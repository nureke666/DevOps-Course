---
title: "04. Auth methods и политики"
description: "Способы аутентификации для людей, приложений, CI и Kubernetes, политики Vault, TTL, лизы и отзыв доступа"
---

# 04. Auth methods и политики ⭐

> Роадмап → Vault: *«auth methods»*.
>
> **После темы ты умеешь:** выбрать способ аутентификации для человека, приложения,
> CI и Kubernetes, написать политику и управлять сроками жизни доступа.

---

## 🗺️ Логика доступа

```text:no-line-numbers
   КТО? ──────────► AUTH METHOD ──────────► ТОКЕН ──────────► ПОЛИТИКА ──► СЕКРЕТ
 человек            userpass / OIDC / LDAP    TTL, renew        что можно
 приложение         approle / kubernetes      max_ttl           на каких путях
 CI/CD              approle / jwt (OIDC)      отзыв
 облачная ВМ        aws / gcp / azure
```

Один принцип: **аутентификация отвечает «кто ты», политика — «что тебе можно»**,
и всё это ограничено временем.

---

## 1. Обзор методов

| Метод | Для кого | Комментарий |
|-------|----------|-------------|
| `token` | Служебное | Базовый; токен уже есть |
| `userpass` | Люди (небольшие команды) | Логин/пароль, просто, но без SSO |
| `ldap` / `oidc` | ⭐ Люди в компании | Вход через корпоративный каталог/SSO, группы → политики |
| `approle` | ⭐ Приложения, CI вне k8s | RoleID + SecretID |
| `kubernetes` | ⭐ Поды в кластере | ServiceAccount-токен как доказательство личности |
| `jwt` | CI (GitLab/GitHub OIDC) | ⭐ Без хранения секретов в пайплайне |
| `aws` / `gcp` / `azure` | ВМ и сервисы в облаке | Метаданные инстанса вместо ключей |
| `cert` | Сервисы с mTLS | Клиентский сертификат |

```bash
vault auth list
vault auth enable userpass
vault auth enable approle
vault auth enable kubernetes
vault auth disable userpass
```

---

## 2. Политики

```hcl
# policies/app-billing.hcl
path "secret/data/prod/billing/*" {
  capabilities = ["read"]
}
path "secret/metadata/prod/billing/*" {
  capabilities = ["list"]
}
path "database/creds/billing-ro" {          # динамические креды (тема 05)
  capabilities = ["read"]
}
```
```hcl
# policies/devops.hcl
path "secret/*"        { capabilities = ["create","read","update","delete","list"] }
path "sys/policies/*"  { capabilities = ["read","list"] }
path "secret/data/prod/finance/*" { capabilities = ["deny"] }   # ⭐ запрет сильнее
```
```bash
vault policy write app-billing policies/app-billing.hcl
vault policy list
vault policy read app-billing
```

| Приём | Зачем |
|-------|-------|
| Политика на сервис, а не на человека | Проще выдавать и отзывать |
| Шаблоны путей <code v-pre>{{identity.entity.name}}</code> | Персональные пути без копипасты |
| `deny` для чувствительных разделов | Явный запрет поверх широких прав |
| Минимальные capabilities | Читать — значит только `read` |
| Разделение prod/stage/dev политиками | Изоляция окружений |

```hcl
# шаблон: каждый пользователь видит только свой путь
path "secret/data/users/{{identity.entity.name}}/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
```

---

## 3. `userpass` и OIDC — доступ для людей

```bash
# userpass (учебный/небольшой контур)
vault auth enable userpass
vault write auth/userpass/users/alice password=changeme policies=devops ttl=8h
vault login -method=userpass username=alice
```

```bash
# OIDC/LDAP — так делают в компаниях
vault auth enable oidc
vault write auth/oidc/config \
  oidc_discovery_url="https://keycloak.example.com/realms/company" \
  oidc_client_id="vault" oidc_client_secret="..." default_role="default"

vault write auth/oidc/role/default \
  bound_audiences="vault" allowed_redirect_uris="https://vault.example.com/ui/vault/auth/oidc/oidc/callback" \
  user_claim="sub" policies="readonly" ttl=8h

vault login -method=oidc        # откроется браузер
```
⭐ В компаниях людей аутентифицируют через SSO: увольнение закрывает доступ
централизованно, а группы каталога маппятся на политики Vault.

