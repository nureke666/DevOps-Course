---
title: "05. Интеграции и динамические секреты"
description: "Динамические креды для PostgreSQL, доставка секретов в Kubernetes, интеграция с CI/CD, Ansible и Terraform, ansible-vault vs HashiCorp Vault"
---

# 05. Интеграции и динамические секреты

> Роадмап → Vault: *«другое по желанию»* — здесь как раз то, ради чего Vault внедряют
> по-настоящему.
>
> **После темы ты умеешь:** выдавать временные учётные данные к базам, интегрировать
> Vault с Kubernetes, CI/CD, Ansible и Terraform, и понимать, чем HashiCorp Vault
> отличается от ansible-vault.

---

## 🗺️ Динамические секреты — главная идея

```text:no-line-numbers
 СТАТИЧЕСКИЙ СЕКРЕТ                      ДИНАМИЧЕСКИЙ СЕКРЕТ ⭐
 ──────────────────                      ────────────────────
 один пароль на всех и навсегда          Vault создаёт учётку ПО ЗАПРОСУ
 ротация = отдельный проект              у неё TTL (например, 1 час)
 утечка = доступ навсегда                по истечении Vault сам её УДАЛЯЕТ
 непонятно, кто им пользовался           видно, кому и когда она выдана
```

```text:no-line-numbers
 приложение ──► Vault ──► CREATE USER app_a1b2 ... IN PostgreSQL
                          выдаёт логин/пароль с лизом на 1 час
                                    │
                        через час ──► DROP ROLE app_a1b2
```

---

## 1. Динамические креды для PostgreSQL ⭐

```bash
vault secrets enable database

vault write database/config/app-postgres \
  plugin_name=postgresql-database-plugin \
  allowed_roles="billing-ro,billing-rw" \
  connection_url="postgresql://{{username}}:{{password}}@db.internal:5432/shop?sslmode=require" \
  username="vault_admin" password="..."          # ⭐ отдельная учётка Vault в БД

vault write database/roles/billing-ro \
  db_name=app-postgres \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
                       GRANT CONNECT ON DATABASE shop TO \"{{name}}\"; \
                       GRANT USAGE ON SCHEMA public TO \"{{name}}\"; \
                       GRANT SELECT ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
  default_ttl="1h" max_ttl="24h"

# получить временные креды
vault read database/creds/billing-ro
# username  v-approle-billing-ro-x7Yk...
# password  A1b2C3...
# lease_id  database/creds/billing-ro/abc...
# lease_duration 1h
```
```bash
vault lease renew  database/creds/billing-ro/abc...
vault lease revoke database/creds/billing-ro/abc...
vault lease revoke -prefix database/creds/        # ⭐ отозвать все при инциденте
```

| Плюс | Что это даёт |
|------|--------------|
| Нет «вечного» пароля | Утечка ограничена сроком лиза |
| Персонализация | Видно, какой сервис/человек получил доступ |
| Мгновенный отзыв | Одна команда убирает все выданные учётки |
| Нет ротации вручную | Ротация встроена в механизм |

⚠️ Требования: у Vault должна быть административная учётка в базе; число временных
учёток нужно контролировать (лимит соединений, `max_ttl`); приложение должно уметь
переполучать креды.

Также существует **ротация статических учёток** (`database/static-roles`) — Vault
периодически меняет пароль существующего пользователя.

---

## 2. Vault и Kubernetes: три способа доставки ⭐

```text:no-line-numbers
 1. VAULT AGENT INJECTOR      мутация пода: sidecar получает секреты и кладёт их в файл
 2. VAULT CSI PROVIDER        секреты монтируются как том через Secrets Store CSI Driver
 3. EXTERNAL SECRETS OPERATOR оператор создаёт обычный k8s Secret из данных Vault ⭐
```

