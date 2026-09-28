---
title: "02. Что такое Vault и как он устроен"
description: "Архитектура Vault: auth methods, токены, политики, secrets engines, seal/unseal, установка, базовые команды и эксплуатация"
---

# 02. Что такое Vault и как он устроен

> Роадмап → Vault: *«Что это такое · Зачем нужен · Базовые команды»*.
>
> **После темы ты умеешь:** объяснить архитектуру Vault, поднять его, распечатать
> (unseal), пользоваться CLI и UI, понимать токены и политики.

---

## 🗺️ Как устроен Vault

```text:no-line-numbers
        клиенты: человек, приложение, CI, Kubernetes, Terraform
                              │ HTTPS API
                              ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │ VAULT                                                                 │
 │  ┌──────────────┐  «кто ты?»          ┌────────────────────────────┐  │
 │  │ AUTH METHODS │────────────────────►│ ТОКЕН (с TTL и политиками) │  │
 │  │ token, userpass, approle,          └─────────────┬──────────────┘  │
 │  │ kubernetes, oidc, ldap, aws…                     │                 │
 │  └──────────────┘                                   ▼                 │
 │                                        ┌────────────────────────────┐ │
 │  ┌──────────────┐  «что тебе можно?»   │ ПОЛИТИКИ (policies)        │ │
 │  │  POLICIES    │◄─────────────────────┤ path "secret/data/app/*"   │ │
 │  └──────────────┘                      │ capabilities = ["read"]    │ │
 │                                        └─────────────┬──────────────┘ │
 │  ┌───────────────────────────────────────────────────▼─────────────┐  │
 │  │ SECRETS ENGINES                                                 │  │
 │  │ kv (статические) · database (динамические) · pki · transit · aws│  │
 │  └───────────────────────────────┬─────────────────────────────────┘  │
 │                                  ▼                                    │
 │  ┌──────────────┐    всё шифруется master-ключом ──► STORAGE BACKEND  │
 │  │ AUDIT DEVICES│    (Raft, Consul, файл, облако)                     │
 │  └──────────────┘    ⭐ Vault хранит шифротекст, не открытые данные    │
 └───────────────────────────────────────────────────────────────────────┘
```

Четыре понятия, из которых состоит вся работа с Vault:
1. **Auth method** — как ты доказываешь, кто ты (получаешь токен).
2. **Policy** — что этому токену разрешено (пути и права).
3. **Secrets engine** — откуда берутся секреты (хранимые или создаваемые на лету).
4. **Audit device** — журнал всех обращений.

---

## 1. Seal / Unseal ⭐

```text:no-line-numbers
 Vault стартует ЗАПЕЧАТАННЫМ (sealed):
   данные в хранилище зашифрованы, master-ключ не собран, API отвечает «sealed»
                    │
                    │ unseal: нужно ввести K из N ключей (схема Шамира)
                    ▼
   Vault распечатан (unsealed) → выдаёт и принимает секреты
```

```bash
vault operator init -key-shares=5 -key-threshold=3
# ⚠️ выводит 5 unseal-ключей и initial root token — ЕДИНСТВЕННЫЙ раз
# ключи раздают разным людям, root-токен используют для первичной настройки и отзывают

vault operator unseal   # ввести 3 разных ключа
vault status            # Sealed: false
```

| Режим unseal | Комментарий |
|--------------|-------------|
| Ключи Шамира вручную | Безопасно, но при каждом рестарте нужны люди |
| **Auto-unseal** ⭐ | Мастер-ключ шифруется внешним KMS (облако, HSM, Transit другого Vault) — рестарт не требует ручных действий |

> ⚠️ Потеря unseal-ключей = потеря всех секретов. Их хранят раздельно,
> в разных местах и у разных людей.

---

## 2. Установка

```bash
# --- dev-режим: для учёбы ---
docker run -d --name vault --cap-add=IPC_LOCK \
  -e VAULT_DEV_ROOT_TOKEN_ID=root -p 8200:8200 hashicorp/vault:latest
export VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=root
```
```text:no-line-numbers
⚠️ dev-режим: данные в памяти, Vault сразу распечатан, root-токен известен,
TLS нет. Никогда не используется дальше учебного стенда.
```