---

## 4. `approle` — для приложений и CI ⭐

```text:no-line-numbers
 RoleID    = «логин» роли      (не секрет, может лежать в конфиге)
 SecretID  = «пароль»          (секрет, короткоживущий, выдаётся по запросу)
 RoleID + SecretID ──► токен с политиками роли
```

```bash
vault auth enable approle

vault write auth/approle/role/billing \
  token_policies="app-billing" \
  token_ttl=1h token_max_ttl=4h \
  secret_id_ttl=10m secret_id_num_uses=1 \
  bind_secret_id=true \
  token_bound_cidrs="10.0.1.0/24"        # ⭐ ограничение по сети

vault read auth/approle/role/billing/role-id
vault write -f auth/approle/role/billing/secret-id

# приложение логинится
vault write auth/approle/login role_id=... secret_id=...
```

| Практика AppRole | Почему |
|------------------|--------|
| `secret_id_ttl` короткий, `num_uses=1` | Даже перехваченный SecretID быстро бесполезен |
| SecretID выдаёт доверенный процесс (response wrapping) | Разделение: кто выдаёт и кто использует |
| `token_bound_cidrs` | Токен работает только из нужной сети |
| Разные роли для разных сервисов | Точечные права и отзыв |

**Response wrapping** — выдать SecretID в «обёртке», которую можно распаковать один раз:
```bash
vault write -wrap-ttl=60s -f auth/approle/role/billing/secret-id
vault unwrap <wrapping_token>       # ⭐ если кто-то распаковал раньше — факт компрометации виден
```

---

## 5. `kubernetes` — для подов ⭐

```text:no-line-numbers
 под с ServiceAccount ──► отправляет свой SA-токен в Vault
                          Vault проверяет его в API кластера
                          ⇒ выдаёт токен Vault с политиками роли
```

```bash
vault auth enable kubernetes

vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc" \
  token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

vault write auth/kubernetes/role/billing \
  bound_service_account_names=billing \
  bound_service_account_namespaces=billing \
  policies=app-billing ttl=1h
```
Дальше секреты доставляются Agent Injector'ом или External Secrets Operator —
подробнее в [«Интеграции и динамические секреты»](/vault/05-vault-integrations).

---

## 6. `jwt`/OIDC для CI ⭐

```text:no-line-numbers
 GitLab/GitHub выдают пайплайну JWT с проверяемыми claims
 (проект, ветка, окружение) ──► Vault проверяет подпись и claims ──► токен

 ⭐ В CI не хранится вообще никаких статических секретов Vault.
```
```bash
vault auth enable jwt
vault write auth/jwt/config \
  oidc_discovery_url="https://gitlab.com" \
  bound_issuer="https://gitlab.com"

vault write auth/jwt/role/ci-billing \
  role_type="jwt" user_claim="project_path" \
  bound_claims='{"project_path":"org/billing","ref":"main","ref_type":"branch"}' \
  policies="ci-billing" ttl=15m
```
```yaml
# .gitlab-ci.yml
deploy:
  id_tokens:
    VAULT_ID_TOKEN: { aud: https://vault.example.com }
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=ci-billing jwt=$VAULT_ID_TOKEN)
    - export DB_PASSWORD=$(vault kv get -field=password secret/prod/billing/db)
```

---

## 7. TTL, лизы и отзыв

```text:no-line-numbers
 ТОКЕН        ttl → max_ttl,  renewable
 ЛИЗ (lease)  у динамических секретов: своя длительность и продление
                  │
                  ├─ vault lease renew <lease_id>
                  └─ vault lease revoke <lease_id>

 ОТЗЫВ КАСКАДОМ: отзыв родительского токена отзывает все дочерние
```
```bash
vault token lookup
vault token renew
vault token revoke <token>
vault token revoke -prefix auth/approle/      # все токены метода
vault lease list database/creds/billing-ro
vault lease revoke -prefix database/creds/    # ⭐ массовый отзыв при инциденте
```