```yaml
# 1. Agent Injector — всё делается аннотациями
apiVersion: apps/v1
kind: Deployment
metadata: { name: billing }
spec:
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "billing"
        vault.hashicorp.com/agent-inject-secret-db: "secret/data/prod/billing/db"
        vault.hashicorp.com/agent-inject-template-db: |
          {{- with secret "secret/data/prod/billing/db" -}}
          DB_USER={{ .Data.data.username }}
          DB_PASSWORD={{ .Data.data.password }}
          {{- end }}
    spec:
      serviceAccountName: billing      # ⭐ по нему Vault узнаёт под
```
```yaml
# 3. External Secrets Operator — секрет Vault превращается в обычный Secret
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata: { name: billing-db, namespace: billing }
spec:
  secretStoreRef: { name: vault-backend, kind: ClusterSecretStore }
  target: { name: billing-db }
  refreshInterval: 1h
  data:
    - secretKey: password
      remoteRef: { key: prod/billing/db, property: password }
```

| Способ | Плюсы | Минусы |
|--------|-------|--------|
| Agent Injector | Секрет не становится k8s Secret, поддержка шаблонов и обновления | Sidecar в каждом поде, аннотации в манифестах |
| CSI Provider | Секрет как файл, без sidecar | Нужен CSI-драйвер, меньше гибкости |
| **ESO** ⭐ | Приложение работает с обычным Secret, ничего не знает про Vault; хорошо дружит с GitOps | Секрет всё же материализуется в k8s Secret |

В GitOps-репозитории при этом хранится только ссылка (см. раздел «ArgoCD»).

---

## 3. Vault и CI/CD

```yaml
# GitLab CI с JWT-аутентификацией (без статических секретов) ⭐
deploy:
  id_tokens:
    VAULT_ID_TOKEN: { aud: https://vault.example.com }
  script:
    - export VAULT_ADDR=https://vault.example.com
    - export VAULT_TOKEN="$(vault write -field=token auth/jwt/login role=ci-billing jwt=$VAULT_ID_TOKEN)"
    - export REGISTRY_TOKEN="$(vault kv get -field=token secret/shared/registry)"
    - ./deploy.sh
  after_script:
    - vault token revoke -self || true        # ⭐ отозвать токен в конце работы
```

| Практика | Почему |
|----------|--------|
| JWT/OIDC вместо статических токенов | В CI нечего красть |
| Короткий TTL токена (5-15 минут) | Токен живёт меньше пайплайна |
| `bound_claims` по проекту и ветке | Форк или чужая ветка не получат доступ |
| Отзыв токена в `after_script` | Нет «висящих» доступов |
| Маскирование переменных | Секрет не попадёт в лог |

---

## 4. Vault и Ansible / Terraform

```yaml
# Ansible: lookup-плагин читает секрет из Vault на лету
- name: Настроить приложение
  ansible.builtin.template:
    src: env.j2
    dest: /opt/app/.env
    mode: "0600"
  vars:
    db_password: "{{ lookup('community.hashi_vault.hashi_vault',
                     'secret=secret/data/prod/billing/db:password') }}"
  no_log: true                        # ⭐ обязательно
```
```hcl
# Terraform: чтение секрета и создание динамических кредов
provider "vault" {}                    # адрес и токен — из окружения

data "vault_kv_secret_v2" "db" {
  mount = "secret"
  name  = "prod/billing/db"
}

resource "postgresql_role" "app" {
  name     = "app"
  password = data.vault_kv_secret_v2.db.data["password"]   # ⚠️ попадёт в стейт!
}
```
⚠️ Всё, что Terraform читает из Vault, **оседает в стейте открытым текстом** —
поэтому стейт шифруют и ограничивают доступ (см. раздел «Terraform»).

⭐ Обратная связка: Terraform-провайдером `vault` описывают саму настройку Vault
(движки, политики, роли) — конфигурация хранилища тоже становится кодом.

---

## 5. `ansible-vault` vs HashiCorp Vault ⭐

| | `ansible-vault` | HashiCorp Vault |
|---|-----------------|-----------------|
| Что это | Шифрование файлов в репозитории Ansible | Сервис хранения и выдачи секретов |
| Где секрет | В git (зашифрован) | В хранилище Vault |
| Аутентификация | Один пароль на файл | Методы, роли, SSO |
| Права | Нет ролевого доступа | Политики на пути |
| Аудит | Нет | Есть |
| TTL и отзыв | Нет | Есть |
| Динамические секреты | Нет | ⭐ Есть |
| Когда достаточно | Маленький проект, мало секретов | Зрелый проект, требования безопасности |

Подробнее про `ansible-vault` — см. раздел «Ansible».