```hcl
# --- прод-подобная конфигурация (Raft) ---
storage "raft" {
  path    = "/vault/data"
  node_id = "vault-1"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_cert_file = "/vault/tls/tls.crt"
  tls_key_file  = "/vault/tls/tls.key"
}

seal "awskms" {                    # auto-unseal (пример)
  region     = "eu-central-1"
  kms_key_id = "..."
}

api_addr     = "https://vault-1.example.com:8200"
cluster_addr = "https://vault-1.example.com:8201"
ui           = true
```

| Вариант развёртывания | Когда |
|------------------------|-------|
| Docker/dev | Учёба |
| systemd на VM + Raft | Классический прод |
| Helm-чарт в Kubernetes | ⭐ Если платформа уже в k8s |
| Managed (HCP Vault, облачные аналоги) | Если не хочется эксплуатировать самим |

Прод-требования: минимум 3 узла Raft (кворум), TLS, auto-unseal, бэкапы снапшотов,
мониторинг, аудит.

---

## 3. Базовые команды ⭐

```bash
export VAULT_ADDR=https://vault.example.com

vault status                       # запечатан ли, версия, узлы кластера
vault login                        # интерактивный вход (метод по умолчанию — token)
vault login -method=userpass username=alice

# --- секреты (KV, подробнее в теме 03) ---
vault kv put    secret/app/db username=app password=s3cr3t
vault kv get    secret/app/db
vault kv get -field=password secret/app/db      # ⭐ только значение, для скриптов
vault kv list   secret/app
vault kv delete secret/app/db

# --- токены ---
vault token create -policy=app-read -ttl=1h
vault token lookup                 # чей токен, какие политики, сколько живёт
vault token renew
vault token revoke <token>         # ⭐ мгновенный отзыв

# --- политики ---
vault policy list
vault policy read app-read
vault policy write app-read app-read.hcl

# --- движки и методы ---
vault secrets list
vault secrets enable -path=kv kv-v2
vault auth list
vault auth enable userpass

# --- всё через HTTP API (важно для приложений) ---
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault.example.com/v1/secret/data/app/db | jq .data.data
```

---

## 4. Токены

```text:no-line-numbers
 аутентификация ──► ТОКЕН ──► все дальнейшие запросы идут с ним
                     │
                     ├── policies: что можно
                     ├── ttl: сколько живёт (по умолчанию ограничен)
                     ├── renewable: можно ли продлевать
                     └── max_ttl: дольше уже нельзя
```

| Тип токена | Смысл |
|------------|-------|
| **root** | Всё можно; ⭐ используется только для первичной настройки и аварий, затем отзывается |
| service token | Обычный токен от auth method, с политиками и TTL |
| batch token | Лёгкий, не хранится в Vault, не продлевается — для массовых операций |
| periodic | Продлевается бесконечно (для долгоживущих сервисов) |

```bash
vault token create -orphan -policy=ci -ttl=15m -use-limit=3   # одноразовые сценарии
vault token revoke -self
vault token revoke -prefix auth/approle/     # отзыв группы токенов
```

⭐ Практика: root-токен генерируют, настраивают auth-методы и политики,
затем **отзывают** (`vault token revoke`), а для восстановления доступа используют
`vault operator generate-root` с unseal-ключами.

---

## 5. Политики (policies)

```hcl
# app-read.hcl — приложение читает только свой путь
path "secret/data/app/*" {
  capabilities = ["read"]
}
path "secret/metadata/app/*" {
  capabilities = ["list"]
}

# devops.hcl — команда управляет своим разделом
path "secret/data/team-a/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "sys/policies/acl" {
  capabilities = ["deny"]            # ⭐ явный запрет побеждает разрешения
}
```

| Capability | Что разрешает |
|------------|---------------|
| `create` / `update` | Запись (в KV v2 для записи обычно нужны обе) |
| `read` | Чтение |
| `delete` | Удаление |
| `list` | Просмотр списка путей |
| `sudo` | Привилегированные пути (`sys/*`) |
| `deny` | Явный запрет (имеет приоритет) |

```bash
vault policy write app-read app-read.hcl
vault token create -policy=app-read
# проверка: под этим токеном read работает, write — «permission denied»
```

⭐ Правило: политика пишется на **пути**, а путь в Vault — это API-эндпоинт.
Для KV v2 чтение секрета `secret/app/db` — это путь `secret/data/app/db`,
а метаданные — `secret/metadata/app/db`. Это самая частая ошибка новичков.