| Параметр | Смысл |
|----------|-------|
| `token_ttl` | Начальный срок жизни токена |
| `token_max_ttl` | Предел, дальше которого продлевать нельзя |
| `secret_id_ttl` | Срок жизни SecretID у AppRole |
| `num_uses` | Сколько раз можно использовать |
| `token_bound_cidrs` | Откуда можно использовать |
| `period` | Токен, который можно продлевать бесконечно (для демонов) |

⭐ Правило: чем короче TTL, тем меньше окно компрометации — но тем важнее,
чтобы приложение умело продлевать или переполучать доступ.

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| Приложения ходят с root-токеном | Нет разграничения и аудита по ролям | AppRole/Kubernetes + политики |
| Долгоживущий SecretID в репозитории | Фактически вечный доступ | Короткий TTL, `num_uses`, wrapping |
| Политика шире, чем нужно | Утечка одного сервиса открывает всё | Минимальные права по путям |
| Политика на `secret/*` для всех | Нет изоляции окружений | Разделение по `prod/stage/dev` |
| Бессрочные токены | Утечка = постоянный доступ | TTL и max TTL |
| Людям выдают userpass вместо SSO | Доступ остаётся после увольнения | OIDC/LDAP с группами |
| Нет `token_bound_cidrs` для критичных ролей | Токен работает откуда угодно | Ограничение по сети |
| Не настроен отзыв при инциденте | Долгий разбор | Заранее известные команды массового отзыва |

---

## 💼 Как это в DevOps

- Люди заходят через корпоративный SSO, сервисы — через AppRole или Kubernetes-метод;
  статических токенов в конфигурациях не остаётся.
- Для CI современный стандарт — JWT/OIDC: пайплайн доказывает свою личность подписью
  провайдера, а не хранит SecretID.
- Политики пишут по принципу «один сервис — одна политика — свой путь»;
  их версионируют в git и применяют Terraform-провайдером `vault`.
- При инциденте важны две команды: массовый отзыв токенов метода и отзыв лизов
  динамических секретов — их держат в рунбуке.
- TTL и ротация — то, что отличает «мы храним секреты в Vault» от «у нас управляемый доступ».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Список методов | `vault auth list` |
| Включить метод | `vault auth enable approle` |
| Пользователь (просто) | `vault write auth/userpass/users/alice password=... policies=devops` |
| Вход человеком | `vault login -method=userpass username=alice` / `-method=oidc` |
| Роль приложения | `vault write auth/approle/role/NAME token_policies=... token_ttl=1h` |
| Получить RoleID | `vault read auth/approle/role/NAME/role-id` |
| Выдать SecretID | `vault write -f auth/approle/role/NAME/secret-id` |
| Обёрнутый SecretID | `vault write -wrap-ttl=60s -f .../secret-id` + `vault unwrap` |
| Логин приложения | `vault write auth/approle/login role_id=... secret_id=...` |
| Роль для подов | `vault write auth/kubernetes/role/NAME bound_service_account_names=...` |
| Роль для CI | `vault write auth/jwt/role/NAME bound_claims=...` |
| Написать политику | `vault policy write NAME file.hcl` |
| Посмотреть свой токен | `vault token lookup` |
| Продлить/отозвать | `vault token renew` / `vault token revoke` |
| Массовый отзыв | `vault token revoke -prefix auth/approle/` |
| Лизы динамических секретов | `vault lease list` / `vault lease revoke -prefix ...` |

---

## 🧠 Что запомнить

1. Auth method отвечает «кто ты», политика — «что можно»; всё ограничено TTL.
2. ⭐ Люди — через SSO (OIDC/LDAP), приложения — AppRole, поды — Kubernetes-метод,
   CI — JWT/OIDC.