---

## 6. Другие полезные движки (обзорно)

| Движок | Что делает | Зачем девопсу |
|--------|-----------|---------------|
| `pki` | Выпускает TLS-сертификаты | Внутренний CA: короткоживущие сертификаты для сервисов |
| `transit` | Шифрование как сервис | Приложение шифрует данные, не храня ключ у себя |
| `ssh` | Подписывает SSH-сертификаты | Доступ к серверам без раскладывания ключей ⭐ |
| `aws`/`gcp` | Временные ключи облака | Нет постоянных ключей доступа |
| `totp` | Одноразовые коды | Второй фактор для сервисов |
| `kubernetes` | Временные ServiceAccount-токены | Доступ к кластеру по запросу |

---

## 7. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| Приложение не умеет переполучать креды | Падение после истечения лиза | Agent/библиотека с renew, повторная аутентификация |
| Слишком короткий TTL без продления | Постоянные сбои | Согласованные TTL и автоматическое продление |
| Нет лимита на число динамических учёток | Упёрлись в `max_connections` БД | `max_ttl`, мониторинг лизов, пул соединений |
| Секреты из Vault в terraform-стейте | Утечка через стейт | Шифрование и ограничение доступа к стейту |
| Секреты в логах Ansible | Утечка | `no_log: true` |
| Статический токен Vault в CI | Кража = доступ к секретам | JWT/OIDC и короткие TTL |
| Vault недоступен при старте подов | Сервисы не поднимаются | HA Vault, кэш агента, graceful-повтор |
| Путают ansible-vault и HashiCorp Vault | Неверные ожидания на собесе | Помнить разницу |

---

## 💼 Как это в DevOps

- Реальная ценность Vault раскрывается именно на динамических секретах: временная
  учётка в базе на час вместо общего пароля, который не меняли три года.
- В Kubernetes чаще всего выбирают External Secrets Operator: приложение работает
  с обычным `Secret`, а платформа отвечает за связь с Vault.
- В CI/CD переходят на JWT/OIDC: это убирает последний статический секрет из пайплайна.
- Настройка Vault (движки, роли, политики) описывается Terraform'ом и проходит ревью —
  иначе никто не знает, у кого какие права.
- На собеседовании очень выигрышно звучит: «на стенде настроил динамические креды
  для PostgreSQL и доступ подов через Kubernetes-метод» — это показывает понимание
  сути, а не только `kv get`.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Динамические креды БД | `vault secrets enable database` + `database/config/*` + `database/roles/*` |
| Получить временные креды | `vault read database/creds/<role>` |
| Продлить/отозвать лиз | `vault lease renew/revoke <lease_id>` |
| Массовый отзыв | `vault lease revoke -prefix database/creds/` |
| Ротация статической учётки | `database/static-roles/*` |
| Секреты в под (sidecar) | Аннотации `vault.hashicorp.com/agent-inject-*` |
| Секреты как k8s Secret | External Secrets Operator (`ExternalSecret`) |
| Секреты как файл | Vault CSI Provider |
| Секреты в CI | JWT/OIDC-роль + короткий TTL + `token revoke -self` |
| Секрет в Ansible | `lookup('community.hashi_vault.hashi_vault', ...)` + `no_log` |
| Секрет в Terraform | `data "vault_kv_secret_v2"` (⚠️ попадёт в стейт) |
| Настройка Vault как код | Terraform-провайдер `vault` |
| Внутренний CA | Движок `pki` |
| SSH без раскладывания ключей | Движок `ssh` (подпись сертификатов) |

---

## 🧠 Что запомнить

1. ⭐ Динамические секреты — главное преимущество Vault: временная учётка создаётся
   по запросу и удаляется по истечении лиза.
2. Для БД нужен движок `database`, конфигурация подключения и роль с SQL-командами
   создания пользователя.
3. Лизы продлеваются и отзываются; массовый отзыв по префиксу — команда для инцидента.
4. В Kubernetes секреты доставляют Agent Injector'ом, CSI-драйвером или ESO;
   в GitOps чаще выбирают ESO.