---

## 6. Аудит

```bash
vault audit enable file file_path=/vault/logs/audit.log
vault audit list
```
```text:no-line-numbers
В журнале: кто (токен/идентичность), когда, какой путь, какая операция, результат.
⭐ Значения секретов в журнале захешированы — сам секрет там не хранится.
⚠️ Если ВСЕ audit-устройства недоступны (например, кончилось место), Vault
перестаёт отвечать: он не работает без возможности записать аудит.
```

Журнал аудита отправляют в централизованное логирование (в тот же стек,
что и логи остальных сервисов) и хранят дольше обычных логов.

---

## 7. Эксплуатация

| Задача | Как |
|--------|-----|
| Бэкап | `vault operator raft snapshot save backup.snap` ⭐ |
| Восстановление | `vault operator raft snapshot restore backup.snap` |
| Кластер | 3-5 узлов Raft, `vault operator raft list-peers` |
| Обновление | Rolling: сначала standby-узлы, затем step-down лидера |
| Мониторинг | Метрики Prometheus (`/v1/sys/metrics?format=prometheus`): запечатан ли, число токенов, задержки |
| Алерты | ⭐ `vault_core_unsealed == 0`, недоступность, рост ошибок, приближение TTL сертификатов |
| Доступность | Vault — критический сервис: если он лежит, сервисы не получают секреты |

```text:no-line-numbers
vault_core_unsealed == 0                       # запечатан — критический алерт
up{job="vault"} == 0
rate(vault_audit_log_request_failure[5m]) > 0  # проблемы с аудитом
```

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| dev-режим в «почти проде» | Данные в памяти, root-токен известен | Только для учёбы |
| Потеря unseal-ключей | Секреты невозможно восстановить | Раздельное хранение, auto-unseal, документированная процедура |
| Root-токен «на каждый день» | Обход всех политик, нет разграничения | Отозвать, работать по auth-методам |
| Политика на `secret/app/*` вместо `secret/data/app/*` | «Permission denied» при KV v2 | Помнить про `data`/`metadata` |
| Нет аудита | Невозможно расследовать инцидент | Включить audit device + вывоз логов |
| Один узел без бэкапов | Потеря всех секретов | Raft-кластер + снапшоты |
| Нет мониторинга seal-статуса | Vault запечатался после рестарта, сервисы встали | Алерт на `vault_core_unsealed` |
| Бесконечные TTL у токенов | Утечка = вечный доступ | Разумные TTL и renew |

---

## 💼 Как это в DevOps

- Vault — критический сервис: его недоступность означает, что приложения не смогут
  получить секреты при старте. Отсюда требования к HA, бэкапам и мониторингу.
- Настройка Vault (политики, auth-методы, движки) описывается кодом — Terraform-провайдером
  `vault` — и проходит ревью, как любая инфраструктура.
- Root-токен живёт минуты: им настраивают доступы и отзывают; аварийное восстановление —
  через unseal-ключи и `generate-root`.
- Журнал аудита уезжает в централизованное логирование и используется при расследованиях.
- На собеседовании достаточно уверенно объяснить: auth → токен → политика → движок,
  что такое unseal и почему root-токен не используют постоянно.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Статус | `vault status` |
| Инициализация | `vault operator init -key-shares=5 -key-threshold=3` |
| Распечатать | `vault operator unseal` (K ключей) |
| Войти | `vault login` / `vault login -method=userpass username=alice` |
| Записать секрет | `vault kv put secret/app/db password=...` |
| Прочитать секрет | `vault kv get secret/app/db` |
| Только значение | `vault kv get -field=password secret/app/db` |
| Список движков/методов | `vault secrets list` / `vault auth list` |
| Включить движок | `vault secrets enable -path=kv kv-v2` |
| Включить метод | `vault auth enable approle` |
| Политика | `vault policy write NAME file.hcl` |
| Токен с политикой | `vault token create -policy=NAME -ttl=1h` |
| Информация о токене | `vault token lookup` |
| Отозвать токен | `vault token revoke <token>` |
| Включить аудит | `vault audit enable file file_path=/vault/logs/audit.log` |
| Бэкап | `vault operator raft snapshot save backup.snap` |
| Метрики | `GET /v1/sys/metrics?format=prometheus` |