3. AppRole: RoleID — «логин», SecretID — короткоживущий «пароль»; лучше выдавать
   его в обёртке (response wrapping).
4. Kubernetes-метод использует токен ServiceAccount как доказательство личности пода.
5. JWT/OIDC в CI позволяет вообще не хранить секреты Vault в пайплайне.
6. Политики пишут на API-пути с минимальными capabilities; `deny` приоритетнее.
7. Шаблоны в путях (<code v-pre>{{identity.entity.name}}</code>) дают персональные разделы без копипасты.
8. TTL, `max_ttl`, `num_uses` и `token_bound_cidrs` сокращают окно компрометации.
9. Отзыв работает каскадно: родительский токен уносит дочерние; для динамических
   секретов отзывают лизы.
10. Команды массового отзыва должны быть записаны в рунбуке до инцидента.

---

## Задачи

> Стенд: Vault (dev достаточно для большинства заданий) + kind для Kubernetes-метода.

---

### Блок A. Теория

**A1.** Как связаны auth method, токен и политика?

<details><summary>Ответ</summary>

Клиент проходит аутентификацию выбранным методом, получает токен с привязанными
политиками и TTL; дальше каждый запрос проверяется политиками на конкретных путях.

</details>

**A2.** Какой метод выбрать для: человека в компании, приложения на VM, пода в k8s,
пайплайна CI, ВМ в облаке?

<details><summary>Ответ</summary>

Человек — OIDC/LDAP (SSO); приложение на VM — AppRole; под — Kubernetes-метод;
CI — JWT/OIDC; облачная ВМ — aws/gcp/azure по метаданным инстанса.

</details>

**A3.** ⭐ Как устроен AppRole? Что такое RoleID и SecretID?

<details><summary>Ответ</summary>

RoleID — идентификатор роли («логин»), обычно не секретный; SecretID —
секретная часть («пароль»), короткоживущая; их пара обменивается на токен
с политиками роли.

</details>

**A4.** Почему SecretID делают короткоживущим и одноразовым?

<details><summary>Ответ</summary>

Чтобы перехваченный SecretID быстро стал бесполезным и не мог использоваться
повторно; это резко сокращает окно компрометации.

</details>

**A5.** Что такое response wrapping и какую проблему он решает?

<details><summary>Ответ</summary>

Выдача значения в одноразовой «обёртке» с TTL: получить его может только тот,
кто первым распакует. Если обёртка уже использована — это явный признак компрометации.

</details>

**A6.** Как работает Kubernetes-метод аутентификации?

<details><summary>Ответ</summary>

Под отправляет в Vault токен своего ServiceAccount; Vault проверяет его через
TokenReview API кластера и, если SA и namespace совпадают с ролью, выдаёт свой токен
с политиками.

</details>

**A7.** ⭐ Что даёт JWT/OIDC-аутентификация для CI?

<details><summary>Ответ</summary>

Пайплайн получает подписанный провайдером JWT с проверяемыми claims
(проект, ветка, окружение) — в CI не нужно хранить никаких статических секретов Vault.

</details>

**A8.** Как устроена политика? Какие capabilities бывают?

<details><summary>Ответ</summary>

Набор правил на API-пути с capabilities: `create`, `read`, `update`, `delete`,
`list`, `sudo`, `deny`.

</details>

**A9.** Что происходит при конфликте разрешения и `deny`?

<details><summary>Ответ</summary>

`deny` всегда побеждает: явный запрет сильнее любых разрешений.

</details>

**A10.** Зачем нужны шаблоны в путях политик?

<details><summary>Ответ</summary>

Чтобы одна политика описывала персональные пути для многих пользователей
или сущностей, без создания отдельной политики каждому.

</details>

**A11.** Чем `token_ttl` отличается от `token_max_ttl`?

<details><summary>Ответ</summary>

`token_ttl` — начальный срок жизни и шаг продления; `token_max_ttl` —
абсолютный предел, после которого продление невозможно и нужен новый логин.

</details>

**A12.** Что такое лиз (lease) и чем он отличается от токена?