5. В CI используют JWT/OIDC: никаких статических токенов Vault в пайплайне.
6. Ansible читает секреты lookup-плагином и обязательно с `no_log: true`.
7. Всё, что Terraform читает из Vault, попадает в стейт — стейт защищают.
8. Настройку самого Vault описывают кодом (Terraform-провайдер `vault`).
9. `ansible-vault` — шифрование файлов в репозитории; HashiCorp Vault — сервис
   с политиками, аудитом, TTL и динамическими секретами.
10. Приложения должны переживать истечение лиза и недоступность Vault:
    продление, повторная аутентификация, кэш агента.

---

## Задачи

> Стенд: Vault + PostgreSQL (для динамических кредов) + kind (для Kubernetes-интеграций).

---

### Блок A. Теория

**A1.** ⭐ Что такое динамические секреты и чем они лучше статических?

<details><summary>Ответ</summary>

Учётные данные, создаваемые Vault по запросу на ограниченное время
и автоматически удаляемые по истечении лиза. Лучше тем, что нет «вечного» пароля,
видно, кому выдан доступ, возможен мгновенный массовый отзыв, а ротация встроена.

</details>

**A2.** Что нужно настроить, чтобы Vault выдавал временные учётки PostgreSQL?

<details><summary>Ответ</summary>

Включить движок `database`, настроить подключение (`database/config/...`)
с административной учёткой и разрешёнными ролями, описать роль
(`database/roles/...`) с SQL-командами создания пользователя и TTL.

</details>

**A3.** Зачем Vault отдельная административная учётная запись в базе?

<details><summary>Ответ</summary>

Чтобы Vault мог создавать и удалять роли, но при этом его права были
ограничены и отделены от прикладных; использовать суперпользователя базы —
избыточный риск.

</details>

**A4.** Что такое лиз и как им управляют?

<details><summary>Ответ</summary>

Лиз — запись о сроке жизни выданного динамического секрета. Им управляют
командами `vault lease list/renew/revoke`, в том числе массово по префиксу.

</details>

**A5.** Какие риски у динамических кредов для БД и как их контролировать?

<details><summary>Ответ</summary>

Рост числа временных ролей и соединений, нагрузка на базу, зависимость
доступности приложения от Vault. Контролируется `max_ttl`, лимитами, мониторингом
числа лизов и пулом соединений.

</details>

**A6.** Что делают `database/static-roles`?

<details><summary>Ответ</summary>

Управляют ротацией пароля **существующего** пользователя БД: Vault периодически
меняет его и отдаёт актуальное значение.

</details>

**A7.** Назови три способа доставки секретов Vault в поды Kubernetes.

<details><summary>Ответ</summary>

Vault Agent Injector (sidecar и файлы), Vault CSI Provider (том с секретами),
External Secrets Operator (создаёт обычный k8s Secret).

</details>

**A8.** ⭐ Сравни Agent Injector, CSI Provider и External Secrets Operator.

<details><summary>Ответ</summary>

Injector: секрет не становится k8s Secret, есть шаблоны и обновление,
но нужен sidecar и аннотации. CSI: секрет как файл, без sidecar, меньше гибкости.
ESO: приложение не знает про Vault и работает с обычным Secret, удобно для GitOps,
но секрет материализуется в кластере.

</details>

**A9.** Как под доказывает Vault, что он — это он?

<details><summary>Ответ</summary>

Отправляет токен своего ServiceAccount; Vault проверяет его через TokenReview
API кластера и сверяет имя SA и namespace с настройками роли.

</details>

**A10.** Как правильно организовать доступ CI к Vault?

<details><summary>Ответ</summary>

Через JWT/OIDC-аутентификацию с `bound_claims` по проекту и ветке,
коротким TTL и отзывом токена в конце пайплайна.

</details>

**A11.** Почему токен CI отзывают в конце пайплайна?

<details><summary>Ответ</summary>

Чтобы после завершения работы не оставалось действующего доступа,
даже если TTL ещё не истёк.

</details>

**A12.** Как Ansible получает секреты из Vault и что обязательно добавить?

<details><summary>Ответ</summary>

Lookup-плагином `community.hashi_vault.hashi_vault`; обязательно
`no_log: true` и права `0600` на файлы с секретами.

</details>

**A13.** ⚠️ Что происходит с секретами, которые Terraform читает из Vault?

<details><summary>Ответ</summary>