---

## 🧠 Что запомнить

1. Логика Vault: auth method → токен с TTL → политики → secrets engine, и всё
   пишется в аудит.
2. ⭐ После старта Vault запечатан; распечатывается K из N ключей Шамира
   или auto-unseal через KMS.
3. Потеря unseal-ключей означает потерю всех секретов.
4. dev-режим — только для учёбы: память, известный root-токен, без TLS.
5. Root-токен используют для первичной настройки и отзывают.
6. Политики пишутся на пути API; для KV v2 это `secret/data/...` и `secret/metadata/...`.
7. `deny` в политике имеет приоритет над разрешениями.
8. Аудит обязателен; при недоступности всех audit-устройств Vault перестаёт отвечать.
9. Прод — Raft-кластер из 3-5 узлов, TLS, auto-unseal, снапшоты, мониторинг
   `vault_core_unsealed`.
10. Конфигурацию Vault описывают кодом (Terraform-провайдер), а не кликами в UI.

---

## Задачи

> Стенд: Vault в dev-режиме для быстрых заданий + Vault с файловым/Raft-хранилищем
> для заданий про seal/unseal.

---

### Блок A. Теория

**A1.** Из каких четырёх «кирпичиков» состоит работа с Vault?

<details><summary>Ответ</summary>

Auth method (кто ты) → токен с TTL и политиками → policy (что можно) →
secrets engine (откуда секрет), плюс сквозной аудит.

</details>

**A2.** ⭐ Что такое seal/unseal и зачем это нужно?

<details><summary>Ответ</summary>

Данные в хранилище зашифрованы мастер-ключом, который после старта
не собран: Vault «запечатан» и не обслуживает запросы. Unseal — процесс сборки
ключа и перехода в рабочее состояние.

</details>

**A3.** Что делает `vault operator init` и что он выводит?

<details><summary>Ответ</summary>

Инициализирует хранилище, генерирует мастер-ключ, разбивает его на N частей
(unseal-ключи) и выводит их вместе с начальным root-токеном — единственный раз.

</details>

**A4.** Что такое схема Шамира и зачем K из N?

<details><summary>Ответ</summary>

Разделение секрета на N частей так, что для восстановления нужно любые K из них.
Это защищает от единоличного контроля и от потери одного ключа.

</details>

**A5.** Что такое auto-unseal и когда он нужен?

<details><summary>Ответ</summary>

Мастер-ключ шифруется внешним KMS (облачный сервис, HSM, Transit другого Vault),
и Vault распечатывается автоматически при старте. Нужен там, где рестарты частые
и ручной unseal неприемлем.

</details>

**A6.** Чем опасна потеря unseal-ключей?

<details><summary>Ответ</summary>

Без K ключей мастер-ключ не восстановить: расшифровать хранилище невозможно,
все секреты потеряны.

</details>

**A7.** Чем dev-режим отличается от боевого и почему его нельзя использовать в проде?

<details><summary>Ответ</summary>

Dev: данные в памяти, автоматический unseal, известный root-токен, без TLS.
Всё это делает его непригодным для чего-либо, кроме обучения.

</details>

**A8.** Что такое storage backend? Назови варианты.

<details><summary>Ответ</summary>

Место, где Vault хранит зашифрованные данные: Raft (встроенный, рекомендуемый),
Consul, файл, облачные хранилища и БД.

</details>

**A9.** Что такое токен и какие у него атрибуты?

<details><summary>Ответ</summary>

Токен — результат аутентификации; атрибуты: список политик, TTL, max TTL,
возможность продления, количество использований, привязка к сущности (identity).

</details>

**A10.** Какие бывают типы токенов?

<details><summary>Ответ</summary>

Root, service (обычный), batch (лёгкий, не хранится, не продлевается),
periodic (продлевается неограниченно), orphan (без родителя).

</details>

**A11.** ⭐ Почему root-токен не используют в повседневной работе и что с ним делают?

<details><summary>Ответ</summary>

Он обходит все политики и не ограничен по правам. Его используют для первичной
настройки и аварий, после чего отзывают; восстановление — через `generate-root`
с unseal-ключами.

</details>

**A12.** Как устроены политики? Какие есть capabilities?

<details><summary>Ответ</summary>