<details><summary>Ответ</summary>

Лиз — учётная запись срока жизни динамического секрета (например, временного
пользователя БД): его можно продлевать и отзывать независимо от токена.

</details>

**A13.** Как работает каскадный отзыв?

<details><summary>Ответ</summary>

Отзыв родительского токена автоматически отзывает все выданные им дочерние
токены и связанные лизы.

</details>

**A14.** Что делает `token_bound_cidrs`?

<details><summary>Ответ</summary>

Ограничивает использование токена сетями-источниками: даже украденный токен
не сработает из другой сети.

</details>

**A15.** Какие команды нужны в рунбуке на случай компрометации доступа?

<details><summary>Ответ</summary>

`vault token revoke -prefix auth/<method>/`, `vault lease revoke -prefix <engine>/`,
отключение роли/метода, ротация секретов, проверка журнала аудита.

</details>

---

### Блок B. «Оцени конфигурацию»

```text:no-line-numbers
B1.  Приложение аутентифицируется root-токеном
```

<details><summary>Ответ</summary>

Нет разграничения и аудита по ролям; root не должен использоваться приложениями.

</details>

```text:no-line-numbers
B2.  Приложение использует AppRole с token_ttl=1h и secret_id_num_uses=1
```

<details><summary>Ответ</summary>

Хорошая конфигурация.

</details>

```text:no-line-numbers
B3.  SecretID лежит в git вместе с кодом приложения
```

<details><summary>Ответ</summary>

SecretID в git — фактически постоянный доступ.

</details>

```text:no-line-numbers
B4.  SecretID выдаётся через response wrapping во время деплоя
```

<details><summary>Ответ</summary>

Правильный подход.

</details>

```text:no-line-numbers
B5.  Политика: path "secret/*" { capabilities = ["read"] } для всех сервисов
```

<details><summary>Ответ</summary>

Слишком широкая политика: любой сервис читает всё.

</details>

```text:no-line-numbers
B6.  Политика: path "secret/data/prod/billing/*" { capabilities = ["read"] }
```

<details><summary>Ответ</summary>

Минимально необходимые права.

</details>

```text:no-line-numbers
B7.  Люди входят через userpass, пароли раздаёт админ
```

<details><summary>Ответ</summary>

Работает, но нет централизованного отзыва при увольнении.

</details>

```text:no-line-numbers
B8.  Люди входят через корпоративный OIDC, группы маппятся на политики
```

<details><summary>Ответ</summary>

Целевая схема для людей.

</details>

```text:no-line-numbers
B9.  Токены без TTL "чтобы не отваливались"
```

<details><summary>Ответ</summary>

Бессрочные токены — постоянное окно компрометации.

</details>

```text:no-line-numbers
B10. token_ttl=15m + автоматическое продление агентом
```

<details><summary>Ответ</summary>

Хорошая практика (короткий TTL + автопродление).

</details>

```text:no-line-numbers
B11. В CI лежит статический токен Vault со сроком в год
```

<details><summary>Ответ</summary>

Статический токен на год в CI — типовая ошибка.

</details>

```text:no-line-numbers
B12. CI аутентифицируется через JWT провайдера и получает токен на 15 минут
```

<details><summary>Ответ</summary>

Современный стандарт для CI.

</details>

```text:no-line-numbers
B13. Kubernetes-роль без ограничения namespace и ServiceAccount
```

<details><summary>Ответ</summary>

Роль без привязки даёт доступ любому поду кластера.

</details>

```text:no-line-numbers
B14. Kubernetes-роль с bound_service_account_names и bound_service_account_namespaces
```

<details><summary>Ответ</summary>

Правильная привязка.

</details>

---

### Блок C. Практика

#### C1. 🔑 Политики
1. Напиши политику `app-read` на чтение `secret/data/dev/app/*`.
2. Создай токен с ней, проверь чтение и запрет записи.
3. Добавь `list` на метаданные и проверь `vault kv list`.
4. Добавь `deny` на подпуть и убедись, что запрет сильнее.