Они попадают в файл состояния открытым текстом, поэтому стейт нужно шифровать,
ограничивать доступ и хранить в защищённом бакете.

</details>

**A14.** Зачем Terraform-провайдер `vault`?

<details><summary>Ответ</summary>

Чтобы описывать саму конфигурацию Vault (движки, политики, роли, методы)
кодом: воспроизводимость, ревью и история изменений.

</details>

**A15.** ⭐ Чем `ansible-vault` отличается от HashiCorp Vault?

<details><summary>Ответ</summary>

`ansible-vault` — шифрование файлов в репозитории Ansible: нет ролевого доступа,
аудита, TTL и динамических секретов. HashiCorp Vault — сервис с аутентификацией,
политиками, журналом и динамическими секретами.

</details>

---

### Блок B. «Оцени решение»

```text:no-line-numbers
B1.  Приложение использует общий постоянный пароль БД, не менявшийся 3 года
```

<details><summary>Ответ</summary>

Классическая проблема: утечка = вечный доступ, ротация болезненна.

</details>

```text:no-line-numbers
B2.  Приложение получает временные креды с TTL 1 час и умеет их продлевать
```

<details><summary>Ответ</summary>

Целевое состояние.

</details>

```text:no-line-numbers
B3.  У Vault нет отдельной учётки в БД, используется суперпользователь postgres
```

<details><summary>Ответ</summary>

Избыточные права Vault в базе — лишний риск.

</details>

```text:no-line-numbers
B4.  max_ttl динамических кредов не задан, число учёток не мониторится
```

<details><summary>Ответ</summary>

Риск исчерпания соединений и «мусорных» ролей.

</details>

```text:no-line-numbers
B5.  В k8s используется Agent Injector с привязкой к ServiceAccount
```

<details><summary>Ответ</summary>

Хорошая практика.

</details>

```text:no-line-numbers
B6.  ExternalSecret ссылается на путь Vault, в git секретов нет
```

<details><summary>Ответ</summary>

Правильная GitOps-совместимая схема.

</details>

```text:no-line-numbers
B7.  В k8s secret'ы создаются вручную kubectl create secret
```

<details><summary>Ответ</summary>

Ручные секреты — нет истории, воспроизводимости и ротации.

</details>

```text:no-line-numbers
B8.  CI хранит статический токен Vault со сроком год
```

<details><summary>Ответ</summary>

Статический токен в CI — то, от чего уходят.

</details>

```text:no-line-numbers
B9.  CI получает токен через JWT на 10 минут и отзывает его в after_script
```

<details><summary>Ответ</summary>

Современный стандарт.

</details>

```text:no-line-numbers
B10. Ansible печатает пароль в выводе задачи (нет no_log)
```

<details><summary>Ответ</summary>

Утечка в логи — нужен `no_log`.

</details>

```text:no-line-numbers
B11. Terraform читает пароль из Vault, стейт лежит в общем бакете без шифрования
```

<details><summary>Ответ</summary>

Секрет доступен всем, у кого есть доступ к бакету.

</details>

```text:no-line-numbers
B12. Настройка Vault (политики, роли) описана Terraform-провайдером и лежит в git
```

<details><summary>Ответ</summary>

Правильно: конфигурация Vault как код.

</details>

```text:no-line-numbers
B13. Приложение читает креды один раз при старте и падает после истечения лиза
```

<details><summary>Ответ</summary>

Приложение должно уметь продлевать/переполучать креды.

</details>

```text:no-line-numbers
B14. Vault — единственный экземпляр без HA, поды не стартуют при его недоступности
```

<details><summary>Ответ</summary>

Vault становится единой точкой отказа — нужен HA и деградация.

</details>

---

### Блок C. Практика

#### C1. 🔑 Динамические креды PostgreSQL
1. Подними PostgreSQL, создай в нём учётку `vault_admin` с правом создавать роли.
2. Включи движок `database`, настрой подключение и роль `-ro` с TTL 5 минут.
3. Получи креды `vault read database/creds/...`, подключись ими к базе.
4. Дождись истечения и убедись, что пользователь удалён (`\du` в psql).

<details><summary>Ответ</summary>

После истечения TTL роль исчезает из `\du` — это и есть демонстрация
динамических секретов.