Политика — набор правил на пути API с перечислением capabilities:
`create`, `read`, `update`, `delete`, `list`, `sudo`, `deny`. Явный `deny` побеждает.

</details>

**A13.** Почему политика на `secret/app/*` не работает с KV v2?

<details><summary>Ответ</summary>

Потому что в KV v2 данные доступны по пути `secret/data/...`,
а метаданные — по `secret/metadata/...`; политика должна указывать реальные API-пути.

</details>

**A14.** Что попадает в журнал аудита и что произойдёт, если аудит недоступен?

<details><summary>Ответ</summary>

Кто, когда, к какому пути и с какой операцией обращался и каков результат;
значения секретов хешируются. Если все audit-устройства недоступны, Vault перестаёт
обслуживать запросы — он не работает без записи аудита.

</details>

**A15.** Что мониторят у Vault и какой алерт самый важный?

<details><summary>Ответ</summary>

Состояние seal (`vault_core_unsealed`), доступность, ошибки аудита, задержки,
число токенов и лизов; самый важный алерт — Vault запечатан или недоступен.

</details>

---

### Блок B. «Что делает команда / что тут не так»

```bash
B1.  vault status
```

<details><summary>Ответ</summary>

Показывает состояние: запечатан ли, версия, узлы.

</details>

```bash
B2.  vault operator init -key-shares=5 -key-threshold=3
```

<details><summary>Ответ</summary>

Инициализация с пятью ключами и порогом три.

</details>

```bash
B3.  vault operator unseal
```

<details><summary>Ответ</summary>

Ввод одного unseal-ключа (нужно повторить K раз).

</details>

```bash
B4.  vault kv get -field=password secret/app/db
```

<details><summary>Ответ</summary>

Чтение конкретного поля — удобно в скриптах.

</details>

```bash
B5.  vault token create -policy=app-read -ttl=1h
```

<details><summary>Ответ</summary>

Создание токена с политикой и сроком жизни.

</details>

```bash
B6.  vault token lookup
```

<details><summary>Ответ</summary>

Информация о текущем токене.

</details>

```bash
B7.  vault token revoke <token>
```

<details><summary>Ответ</summary>

Немедленный отзыв токена.

</details>

```bash
B8.  vault policy write app-read app-read.hcl
```

<details><summary>Ответ</summary>

Запись политики из файла.

</details>

```bash
B9.  vault audit enable file file_path=/vault/logs/audit.log
```

<details><summary>Ответ</summary>

Включение файлового аудита.

</details>

```bash
B10. vault operator raft snapshot save backup.snap
```

<details><summary>Ответ</summary>

Снапшот Raft — основной бэкап.

</details>

Оцени решения:

```text:no-line-numbers
B11. Vault запущен в dev-режиме на проде
```

<details><summary>Ответ</summary>

Dev на проде — потеря данных при рестарте и известный root-токен.

</details>

```text:no-line-numbers
B12. Unseal-ключи лежат в одном файле у одного инженера
```

<details><summary>Ответ</summary>

Все ключи у одного человека обесценивают схему Шамира.

</details>

```text:no-line-numbers
B13. Auto-unseal через облачный KMS, ключи Шамира в сейфе как резерв
```

<details><summary>Ответ</summary>

Хорошая практика.

</details>

```text:no-line-numbers
B14. Приложения ходят в Vault с root-токеном
```

<details><summary>Ответ</summary>

Root-токен у приложений — отсутствие разграничения и аудита по ролям.

</details>

```text:no-line-numbers
B15. Политика: path "secret/app/*" { capabilities = ["read"] }  при KV v2
```

<details><summary>Ответ</summary>

Политика не сработает: нужен путь `secret/data/app/*`.

</details>

```text:no-line-numbers
B16. Аудит выключен, "чтобы не забивать диск"
```

<details><summary>Ответ</summary>

Без аудита невозможно расследование; кроме того, это требование безопасности.

</details>

```text:no-line-numbers
B17. Один узел Vault без снапшотов
```

<details><summary>Ответ</summary>

Единственный узел без снапшотов — риск полной потери.

</details>

```text:no-line-numbers
B18. Токены выдаются без TTL
```

<details><summary>Ответ</summary>

Бессрочные токены превращают утечку в постоянный доступ.

</details>

---

### Блок C. Практика