#### C2. userpass
Создай пользователя с политикой, войди под ним, проверь доступ,
измени политику и посмотри, когда изменения вступают в силу.

#### C3. ⭐ AppRole
1. Включи метод, создай роль с короткими TTL.
2. Получи RoleID и SecretID, выполни логин, получи токен.
3. Прочитай секрет этим токеном.
4. Попробуй использовать SecretID второй раз (`num_uses=1`).

<details><summary>Ответ</summary>

При `secret_id_num_uses=1` повторный логин с тем же SecretID завершится ошибкой.

</details>

#### C4. Response wrapping
1. Выдай SecretID с `-wrap-ttl=60s`.
2. Распакуй `vault unwrap`.
3. Попробуй распаковать повторно — объясни результат и почему это полезно.

<details><summary>Ответ</summary>

Повторный `unwrap` невозможен — обёртка одноразовая; это и есть индикатор
перехвата.

</details>

#### C5. Kubernetes-метод
1. В kind установи Vault (или настрой внешний) и включи метод `kubernetes`.
2. Создай роль, привязанную к ServiceAccount и namespace.
3. Из пода получи токен Vault по SA-токену и прочитай секрет.

#### C6. JWT для CI (со звёздочкой)
Настрой роль `jwt` для своего GitLab/GitHub-проекта с `bound_claims`
по проекту и ветке. Проверь, что пайплайн из другой ветки доступ не получает.

<details><summary>Ответ</summary>

При несовпадении `bound_claims` (другая ветка/проект) Vault откажет в логине.

</details>

#### C7. TTL и продление
1. Создай токен с `ttl=2m` и `max_ttl=10m`.
2. Продли его несколько раз, поймай момент, когда продление невозможно.
3. Сделай periodic-токен и сравни поведение.

<details><summary>Ответ</summary>

После достижения `max_ttl` продление перестаёт работать, требуется новая
аутентификация; periodic-токен продлевается неограниченно.

</details>

#### C8. Отзыв
1. Создай несколько токенов от одной роли.
2. Отзови их одной командой по префиксу.
3. Проверь, что все перестали работать.

#### C9. Персональные пути
Настрой политику с шаблоном <code v-pre>{{identity.entity.name}}</code> и убедись,
что каждый пользователь видит только свой раздел.

<details><summary>Ответ</summary>

Каждый пользователь видит только `secret/data/users/<своё имя>/*`.

</details>

#### C10. Рунбук
Напиши рунбук «компрометация доступа»: какие команды выполнить,
что ротировать, как проверить журнал аудита, кого уведомить.

---

### Блок D. Инциденты

**D1.** SecretID утёк в логах CI. Что делать и как предотвратить?

<details><summary>Ответ</summary>

Отозвать SecretID и связанные токены, выпустить новый, включить маскирование
в CI, перейти на response wrapping или JWT-аутентификацию, проверить аудит.

</details>

**D2.** Приложение перестало получать секреты через час работы. Причина?

<details><summary>Ответ</summary>

Истёк TTL токена, и приложение не умеет продлевать/переполучать доступ;
решается агентом, библиотекой с renew или повторной аутентификацией.

</details>

**D3.** Под в Kubernetes получает `permission denied` при обращении к Vault. Что проверить?

<details><summary>Ответ</summary>

Роль в Vault (привязка SA и namespace), корректность конфигурации метода
(host, CA, reviewer JWT), политики, путь KV (`data`), сетевой доступ до Vault,
срок действия SA-токена.

</details>

**D4.** Политика изменена, но токен по-прежнему имеет старые права. Почему?

<details><summary>Ответ</summary>

Политики применяются при выдаче токена и проверяются при запросе, но
существующий токен сохраняет связанный набор политик; нужно перелогиниться
или отозвать токен.

</details>

**D5.** Уволился инженер, у которого был userpass-доступ. Что делаешь?

<details><summary>Ответ</summary>

Удалить пользователя в методе аутентификации (или отключить в SSO),
отозвать его токены, проверить аудит, при необходимости ротировать секреты,
к которым он имел доступ.