</details>

#### C2. Лизы
1. Получи креды, посмотри `vault lease list database/creds/...`.
2. Продли лиз, затем отзови его и проверь, что пользователь удалён немедленно.
3. Отзови все лизы префиксом.

<details><summary>Ответ</summary>

`vault lease revoke` удаляет пользователя немедленно, не дожидаясь TTL.

</details>

#### C3. Ограничения
1. Получи 20 наборов кредов подряд.
2. Посмотри в PostgreSQL, сколько появилось ролей.
3. Подумай и запиши, как это взаимодействует с `max_connections`.

<details><summary>Ответ</summary>

Каждая выдача создаёт отдельную роль и потенциально отдельные соединения —
отсюда требования к `max_ttl` и мониторингу.

</details>

#### C4. Статическая ротация
Настрой `database/static-roles` для существующего пользователя и понаблюдай,
как Vault меняет его пароль по расписанию.

#### C5. 🔑 Kubernetes + Agent Injector
1. Установи Vault в kind (Helm) и включи Kubernetes-метод.
2. Создай роль для ServiceAccount приложения.
3. Добавь аннотации `agent-inject` в Deployment.
4. Проверь, что секрет появился в файле внутри пода.

<details><summary>Ответ</summary>

Признак успеха — файл с секретом внутри пода (обычно `/vault/secrets/...`).

</details>

#### C6. External Secrets Operator
1. Установи ESO, настрой `ClusterSecretStore` на Vault.
2. Создай `ExternalSecret`, проверь появление обычного `Secret`.
3. Измени значение в Vault и убедись, что Secret обновился.

<details><summary>Ответ</summary>

После изменения значения в Vault ESO обновит Secret в течение `refreshInterval`.

</details>

#### C7. CI через JWT
Настрой роль `jwt` для своего проекта, получи токен в пайплайне,
прочитай секрет и отзови токен в `after_script`.

#### C8. Ansible
Напиши плейбук, который получает пароль из Vault lookup-плагином и кладёт его
в файл с правами 600 и `no_log: true`. Проверь, что пароль не виден в выводе.

#### C9. Terraform
1. Прочитай секрет из Vault через `data "vault_kv_secret_v2"`.
2. Найди значение в `terraform.tfstate`.
3. Опиши, какие меры защиты стейта нужны.

<details><summary>Ответ</summary>

В стейте будет видно значение секрета — отсюда требования к его защите.

</details>

#### C10. Vault как код
Опиши Terraform-провайдером `vault`: движок KV, политику и роль AppRole.
Примени и проверь, что всё создалось.

---

### Блок D. Инциденты

**D1.** После истечения лиза приложение потеряло доступ к базе и упало. Как правильно?

<details><summary>Ответ</summary>

Приложение должно продлевать лиз (Vault Agent, клиентская библиотека)
или переполучать креды при ошибке подключения; также помогает пул соединений
с корректной обработкой переподключений.

</details>

**D2.** В PostgreSQL накопились сотни ролей `v-approle-...`. Что произошло?

<details><summary>Ответ</summary>

Множество выданных и не отозванных лизов (слишком частая выдача, длинные TTL,
приложение запрашивает креды при каждом запросе). Нужны разумные TTL, кэширование
и мониторинг числа лизов.

</details>

**D3.** Утечка: нужно немедленно закрыть все выданные доступы к базе. Команды?

<details><summary>Ответ</summary>

`vault lease revoke -prefix database/creds/` (при необходимости —
`vault token revoke -prefix auth/<method>/`), затем проверка ролей в базе
и разбор инцидента.

</details>

**D4.** Под не получает секреты через Agent Injector. Алгоритм разбора.

<details><summary>Ответ</summary>

Логи injector'а и sidecar-контейнера, корректность аннотаций и имени роли,
привязка ServiceAccount и namespace в роли Vault, доступность Vault из кластера,
политики и путь секрета (`data`).

</details>

**D5.** `ExternalSecret` в состоянии ошибки. Что проверить?

<details><summary>Ответ</summary>

Статус и события `ExternalSecret`, настройки `SecretStore` (адрес, auth),
права политики, корректность `remoteRef` (ключ и property), логи оператора.

</details>

**D6.** Пароль из Vault оказался в логах CI. Что делать и что изменить?