#### C1. 🔑 Dev-режим и первые команды
1. Подними Vault в dev-режиме.
2. Выполни `vault status`, зайди в UI.
3. Запиши и прочитай секрет, получи только значение поля.
4. Посмотри `vault secrets list` и `vault auth list`.

#### C2. ⭐ Боевой режим: init и unseal
1. Запусти Vault с файловым (или Raft) хранилищем, без dev-режима.
2. Выполни `vault operator init`, сохрани ключи и root-токен.
3. Перезапусти Vault и убедись, что он запечатан.
4. Распечатай его, наблюдая, как меняется `vault status`.
5. Попробуй распечатать двумя ключами из трёх необходимых — что произойдёт?

<details><summary>Ответ</summary>

С недостаточным числом ключей Vault остаётся запечатанным и показывает
прогресс `Unseal Progress: 2/3`.

</details>

#### C3. Токены
1. Создай токен с TTL 2 минуты.
2. Посмотри `vault token lookup` под ним.
3. Дождись истечения и попробуй использовать.
4. Создай продлеваемый токен и продли его.

<details><summary>Ответ</summary>

По истечении TTL токен становится недействительным: любые запросы вернут
ошибку авторизации.

</details>

#### C4. 🔑 Политики
1. Напиши политику только на чтение `secret/data/app/*`.
2. Создай токен с этой политикой.
3. Проверь: чтение работает, запись — `permission denied`.
4. Добавь `deny` на подпуть и убедись, что запрет побеждает.

#### C5. Ошибка с путями KV v2
Намеренно напиши политику на `secret/app/*`, получи `permission denied`
и исправь на `secret/data/app/*`. Запиши вывод — это частый вопрос на собеседовании.

<details><summary>Ответ</summary>

Ошибка будет вида `permission denied`; после исправления пути на `secret/data/...`
чтение заработает.

</details>

#### C6. Root-токен
1. Создай рабочего пользователя/метод аутентификации.
2. Отзови root-токен (`vault token revoke`).
3. Восстанови root-доступ через `vault operator generate-root` с unseal-ключами.

#### C7. Аудит
1. Включи файловый аудит.
2. Выполни чтение секрета и найди запись в журнале.
3. Проверь, что значение секрета захешировано.
4. Сделай каталог аудита недоступным и посмотри, что произойдёт с Vault
   (затем верни обратно).

<details><summary>Ответ</summary>

В журнале видно `hmac-sha256:...` вместо значений — сам секрет не хранится.
При недоступности аудита Vault перестаёт отвечать на запросы.

</details>

#### C8. Бэкап
Сделай снапшот Raft, удали секрет, восстанови снапшот и проверь, что секрет вернулся.

#### C9. Метрики
Получи метрики `/v1/sys/metrics?format=prometheus`, добавь Vault как таргет
в Prometheus, построй панель и алерт на `vault_core_unsealed == 0`.

<details><summary>Ответ</summary>

`vault_core_unsealed` равен 1, когда Vault распечатан; 0 — повод для
критического алерта.

</details>

#### C10. Vault как код
Опиши базовую настройку (движок KV, политику, метод аутентификации)
Terraform-провайдером `vault` или скриптом в репозитории.

---

### Блок D. Инциденты

**D1.** После перезапуска сервера Vault не отвечает, `vault status` показывает
`Sealed: true`. Что делать?

<details><summary>Ответ</summary>

Распечатать Vault (ввести K ключей) или проверить работу auto-unseal;
затем разобраться, почему не сработала автоматика, и добавить алерт.

</details>

**D2.** Приложения перестали стартовать: не могут получить секреты. Алгоритм разбора.

<details><summary>Ответ</summary>

Проверить доступность и seal-статус Vault, валидность токенов/ролей,
срок действия лизов, политики, сеть и TLS, логи приложений и аудита.

</details>

**D3.** Unseal-ключи утеряны. Что можно сделать?

<details><summary>Ответ</summary>

Если нет auto-unseal и рабочих копий ключей — данные невосстановимы;
остаётся пересоздать Vault и заново заполнить секреты из других источников.
Именно поэтому ключи хранят раздельно и документируют процедуру.

</details>

**D4.** Root-токен утёк. Порядок действий.

<details><summary>Ответ</summary>