</details>

**D6.** Нужно срочно отозвать все доступы одного сервиса. Как?

<details><summary>Ответ</summary>

Отозвать токены по префиксу метода/роли и лизы динамических секретов,
при необходимости удалить роль и ротировать секреты.

</details>

**D7.** CI-пайплайн из форка получил доступ к прод-секретам. Что было настроено неверно?

<details><summary>Ответ</summary>

В роли JWT не заданы (или слишком широки) `bound_claims`: не ограничены
проект, ветка и тип ссылки; форк смог получить токен.

</details>

**D8.** Приложение «висит» на старте: Vault недоступен. Как проектировать такие случаи?

<details><summary>Ответ</summary>

Проектировать деградацию: кэшировать полученные секреты (Vault Agent),
повторные попытки с backoff, health-проверки, HA Vault; критично — не делать
старт приложения зависимым от единственного экземпляра Vault.

</details>

**D9.** Политика для KV v2 не работает, хотя пути выглядят правильно. Частая причина?

<details><summary>Ответ</summary>

Права выданы на `secret/app/*` вместо `secret/data/app/*` (и `secret/metadata/*`
для `list`).

</details>

**D10.** Токены приложений живут год. Как перевести на короткие TTL без простоя?

<details><summary>Ответ</summary>

Ввести агента/библиотеку с автоматическим продлением, выкатывать по окружениям
(dev → stage → prod), параллельно поддерживать старые токены до полного перехода,
затем отозвать их.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие auth methods есть в Vault?

<details><summary>Ответ</summary>

token, userpass, ldap, oidc, approle, kubernetes, jwt, aws/gcp/azure, cert.

</details>

**2.** Как аутентифицируются приложения?

<details><summary>Ответ</summary>

Через AppRole (вне k8s) или Kubernetes-метод (в кластере), с политиками
и короткими TTL.

</details>

**3.** Что такое AppRole?

<details><summary>Ответ</summary>

Пара RoleID (идентификатор) и SecretID (секрет), обмениваемая на токен.

</details>

**4.** Как поды получают доступ к Vault?

<details><summary>Ответ</summary>

По токену ServiceAccount, который Vault проверяет через API кластера.

</details>

**5.** Как настроить доступ для CI без статических секретов?

<details><summary>Ответ</summary>

Через JWT/OIDC-аутентификацию с проверкой claims пайплайна.

</details>

**6.** Как устроены политики?

<details><summary>Ответ</summary>

Правила на API-пути с capabilities; `deny` приоритетен; поддерживаются шаблоны.

</details>

**7.** Что такое TTL и max TTL?

<details><summary>Ответ</summary>

Срок жизни токена и абсолютный предел продления.

</details>

**8.** Что такое лиз и как его отозвать?

<details><summary>Ответ</summary>

Запись о сроке жизни динамического секрета; отзывается `vault lease revoke`.

</details>

**9.** Как выдать доступ человеку и как его отозвать?

<details><summary>Ответ</summary>

Через SSO с маппингом групп на политики; отзыв — отключение в каталоге
и отзыв токенов.

</details>

**10.** Что делать при компрометации доступа?

<details><summary>Ответ</summary>

Отозвать токены и лизы, ротировать секреты, проверить аудит, разобрать причину
и закрыть её процессом.

</details>

---

### 🎯 Чек-лист

- [ ] Написал политики и проверил `permission denied`
- [ ] Понимаю приоритет `deny`
- [ ] ⭐ Настроил AppRole с короткими TTL и одноразовым SecretID
- [ ] Пробовал response wrapping
- [ ] Настроил Kubernetes-метод и получил секрет из пода
- [ ] Знаю, как настроить JWT-аутентификацию для CI
- [ ] Понимаю TTL, max TTL и periodic-токены
- [ ] Умею отзывать токены и лизы массово
- [ ] Использую шаблоны в политиках для персональных путей
- [ ] Есть рунбук на компрометацию доступа