<details><summary>Ответ</summary>

Ротировать секрет, включить маскирование переменных, не печатать секреты,
проверить артефакты и логи, перейти на короткие TTL и JWT-аутентификацию.

</details>

**D7.** Пароль из Vault виден в `terraform.tfstate` в общем бакете. Действия.

<details><summary>Ответ</summary>

Ротировать секрет, включить шифрование и ограничить доступ к бакету стейта,
включить версионирование, пересмотреть, какие данные вообще проходят через Terraform.

</details>

**D8.** Ansible-плейбук напечатал пароль в выводе. Как исправить и предотвратить?

<details><summary>Ответ</summary>

Добавить `no_log: true`, проверить, где ещё выводится значение, ротировать
секрет, добавить проверку в ревью плейбуков.

</details>

**D9.** Vault недоступен, новые поды не стартуют. Как проектировать устойчивость?

<details><summary>Ответ</summary>

HA-кластер Vault, auto-unseal, кэширование секретов агентом, повторные попытки
с backoff, возможность стартовать с последними известными значениями, мониторинг.

</details>

**D10.** Коллега говорит: «у нас же есть ansible-vault, зачем ещё Vault?» Ответ.

<details><summary>Ответ</summary>

`ansible-vault` решает только задачу «не хранить пароли в git открытыми»:
нет аудита, ролевого доступа, TTL, отзыва и динамических секретов. HashiCorp Vault
даёт управляемый доступ и ротацию; на зрелом проекте этого требуют безопасность и аудит.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое динамические секреты?

<details><summary>Ответ</summary>

Учётные данные, создаваемые по запросу с ограниченным сроком жизни
и автоматическим удалением.

</details>

**2.** Как настроить выдачу временных кредов к PostgreSQL?

<details><summary>Ответ</summary>

Движок `database`, конфигурация подключения с админ-учёткой, роль с SQL
создания пользователя и TTL.

</details>

**3.** Что такое лиз и как его отозвать?

<details><summary>Ответ</summary>

Запись о сроке жизни выданного секрета; отзывается `vault lease revoke`
(в том числе по префиксу).

</details>

**4.** Как секреты попадают в поды Kubernetes?

<details><summary>Ответ</summary>

Через Agent Injector, CSI Provider или External Secrets Operator; под
аутентифицируется токеном ServiceAccount.

</details>

**5.** Что такое External Secrets Operator?

<details><summary>Ответ</summary>

Оператор, создающий обычные k8s Secret из данных внешнего хранилища
и поддерживающий их актуальность.

</details>

**6.** Как организовать доступ CI к Vault без статических секретов?

<details><summary>Ответ</summary>

Через JWT/OIDC-роль с `bound_claims`, коротким TTL и отзывом токена.

</details>

**7.** Как использовать Vault в Ansible?

<details><summary>Ответ</summary>

Lookup-плагином `hashi_vault` с обязательным `no_log`.

</details>

**8.** Что происходит с секретами, прочитанными Terraform?

<details><summary>Ответ</summary>

Они попадают в стейт открытым текстом; стейт шифруют и ограничивают доступ.

</details>

**9.** Чем ansible-vault отличается от HashiCorp Vault?

<details><summary>Ответ</summary>

Первое — шифрование файлов в репозитории, второе — сервис с политиками,
аудитом, TTL и динамическими секретами.

</details>

**10.** Какие ещё движки Vault знаешь?

<details><summary>Ответ</summary>

`pki`, `transit`, `ssh`, `aws`/`gcp`, `kubernetes`, `totp`.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Настроил динамические креды для PostgreSQL и видел удаление пользователя
- [ ] Управляю лизами: продление, отзыв, массовый отзыв
- [ ] Понимаю риски и ограничения динамических учёток
- [ ] Настроил доступ подов через Kubernetes-метод
- [ ] Пробовал Agent Injector и/или External Secrets Operator
- [ ] Настроил доступ CI через JWT без статических секретов
- [ ] Использую Vault в Ansible с `no_log`
- [ ] Знаю, что секреты Terraform оседают в стейте
- [ ] Описал конфигурацию Vault кодом
- [ ] Могу объяснить разницу ansible-vault и HashiCorp Vault