Немедленно отозвать root-токен, проверить аудит на его использование,
ротировать критичные секреты, к которым он давал доступ, и разобрать,
почему он вообще существовал постоянно.

</details>

**D5.** Политика выглядит правильной, но клиент получает `permission denied`. Причины?

<details><summary>Ответ</summary>

Неверный путь (KV v2 `data`/`metadata`), отсутствие `list` для листинга,
другой namespace/mount, действующий `deny`, токен без нужной политики,
истёкший токен.

</details>

**D6.** Vault перестал отвечать, в логах ошибки записи аудита. Что произошло?

<details><summary>Ответ</summary>

Все audit-устройства недоступны (нет места, нет прав) — Vault намеренно
прекращает обслуживание запросов.

</details>

**D7.** Диск под Vault заполнен. Чем это грозит и что делать?

<details><summary>Ответ</summary>

Vault может перестать работать (в том числе из-за аудита и хранилища);
нужно освободить место, настроить ротацию журналов и алерт на диск.

</details>

**D8.** Нужно обновить Vault-кластер без простоя. Как?

<details><summary>Ответ</summary>

Rolling-обновление: обновляют standby-узлы, проверяют кластер,
затем выполняют `vault operator step-down` на лидере и обновляют его.

</details>

**D9.** Токен приложения истёк в неподходящий момент. Как правильно организовать TTL?

<details><summary>Ответ</summary>

Использовать продлеваемые токены и клиентские библиотеки/агент,
которые продлевают лиз; для приложений — auth-метод с автоматическим получением
нового токена (AppRole/Kubernetes), а не «вечный» токен.

</details>

**D10.** Vault — единая точка отказа: при его падении не стартуют сервисы.
Как снизить риск?

<details><summary>Ответ</summary>

HA-кластер, auto-unseal, кэширование секретов на стороне приложения/агента,
graceful-поведение при недоступности (использовать последние полученные значения),
мониторинг и отработанная процедура восстановления.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Vault и зачем он нужен?

<details><summary>Ответ</summary>

Централизованный сервис хранения и выдачи секретов с аутентификацией, политиками,
TTL, аудитом и динамическими секретами.

</details>

**2.** Как Vault хранит секреты?

<details><summary>Ответ</summary>

В зашифрованном виде в storage backend; ключ шифрования собирается при unseal.

</details>

**3.** Что такое unseal и как он работает?

<details><summary>Ответ</summary>

Сборка мастер-ключа из K частей (Шамир) для перехода в рабочее состояние.

</details>

**4.** Что такое auto-unseal?

<details><summary>Ответ</summary>

Автоматическая распечатка с помощью внешнего KMS/HSM.

</details>

**5.** Что такое токен и какие у него параметры?

<details><summary>Ответ</summary>

Результат аутентификации с политиками, TTL, возможностью продления и отзыва.

</details>

**6.** Как устроены политики?

<details><summary>Ответ</summary>

Правила на путях API с набором capabilities; `deny` приоритетен.

</details>

**7.** Почему не стоит пользоваться root-токеном?

<details><summary>Ответ</summary>

Он обходит политики; используется только для первичной настройки и аварий.

</details>

**8.** Что пишется в журнал аудита?

<details><summary>Ответ</summary>

Кто, когда, какой путь и операция, результат; значения секретов хешируются.

</details>

**9.** Как делают бэкап Vault?

<details><summary>Ответ</summary>

Снапшотами Raft (`snapshot save/restore`), с защищённым хранением снапшотов.

</details>

**10.** Что мониторите у Vault?

<details><summary>Ответ</summary>

Seal-статус, доступность, ошибки аудита, задержки, количество токенов и лизов.

</details>

---

### 🎯 Чек-лист

- [ ] Поднял Vault в dev и в боевом режиме
- [ ] ⭐ Прошёл `init` и `unseal`, понимаю схему Шамира
- [ ] Знаю, что такое auto-unseal и зачем он
- [ ] Создавал токены с TTL и отзывал их
- [ ] Написал политику и проверил `permission denied`
- [ ] Помню про пути `secret/data/...` в KV v2
- [ ] Отозвал root-токен и восстанавливал доступ
- [ ] Включил аудит и нашёл запись о чтении секрета
- [ ] Сделал и восстановил снапшот
- [ ] Настроил метрики и алерт на запечатанный Vault
