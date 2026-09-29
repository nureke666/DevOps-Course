---
title: "05. IAM и доступ"
description: "Блок → Безопасность → тема 05. Опирается на"
---

# 05. IAM и доступ

> Блок → Безопасность → тема 05. Опирается на
> [../Left/04_Cloud/01_cloud_models.md](/cloud/01-cloud-models) (IAM как понятие) ·
> [../Left/04_Cloud/03_network_vpc.md](/cloud/03-network-vpc) (bastion vs VPN) ·
> [../Kubernetes/17_rbac.md](/kubernetes/17-rbac) (RBAC) ·
> [../Left/08_Vault/04_auth_methods.md](/vault/04-auth-methods) (OIDC/JWT для людей и CI) ·
> [../Network/08_ssh.md](/network/08-ssh). Принципы least privilege и zero trust — в
> [01_security_mindset.md](/security/01-security-mindset).
>
> **После темы ты умеешь:** читать и писать IAM-политики (на примере AWS) с least privilege и
> понимать, как облако принимает решение allow/deny; сопоставлять AWS с Yandex Cloud и GCP;
> давать доступ сервисам без статических ключей (роли ВМ, workload identity, OIDC из GitLab CI);
> выбирать между bastion, VPN (WireGuard) и identity-aware доступом (SSM, IAP, OS Login);
> настраивать SSO, access review и break-glass; выпускать SSH-сертификаты вместо раздачи ключей.

---

## 🗺️ Карта темы

```text
                КТО?  (authentication)                      ЧТО МОЖНО?  (authorization)
   ┌──────────────────────────────────────────┐     ┌───────────────────────────────────────┐
   │ люди     → SSO (IdP) + MFA               │     │ policy: Effect · Action · Resource ·  │
   │ сервисы  → роль ВМ / workload identity   │ ──► │         Condition                     │
   │ CI       → OIDC-токен → временные креды  │     │ deny by default, explicit Deny wins   │
   │ админ    → SSH-сертификат / IAP / SSM    │     │ least privilege, короткий срок        │
   └──────────────────────────────────────────┘     └───────────────────────────────────────┘
                              │                                        │
                              └───────────────┬────────────────────────┘
                                              ▼
                ЖИЗНЕННЫЙ ЦИКЛ ДОСТУПА: выдать → пересмотреть (access review) →
                отозвать (offboarding) · аварийно войти (break-glass) · всё — в аудит-лог
```text
---

## 1. Модель IAM: кто, что, над чем, при каких условиях

Любая система доступа отвечает на вопрос: **может ли principal выполнить action над resource
при таких conditions?**

| Понятие | Что это | Пример |
|---------|---------|--------|
| **Principal** | Кто действует | Пользователь, группа, роль, сервисный аккаунт, федеративная identity |
| **Authentication** | Доказать, кто ты | Пароль + MFA, ключ, OIDC-токен, сертификат |
| **Authorization** | Решить, что можно | Политики, роли, RBAC |
| **Policy** | Набор правил allow/deny | JSON-политика AWS, binding роли в GCP/YC |
| **Role** | Набор прав, который «надевают» | IAM role в AWS: её принимают люди, сервисы, CI |
| **Service account** | Identity для программы, не для человека | Приложение, CI, ВМ |

Три правила, общие для всех облаков и Kubernetes:
1. **Deny by default** — если ничего не разрешено явно, запрещено.
2. **Права — группам и ролям**, а не конкретным людям.
3. **Короткоживущие креды лучше вечных**: роль на час вместо access key на годы.

---

## 2. Политики AWS: анатомия и логика решения

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "UploadArtifacts",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::acme-artifacts/linkd/*"
    },
    {
      "Sid": "ListOnlyOwnPrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::acme-artifacts",
      "Condition": { "StringLike": { "s3:prefix": ["linkd/*"] } }
    }
  ]
}
```text
- **Effect** — `Allow` или `Deny`; **Action** — `сервис:операция`; **Resource** — ARN;
  **Condition** — дополнительные условия (IP, MFA, теги, префикс, TLS).
- Обрати внимание: `ListBucket` действует на бакет, `PutObject` — на объекты (`/*`). Путаница
  в ARN — частая причина «AccessDenied при правильной политике».

**Identity-based vs resource-based:**

| | Identity-based | Resource-based |
|---|----------------|----------------|
| Висит на | Пользователе, группе, роли | Ресурсе: бакете, KMS-ключе, **trust policy роли** |
| Отвечает | «Что может этот principal» | «Кто может трогать этот ресурс» |
| Пример | Политика CI-роли выше | Bucket policy «только по TLS»; trust policy «кто может принять роль» |

```json
{ "Sid": "DenyInsecureTransport", "Effect": "Deny", "Principal": "*",
  "Action": "s3:*", "Resource": ["arn:aws:s3:::acme-artifacts", "arn:aws:s3:::acme-artifacts/*"],
  "Condition": { "Bool": { "aws:SecureTransport": "false" } } }
```text
**Как AWS принимает решение** (упрощённо, в пределах аккаунта):
```text
 запрос ──► есть явный Deny в ЛЮБОЙ применимой политике? ── да ──► DENY
                 │ нет
                 ▼
            разрешают ли ограничители (SCP организации, permission boundary,
            session policy)? ── нет ──► DENY
                 │ да
                 ▼
            есть Allow в identity- или resource-based политике? ── нет ──► DENY (implicit)
                 │ да
                 ▼
               ALLOW
```text
> ⭐ Explicit Deny сильнее любого Allow. SCP и permission boundary не **дают** права —
> они только **ограничивают** максимум. Поэтому guardrail'ы («нельзя выключать CloudTrail»,
> «нельзя создавать ресурсы вне региона») пишут как Deny в SCP.

---

## 3. Least privilege на практике

«Минимальные права» почти никто не пишет с первого раза. Рабочий цикл:

```text
 1. Начать с узкой политики под задачу (или с managed-политики read-only)
 2. Запустить, собрать AccessDenied → добавить ровно недостающее действие
 3. Через 30–90 дней: что из выданного реально использовалось? → урезать
 4. Проверять политики до применения и регулярно после
```text
| Инструмент AWS | Что делает |
|----------------|-----------|
| `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://p.json` | Ошибки, предупреждения и «слишком широко» ещё до применения |
| IAM Access Analyzer: policy generation | Генерирует политику по реальным вызовам из CloudTrail |
| IAM Access Analyzer: unused access | Находит неиспользуемые роли, ключи, права |
| `aws iam simulate-principal-policy --policy-source-arn &lt;arn&gt; --action-names s3:PutObject --resource-arns &lt;arn&gt;` | «А можно ли?» без реального вызова |
| Last accessed (консоль/API) | Когда сервис или действие использовались последний раз |

Архитектурные приёмы: **отдельные аккаунты/каталоги** для prod и dev (граница blast radius
сильнее любой политики); доступ людей в prod — только чтение, изменения — через пайплайн;
права по тегам (ABAC) для больших инфраструктур.

---

## 4. AWS ↔ Yandex Cloud ↔ GCP

Концепции одинаковые, отличаются названия (подробнее про рынок облаков —
[../Left/04_Cloud/00_INDEX.md](/cloud/)):

| Понятие | AWS | Yandex Cloud | GCP |
|---------|-----|--------------|-----|
| Граница изоляции | Account (+ Organizations, SCP) | Облако / каталог (+ Cloud Organization) | Project (+ Organization, Org Policy) |
| Права | JSON-политики на principal/ресурсе | Роли, назначенные на ресурс (облако, каталог, сервис) | Роли, привязанные binding'ом к ресурсу |
| Базовые роли | managed-политики (`ReadOnlyAccess`…) | примитивные `viewer`, `editor`, `admin` + сервисные (`storage.viewer`…) | basic `Viewer/Editor/Owner` + predefined |
| Identity программы | IAM role (instance profile, IRSA / EKS Pod Identity) | Сервисный аккаунт (привязка к ВМ, авторизованные ключи) | Service account (+ Workload Identity для GKE) |
| Федерация CI без ключей | OIDC provider + `AssumeRoleWithWebIdentity` | Федерации сервисных аккаунтов (Workload Identity Federation) | Workload Identity Federation |
| SSO людей | IAM Identity Center | Федерации удостоверений в Cloud Organization (SAML) | Cloud Identity / внешний IdP |
| Вход на ВМ без открытого 22 | SSM Session Manager | OS Login (`yc compute ssh`) | IAP TCP forwarding, OS Login |
| Аудит API | CloudTrail | Audit Trails | Cloud Audit Logs |
| Секреты | Secrets Manager | Lockbox | Secret Manager |

> ⭐ Общий антипаттерн для всех трёх: примитивная роль `editor`/`Owner`/`AdministratorAccess`
> сервисному аккаунту «чтобы работало». В Yandex Cloud и GCP роли назначаются на **ресурс** —
> выдавай на конкретный каталог/бакет, а не на всё облако/организацию.

---

## 5. Сервисы без статических ключей

**Статический ключ** (access key, JSON-ключ сервисного аккаунта) живёт годами, копируется
в `.env`, CI, ноутбуки — и утекает. Цель — чтобы программа получала **временные** креды
от платформы, на которой работает.

| Где работает код | Как получает креды | Что не забыть |
|------------------|-------------------|---------------|
| ВМ в AWS | Instance profile → IMDS | ⭐ IMDSv2 обязателен, hop limit 1 (иначе SSRF и контейнеры на хосте получат креды роли) |
| ВМ в Yandex Cloud | Сервисный аккаунт, привязанный к ВМ → IAM-токен из metadata | Минимальные роли на нужный каталог |
| Под в EKS / GKE | IRSA или EKS Pod Identity / GKE Workload Identity: SA Kubernetes ↔ облачная роль | Роль на под, а не на всю ноду |
| CI/CD | OIDC-токен джобы → временные креды (раздел 6) | Условия по проекту и ветке |
| Вне облака (свой сервер) | Workload identity federation по OIDC или Vault с динамическими кредами | Если ключ всё же нужен — хранилище + ротация |

Где статические ключи ещё встречаются и как с ними жить: сторонний SaaS без федерации,
старые утилиты, S3-совместимые хранилища. Правила: ключ в секрет-менеджере, не в репо и не в
образе; один ключ — одна система; ротация по расписанию (два ключа: выпустить новый → переключить
→ отозвать старый); алерт на использование с неожиданных адресов; инвентарь
([../Project/08_secrets_security.md](/project/08-secrets-security)).

---

## 6. OIDC из GitLab CI вместо ключей

Классика: в CI-переменной лежит `AWS_SECRET_ACCESS_KEY` с правами деплоя. Утёк лог или
переменная — утёк прод, и ключ годен, пока его не отзовут. С OIDC секретов в CI **нет вообще**:

```text
  GitLab (issuer)                       AWS STS                           джоба
 ┌──────────────┐  1. JWT на джобу     ┌────────────────────────────┐
 │ подписывает  │ ───────────────────► │ 2. проверяет подпись (JWKS │
 │ ID-токен:    │   aud, sub=project_  │    issuer'а) и условия      │ 3. креды на 1 час
 │ project,ref, │   path:grp/app:ref_  │    trust policy роли        │ ─────────────────► deploy
 │ protected…   │   type:branch:ref:.. │                             │
 └──────────────┘                      └────────────────────────────┘
```text
**1. В AWS:** IAM → Identity providers → OpenID Connect, URL `https://gitlab.com` (или свой
GitLab), audience — как в `aud` джобы. **2. Роль с trust policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::111122223333:oidc-provider/gitlab.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "gitlab.com:sub": "project_path:acme/linkd:ref_type:branch:ref:main",
        "gitlab.com:aud": "https://gitlab.com"
      }
    }
  }]
}
```text
**3. Джоба:**
```yaml
deploy:prod:
  stage: deploy
  image: amazon/aws-cli:latest        # в проде — пин по digest (тема 04)
  environment: production
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.com
  script:
    - >
      aws_sts_output=$(aws sts assume-role-with-web-identity
      --role-arn "$ROLE_ARN"
      --role-session-name "GitLabRunner-${CI_PROJECT_ID}-${CI_PIPELINE_ID}"
      --web-identity-token "$GITLAB_OIDC_TOKEN"
      --duration-seconds 3600
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]'
      --output text)
    - export $(printf "AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s AWS_SESSION_TOKEN=%s" $aws_sts_output)
    - aws sts get-caller-identity
```text
`ROLE_ARN` — не секрет, его можно держать обычной переменной.

**Что ограничивать в trust policy:**
- ⭐ **Всегда `sub`** с конкретным проектом и веткой/тегом. Без условия по `sub` роль сможет
  принять **любой** проект на gitlab.com, потому что issuer у всех общий.
- Прод-роль — только для `ref:main` (protected branch) или protected environment. На gitlab.com
  доступны ещё условия по `namespace_id`, `project_id`, `ref_protected` — стабильнее, чем пути,
  которые меняются при переименовании группы. На self-managed в AWS проверяются `sub` и `aud`.
- Состав `sub` настраивается (`ci_id_token_sub_claim_components`), например с `project_id`.
- Отдельные роли: `ci-plan` (read-only) для MR, `ci-deploy-prod` — только из main.

Старые переменные `CI_JOB_JWT`/`CI_JOB_JWT_V2` удалены в GitLab 17.0 — только `id_tokens`.
Тот же механизм работает для Vault (`jwt` auth — [../Left/08_Vault/04_auth_methods.md](/vault/04-auth-methods)),
для Yandex Cloud (федерация сервисных аккаунтов: JWT обменивается на IAM-токен через
`https://auth.yandex.cloud/oauth/token`) и для GCP (Workload Identity Federation).

---

## 7. Доступ людей к серверам: bastion, VPN, identity-aware

| | Bastion (jump host) | VPN (WireGuard и др.) | Identity-aware (SSM, IAP, OS Login) |
|---|---------------------|-----------------------|-------------------------------------|
| Идея | Один публичный SSH-хост, дальше `ProxyJump` | Защищённый туннель в приватную сеть | Вход по identity облака, без открытых портов |
| Порт наружу | 22 на bastion | UDP-порт VPN | Нет входящих |
| Аутентификация | SSH-ключ/сертификат | Ключ VPN (+ SSO у коммерческих) | SSO + MFA облака, IAM-роль |
| Гранулярность | Сервер, если настроено | Обычно вся сеть | Конкретная ВМ/порт по политике |
| Аудит | auth.log bastion (легко потерять) | Логи VPN — кто подключился, не что делал | Сессии в CloudTrail/S3, записи команд |
| Минусы | Ещё один сервер: патчить, харденить | «VPN = вся сеть» — противоречит zero trust | Привязка к облаку, нужен агент (SSM) |

```bash
# AWS SSM: нет SSH-порта, нужна роль ВМ AmazonSSMManagedInstanceCore и агент
aws ssm start-session --target i-0abc1234def567890
aws ssm start-session --target i-0abc1234def567890 --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["5432"],"localPortNumber":["15432"]}'      # туннель к БД
# GCP IAP: firewall пропускает 22 только с диапазона IAP 35.235.240.0/20
gcloud compute ssh app-vm --tunnel-through-iap
# Yandex Cloud OS Login: доступ по ролям IAM, ключи не раскладываются руками
yc compute ssh --name app-vm
```text
### WireGuard за 10 минут (host ↔ sec01)

```bash
# на sec01 и на хосте
sudo apt install -y wireguard
umask 077; wg genkey | tee wg.key | wg pubkey > wg.pub     # ⚠️ приватный ключ не покидает машину
```text
```ini
# sec01: /etc/wireguard/wg0.conf                # хост: /etc/wireguard/wg0.conf
[Interface]                                     [Interface]
Address    = 10.8.0.1/24                        Address    = 10.8.0.2/32
ListenPort = 51820                              PrivateKey = &lt;ключ хоста&gt;
PrivateKey = &lt;ключ sec01&gt;
                                                [Peer]
[Peer]            # ноутбук админа              PublicKey  = &lt;pub sec01&gt;
PublicKey  = &lt;pub хоста&gt;                        Endpoint   = 192.168.56.30:51820
AllowedIPs = 10.8.0.2/32                        AllowedIPs = 10.8.0.0/24   # split tunnel: только сеть VPN
                                                PersistentKeepalive = 25
```text
```bash
sudo wg-quick up wg0 && sudo systemctl enable wg-quick@wg0
sudo wg show                                    # latest handshake, transfer
ssh vagrant@10.8.0.1                            # вход через туннель
# SSH только через VPN (⚠️ сначала проверь вход через 10.8.0.1, вторая сессия открыта):
sudo ufw allow 51820/udp && sudo ufw allow in on wg0 to any port 22 proto tcp
```text
- `AllowedIPs` у пира — одновременно «какие адреса маршрутизировать в туннель» и «с каких
  адресов принимать пакеты от этого пира».
- Чтобы через VPN ходить в сети **за** сервером, нужны `net.ipv4.ip_forward=1` и маршрут/NAT —
  это уже роль VPN-шлюза, а не отдельного сервера.
- Каждому человеку — свой ключ и адрес: увольнение = удалить `[Peer]`.

---

## 8. SSO, MFA и жизненный цикл учёток

**SSO**: люди логинятся в одном IdP (Keycloak, Okta, Microsoft Entra ID, Google Workspace),
а сервисы (облако, GitLab, Grafana, Vault, Kubernetes) доверяют ему по **SAML 2.0** или **OIDC**.
Права приходят группами из IdP.

| Практика | Зачем |
|----------|-------|
| Все админские входы — через SSO | Одна точка выключения при увольнении |
| **SCIM** provisioning | IdP сам создаёт и удаляет учётки в сервисах — offboarding без ручного списка |
| MFA везде, для админов — phishing-resistant (FIDO2/WebAuthn ключ) | TOTP и SMS перехватываются фишингом и SIM-swap |
| Короткие сессии для прод-доступа | Украденная сессия быстро протухает |
| Нет общих учёток (`admin` на всех) | Иначе аудит не скажет, кто это был |

Kubernetes: люди — через OIDC IdP, группы → RoleBinding ([../Kubernetes/17_rbac.md](/kubernetes/17-rbac),
раздел 8). Там же для CI показан долгоживущий токен из Secret типа `service-account-token` —
для внешних систем лучше короткоживущий `kubectl create token &lt;sa&gt; --duration=1h` или вообще
GitOps (у CI нет доступа к кластеру).

---

## 9. Access review, JIT и break-glass

**Access review** — регулярный (обычно ежеквартально) пересмотр «у кого какой доступ»:
```text
 1. Выгрузить: члены групп IdP, роли в облаке, GitLab members, kubeconfig/RoleBinding, VPN-пиры
 2. Владелец системы/руководитель подтверждает каждую строку: нужен / не нужен
 3. Не нужен → отозвать; никто не подтвердил → отозвать
 4. Сохранить результат — это доказательство для аудита (тема 07)
```text
```bash
aws iam generate-credential-report
aws iam get-credential-report --query Content --output text | base64 -d | cut -d, -f1,5,11 | column -ts,
#  user, password_last_used, access_key_1_last_used_date — кто не заходил 90+ дней
```text
**JIT (just-in-time)** — постоянных админских прав нет; повышение выдаётся по запросу на 1–4 часа
с одобрением и записью (инструменты вроде Teleport, временные роли облака, динамические креды Vault).

**Break-glass** — аварийный доступ, когда SSO/IdP лежит или всё сломано:

| Требование | Как |
|------------|-----|
| Отдельная учётка с высокими правами | Не используется в обычной работе |
| Надёжная защита | Аппаратный MFA-ключ, креды в сейфе/у двух людей (разделение) |
| ⭐ Алерт на любое использование | Вход этой учёткой → страница дежурному и безопасности |
| Проверяется регулярно | Раз в квартал учения: вход работает, алерт пришёл |
| После использования | Ротация кредов, разбор: почему понадобилось |
| Для k8s и Vault | Офлайн admin-kubeconfig в сейфе; процедура recovery Vault записана |

---

## 10. SSH-сертификаты (опционально, но очень полезно)

Вместо раскладывания `authorized_keys` по сотне серверов: свой **SSH CA** подписывает ключ
пользователя на 8 часов, серверы доверяют CA.
```bash
# один раз: CA (⚠️ user_ca — самый ценный ключ, храни офлайн или в Vault)
ssh-keygen -t ed25519 -f user_ca -C "lab user CA"
# на сервере (sec01)
sudo cp user_ca.pub /etc/ssh/user_ca.pub
echo 'TrustedUserCAKeys /etc/ssh/user_ca.pub'                  | sudo tee    /etc/ssh/sshd_config.d/10-ca.conf
echo 'AuthorizedPrincipalsFile /etc/ssh/auth_principals/%u'   | sudo tee -a /etc/ssh/sshd_config.d/10-ca.conf
sudo mkdir -p /etc/ssh/auth_principals && echo "ops" | sudo tee /etc/ssh/auth_principals/vagrant
sudo sshd -t && sudo systemctl reload ssh
# выдача сертификата на 8 часов с principal "ops"
ssh-keygen -s user_ca -I "nurik@laptop" -n ops -V +8h ~/.ssh/id_ed25519.pub   # → id_ed25519-cert.pub
ssh-keygen -L -f ~/.ssh/id_ed25519-cert.pub                                  # срок, principals
ssh vagrant@192.168.56.30                                                    # ssh подхватит -cert.pub сам
```text
- **Principals** — «роли» в сертификате; `AuthorizedPrincipalsFile` решает, какие principals
  пускать под каким пользователем.
- Отзыв — через срок (8 часов) и список отозванных `RevokedKeys` (KRL).
- Host-сертификаты (`ssh-keygen -h`) убирают «The authenticity of host … can't be established».
- В проде CA держат в Vault (SSH secrets engine) или используют Teleport/OS Login — выдача по SSO.

---

## 11. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Access keys у root-аккаунта | Полный доступ без ограничений, не урезать политикой | Root без ключей, с аппаратным MFA, только для break-glass |
| `"Action": "*", "Resource": "*"` сервису | Утечка = компрометация аккаунта | Конкретные действия и ARN, validate-policy |
| Ключ облака в CI-переменной навсегда | Утёк лог — утёк прод на годы | OIDC + временные креды |
| OIDC trust без условия по `sub` | Роль примет любой проект на gitlab.com | `sub` с проектом и веткой, отдельная роль для prod |
| IMDSv1 на ВМ с веб-приложением | SSRF → креды роли ВМ | IMDSv2 обязательный, hop limit 1 |
| Общая учётка `admin` | Аудит бесполезен, отзыв ломает всех | Персональные учётки через SSO |
| «VPN — и вся сеть открыта» | Взломанный ноутбук = доступ везде | Сегментация, доступ к конкретным системам |
| Offboarding по памяти | Бывший сотрудник с ключом через месяц | SSO + SCIM, SSH-сертификаты, review |
| Break-glass без алерта и учений | Не работает в аварию или используется тихо | Алерт на вход, учения раз в квартал |
| Долгоживущий SA-токен k8s во внешнем CI | Токен без срока, выдаётся без аудита | `kubectl create token --duration` или GitOps |
| Роль `editor` на всё облако YC/GCP | Blast radius — всё облако | Роль на конкретный каталог/ресурс |

---

## 💼 Как это в DevOps

- Девопс — главный «выдаватель доступов»: каждая новая роль, сервисный аккаунт и CI-переменная
  проходят вопрос «что будет, если утечёт» ([01](/security/01-security-mindset)).
- IAM живёт в коде: роли, политики и trust policy — в Terraform с ревью; ручные клики в консоли
  — дрейф, который никто не отревьюит.
- Переход «ключи в CI → OIDC» — одна из самых ценных и быстрых задач безопасности: за день
  убирает целый класс утечек.
- На собесе спрашивают: «как дать CI доступ в облако», «как дать доступ разработчику к базе в проде»,
  «что сделаешь при увольнении сотрудника» — отвечай через identity, короткий срок и аудит.
- Доступ к проду по умолчанию — чтение; изменения — пайплайном; экстренное — break-glass с алертом.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить политику до применения | `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://p.json` |
| «Можно ли?» без вызова | `aws iam simulate-principal-policy --policy-source-arn … --action-names … --resource-arns …` |
| Кто я сейчас | `aws sts get-caller-identity` |
| Запретить без TLS | bucket policy: `Deny` при `aws:SecureTransport = false` |
| CI → AWS без ключей | `id_tokens` + `assume-role-with-web-identity`, trust с `sub` |
| Неиспользуемые учётки | `aws iam generate-credential-report` → `get-credential-report` |
| Вход на ВМ без 22 | `aws ssm start-session` / `gcloud compute ssh --tunnel-through-iap` / `yc compute ssh` |
| Ключи WireGuard | `umask 077; wg genkey \| tee wg.key \| wg pubkey > wg.pub` |
| Поднять туннель | `sudo wg-quick up wg0 && sudo wg show` |
| SSH-сертификат на 8 часов | `ssh-keygen -s user_ca -I id -n ops -V +8h key.pub` |
| Посмотреть сертификат | `ssh-keygen -L -f key-cert.pub` |
| Короткий токен SA k8s | `kubectl create token &lt;sa&gt; --duration=1h` |

---

## 🧠 Что запомнить

1. Доступ = principal + action + resource + condition; deny by default, explicit Deny сильнее Allow.
2. SCP и permission boundary не дают права, а ограничивают максимум — туда пишут guardrail'ы.
3. Least privilege — цикл: узко → по AccessDenied добавить → по факту использования урезать.
4. AWS, Yandex Cloud и GCP устроены одинаково: роли, сервисные аккаунты, федерация, аудит; в YC/GCP роль — на конкретный ресурс.
5. Программы получают временные креды от платформы (роль ВМ, workload identity), а не статические ключи.
6. OIDC из CI убирает секреты из пайплайна; без условия по `sub` trust policy открыта всему gitlab.com.
7. Identity-aware доступ (SSM/IAP/OS Login) лучше bastion и «VPN во всю сеть»: нет открытых портов, есть аудит.
8. SSO + SCIM + MFA (для админов — FIDO2) делают offboarding одним действием.
9. Access review ежеквартально, JIT вместо постоянных админских прав, break-glass с алертом и учениями.
10. SSH-сертификаты с коротким сроком заменяют раскладку `authorized_keys` и решают отзыв.

➡️ Дальше: [06_k8s_security.md](/security/06-k8s-security) · задачи: 05_iam_access_tasks.md


---

### Блок A. Теория


**A1.** Чем authentication отличается от authorization? Из чего состоит любое решение о доступе?

<details><summary>Ответ</summary>

Authentication — доказать, кто ты (пароль+MFA, ключ, токен); authorization — решить, что
можно. Решение: может ли principal выполнить action над resource при conditions.

</details>

**A2.** ⭐ Опиши, как AWS принимает решение allow/deny. Что сильнее: Allow или explicit Deny?

<details><summary>Ответ</summary>

Явный Deny в любой применимой политике → deny; иначе ограничители (SCP, permission boundary,
session policy) должны разрешать; затем нужен Allow в identity- или resource-based политике; нет
Allow → implicit deny. Explicit Deny сильнее любого Allow.

</details>

**A3.** Чем identity-based политика отличается от resource-based? Приведи по примеру.

<details><summary>Ответ</summary>

Identity-based висит на principal («что может эта роль»): политика CI-роли на `PutObject`.
Resource-based висит на ресурсе («кто может трогать ресурс»): bucket policy «только TLS», trust
policy роли «кто может её принять».

</details>

**A4.** Что делают SCP и permission boundary? Почему они не могут «дать» права?

<details><summary>Ответ</summary>

Задают верхнюю границу возможных прав (SCP — для аккаунтов организации, boundary — для
роли/пользователя). Итоговые права — пересечение Allow и ограничителей, поэтому ограничитель без
Allow ничего не даёт. Туда пишут guardrail'ы в виде Deny.

</details>

**A5.** Опиши рабочий цикл least privilege. Какие инструменты AWS в нём помогают?

<details><summary>Ответ</summary>

Узкая политика → по AccessDenied добавлять ровно нужное → через 30–90 дней урезать по факту
использования → проверять до применения и регулярно. Инструменты: Access Analyzer (validate-policy,
генерация политики по CloudTrail, unused access), `simulate-principal-policy`, last accessed.

</details>

**A6.** Сопоставь AWS, Yandex Cloud и GCP: граница изоляции, identity программы, федерация CI,
вход на ВМ без 22, аудит API.

<details><summary>Ответ</summary>

Изоляция: account / облако-каталог / project. Identity программы: IAM role / сервисный
аккаунт / service account. Федерация CI: OIDC provider + AssumeRoleWithWebIdentity / федерации
сервисных аккаунтов / Workload Identity Federation. Вход без 22: SSM / OS Login / IAP.
Аудит: CloudTrail / Audit Trails / Cloud Audit Logs.

</details>

**A7.** ⭐ Почему статические ключи опасны? Как программа на ВМ, в поде и в CI получает креды без них?

<details><summary>Ответ</summary>

Живут годами, копируются в `.env`, CI, ноутбуки, утекают, отзываются вручную. ВМ — роль
через metadata (instance profile / SA на ВМ); под — IRSA/EKS Pod Identity/GKE Workload Identity;
CI — OIDC-токен джобы → временные креды.

</details>

**A8.** Зачем IMDSv2 и hop limit 1?

<details><summary>Ответ</summary>

IMDSv2 требует сессионный токен, полученный PUT-запросом: простой GET через SSRF
его не получит. Hop limit 1 не даёт ответу metadata пройти дальше хоста (например, в контейнер
на ВМ).

</details>

**A9.** ⭐ Опиши поток OIDC из GitLab CI в AWS. Где здесь секрет?

<details><summary>Ответ</summary>

GitLab подписывает ID-токен джобы (JWT с `aud`, `sub` = проект и ветка); джоба отправляет
его в STS `AssumeRoleWithWebIdentity`; AWS проверяет подпись по JWKS issuer'а и условия trust
policy; выдаёт креды на час. Долгоживущего секрета нет — токен живёт минуты, креды — час.

</details>

**A10.** ⭐ Что будет, если в trust policy OIDC-роли нет условия по `sub`? Какие ещё условия
полезны на gitlab.com?

<details><summary>Ответ</summary>

Роль сможет принять любой проект на gitlab.com (issuer общий) — в том числе проект
атакующего. На gitlab.com полезны условия по `namespace_id`, `project_id`, `ref_protected`,
плюс `sub` с конкретной веткой и отдельная роль для prod.

</details>

**A11.** Сравни bastion, VPN и identity-aware доступ (SSM/IAP/OS Login).

<details><summary>Ответ</summary>

Bastion — один публичный SSH-хост, дальше ProxyJump; его надо патчить, аудит в его
auth.log. VPN — туннель в сеть, обычно открывает всю сеть. Identity-aware — вход по IAM/SSO без
входящих портов, гранулярно по ВМ, сессии в аудите; минус — привязка к облаку и агент.

</details>

**A12.** Что означает `AllowedIPs` в WireGuard? Что такое split tunnel?

<details><summary>Ответ</summary>

Адреса, которые маршрутизируются в туннель к пиру, и адреса-источники, которые
принимаются от этого пира. Split tunnel — в туннель идёт только нужная сеть (например,
`10.8.0.0/24`), остальной трафик — напрямую.

</details>

**A13.** Что дают SSO, SCIM и phishing-resistant MFA?

<details><summary>Ответ</summary>

SSO — один вход в IdP, сервисы доверяют по SAML/OIDC, права группами. SCIM — IdP сам
создаёт и удаляет учётки в сервисах (offboarding без ручного списка). FIDO2/WebAuthn — ключ,
который фишинговый сайт не сможет использовать (привязка к домену), в отличие от TOTP и SMS.

</details>

**A14.** Что такое access review и JIT-доступ?

<details><summary>Ответ</summary>

Access review — регулярный пересмотр доступов владельцами: подтвердить или отозвать,
сохранить результат. JIT — постоянных админских прав нет, повышение выдаётся по запросу на время
с одобрением и записью.

</details>

**A15.** ⭐ Какие требования к break-glass учётке?

<details><summary>Ответ</summary>

Отдельная учётка, не для ежедневной работы; аппаратный MFA; креды в сейфе или разделены
между людьми; алерт на любое использование; регулярные учения; ротация и разбор после использования;
для k8s/Vault — офлайн kubeconfig и процедура recovery.

</details>

**A16.** Чем SSH-сертификаты лучше `authorized_keys`? Что такое principal?

<details><summary>Ответ</summary>

Сертификат с коротким сроком не нужно отзывать и раскладывать по серверам — серверы
доверяют CA; отзыв через срок и KRL; видно, кто и когда получил доступ. Principal — «роль» в
сертификате, а `AuthorizedPrincipalsFile` решает, какие principals пускать под каким пользователем.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  { "Effect": "Allow", "Action": "s3:*",
```text
<details><summary>Ответ</summary>

⚠️ ARN без `/*` — это бакет, а `PutObject` действует на объекты. Нужен
`arn:aws:s3:::acme-artifacts/linkd/*` для объектов и бакет — только для `ListBucket`. И `s3:*`
слишком широко.

</details>

```text:no-line-numbers
       "Resource": "arn:aws:s3:::acme-artifacts" }
```text
```text:no-line-numbers
     // CI: PutObject → AccessDenied, «хотя s3:* же!»
```text
```text:no-line-numbers
B2.  // trust policy роли деплоя
```text
<details><summary>Ответ</summary>

⚠️ Нет условия по `sub` — роль примет любой проект на gitlab.com. Добавить
`gitlab.com:sub` с проектом и веткой (и `project_id`/`ref_protected`).

</details>

```text:no-line-numbers
     { "Effect": "Allow",
```text
```text:no-line-numbers
       "Principal": { "Federated": "arn:aws:iam::111122223333:oidc-provider/gitlab.com" },
```text
```text:no-line-numbers
       "Action": "sts:AssumeRoleWithWebIdentity",
```text
```text:no-line-numbers
       "Condition": { "StringEquals": { "gitlab.com:aud": "https://gitlab.com" } } }
```text
```text:no-line-numbers
B3.  // identity-политика даёт s3:DeleteObject, а SCP организации:
```text
<details><summary>Ответ</summary>

⚠️ Explicit Deny в SCP сильнее Allow в identity-политике — удаление запрещено
организацией. Это guardrail, решать с владельцами SCP.

</details>

```text:no-line-numbers
     { "Effect": "Deny", "Action": "s3:DeleteObject", "Resource": "*" }
```text
```text:no-line-numbers
     // «почему не удаляется, у меня же Allow?»
```text
```text:no-line-numbers
B4.  "gitlab.com:sub": "project_path:acme/linkd:ref_type:branch:ref:*"      // прод-роль, StringLike
```text
<details><summary>Ответ</summary>

⚠️ `ref:*` — любая ветка, включая feature-ветку разработчика или злоумышленника с правом
push. Для прод-роли — только `ref:main` (protected) и protected environment.

</details>

```text:no-line-numbers
B5.  # .gitlab-ci.yml
```text
<details><summary>Ответ</summary>

⚠️ Статические ключи в CI — в файле в git они ещё и в истории навсегда. Masked не защищает
от вывода по частям/base64. Ротировать ключ, перейти на OIDC.

</details>

```text:no-line-numbers
     variables:
```text
```text:no-line-numbers
       AWS_ACCESS_KEY_ID: AKIA...               # «masked же»
```text
```text:no-line-numbers
       AWS_SECRET_ACCESS_KEY: wJalr...
```text
```text:no-line-numbers
B6.  # WireGuard: клиент
```text
<details><summary>Ответ</summary>

⚠️ Full tunnel: весь трафик ноутбука пойдёт через сервер (и без форвардинга/NAT
интернет пропадёт). Для доступа к серверам — `AllowedIPs = 10.8.0.0/24` (и нужные подсети).

</details>

```text:no-line-numbers
     [Peer]
```text
```text:no-line-numbers
     AllowedIPs = 0.0.0.0/0                     # «хотел только доступ к серверам»
```text
```text:no-line-numbers
B7.  # sec01
```text
<details><summary>Ответ</summary>

⚠️ Сертификат на 10 лет — теряется главное преимущество (короткий срок). Выдавать на часы
(`-V +8h`), автоматически через SSO/Vault.

</details>

```text:no-line-numbers
     ssh-keygen -s user_ca -I nurik -n ops -V +520w ~/.ssh/id_ed25519.pub
```text
```text:no-line-numbers
B8.  # Yandex Cloud: сервисному аккаунту бэкапа
```text
<details><summary>Ответ</summary>

⚠️ `editor` на всё облако — сервис бэкапа может менять и удалять любые ресурсы.
Сервисная роль на конкретный бакет/каталог (например, `storage.uploader` на бакет бэкапов).

</details>

```text:no-line-numbers
     yc resource-manager cloud add-access-binding &lt;cloud&gt; --role editor --service-account-name backup
```text
```text:no-line-numbers
B9.  # AWS: на ВМ с веб-приложением
```text
<details><summary>Ответ</summary>

⚠️ IMDSv1 отдаёт креды роли на обычный GET — SSRF в приложении = креды роли. `HttpTokens=required`,
hop limit 1.

</details>

```text:no-line-numbers
     HttpTokens = optional   # IMDSv1 разрешён
```text
```text:no-line-numbers
B10.  # break-glass
```text
<details><summary>Ответ</summary>

⚠️ Всё не так: пароль скомпрометирован по определению, нет MFA, нет алерта, не проверено.
Сейф/разделение кредов, аппаратный MFA, алерт на вход, учения, ротация после использования.

</details>

```text:no-line-numbers
     Учётка emergency-admin, пароль в общем чате админов «на всякий случай», MFA нет,
```text
```text:no-line-numbers
     ни разу не проверялась, алертов нет.
```text
```text:no-line-numbers
B11.  # все админы ходят на серверы под учёткой ubuntu с одним общим ключом
```text
<details><summary>Ответ</summary>

⚠️ Общий ключ: аудит не скажет, кто это был, отзыв одного человека = замена ключа у всех,
увольнение не отзывает доступ. Персональные учётки, SSH-сертификаты или OS Login/SSM.

</details>

```text:no-line-numbers
B12.  kubectl -n prod get secret gitlab-deployer-token -o jsonpath='{.data.token}' | base64 -d
```text
<details><summary>Ответ</summary>

⚠️ Долгоживущий токен SA без срока в CI уже два года, его никто не ротирует. Для
внешней системы — `kubectl create token --duration`, OIDC-интеграция или GitOps, где у CI нет
доступа к кластеру.

</details>

```text:no-line-numbers
     # токен положили в CI-переменную 2 года назад
```text
---

### Блок C. Практика


### C1. 🔑 Least-privilege политика для CI
Напиши identity-политику для роли CI, которая загружает артефакты в `s3://acme-artifacts/linkd/`
и может видеть список только этого префикса. Добавь bucket policy «только по TLS». Проверь
`validate-policy` (или объясни письменно, почему каждое действие и ARN именно такие).

### C2. 🔑 Найди дыры в trust policy
Возьми trust policy из B2, B4 и ещё одну свою с `StringLike` на `project_path:acme/*`. Для каждой:
кто сможет принять роль? Перепиши безопасно: отдельные роли `ci-plan` (любая ветка проекта,
read-only) и `ci-deploy-prod` (только `main`, на gitlab.com — плюс `project_id` и `ref_protected`).

### C3. OIDC-джоба
Напиши job `deploy:prod` с `id_tokens`, `assume-role-with-web-identity` и проверкой
`aws sts get-caller-identity`. Объясни, почему `ROLE_ARN` можно не прятать, а что будет, если
кто-то запустит эту джобу из feature-ветки.

### C4. Карта соответствий AWS ↔ Yandex Cloud ↔ GCP
Для своего проекта (или linkd) распиши: какие identity нужны (CI, приложение, бэкап, люди),
какие роли и на какой ресурс в Yandex Cloud, как CI получает креды без ключей, где аудит.

### C5. 🔑 WireGuard host ↔ sec01
Подними туннель по разделу 7: `10.8.0.1` на `sec01`, `10.8.0.2` на хосте, split tunnel.
Проверь `wg show` (есть handshake), войди `ssh vagrant@10.8.0.1`. Затем разреши SSH только через
`wg0` в ufw и убедись, что вход по `192.168.56.30` не работает, а по `10.8.0.1` — работает.

### C6. 🔑 SSH CA с сертификатами на 8 часов
Создай `user_ca`, настрой `TrustedUserCAKeys` и `AuthorizedPrincipalsFile` на `sec01`, выпусти
сертификат на 8 часов с principal `ops`, войди. Выпусти сертификат на 1 минуту и убедись, что
после истечения вход отклоняется. Убери свой ключ из `authorized_keys` и проверь, что вход по
сертификату остаётся.

### C7. Access review
Составь чек-лист ежеквартального access review для своего стенда/проекта: список систем (облако,
GitLab, kind/k8s, VPN, серверы, Vault), откуда брать список доступов, кто подтверждает, что делать
с неподтверждёнными, куда сохранять результат.

### C8. Break-glass runbook
Напиши runbook на страницу: где лежат креды и кто может их достать, как войти, какой алерт
придёт и кому, что сделать после (ротация, разбор), как и когда проводятся учения.

### C9. Offboarding за 15 минут
Опиши, что нужно отозвать при увольнении девопса в компании со SSO, SCIM, OIDC в CI, SSH-сертификатами
и WireGuard. Чего не хватило бы без SSO?

---

### Блок D. Инциденты


**D1.** В публичном репозитории нашли access key пользователя `ci-deploy` с правами
`AdministratorAccess`. Твои действия в первые 30 минут.

<details><summary>Ответ</summary>

Сразу деактивировать и удалить ключ (`aws iam update-access-key --status Inactive`, затем
`delete-access-key`), не удаляя пользователя до разбора. Смотреть CloudTrail по этому ключу:
что делал, создавал ли новых пользователей/ключи/роли, запускал ли ресурсы (майнеры). Отозвать
созданное атакующим, проверить регионы. Дальше — OIDC вместо ключа и урезание прав; порядок
действий — тема 07 и [../CICD/13_quality_security.md](/cicd/13-quality-security).

</details>

**D2.** В CloudTrail — `AssumeRoleWithWebIdentity` на прод-роль из проекта `someone/random-fork`.

<details><summary>Ответ</summary>

Trust policy без условия по `sub` (или со слишком широким `StringLike`). Немедленно
исправить trust policy, отозвать сессии роли (в IAM: «Revoke active sessions» добавляет Deny
для токенов, выданных до момента отзыва), разобрать в CloudTrail, что делали выданные креды.

</details>

**D3.** После SSRF в приложении атакующий получил креды роли ВМ и вызывает `s3:ListBuckets`
с внешнего IP.

<details><summary>Ответ</summary>

Отозвать активные сессии роли, закрыть SSRF компенсирующими мерами (IMDSv2 required,
hop limit 1, egress), проверить в CloudTrail все действия с этими кредами, ротировать доступные
им секреты, настроить алерт «креды роли ВМ используются не с её IP» (например, GuardDuty
в AWS умеет такое находить).

</details>

**D4.** IdP (Keycloak) лежит, все админские входы через SSO не работают, а в проде инцидент.

<details><summary>Ответ</summary>

Break-glass: аварийная учётка с аппаратным MFA из сейфа, вход фиксируется в таймлайне
инцидента, алерт ожидаем. После — ротация, разбор, отдельный action item по надёжности IdP.

</details>

**D5.** Уволившийся сотрудник через неделю зашёл в VPN — его пир забыли удалить.

<details><summary>Ответ</summary>

Удалить пир, проверить логи: что делал через VPN (серверы, базы), отозвать другие доступы.
Причина — ручной offboarding; исправление — VPN с SSO (или автоматическая синхронизация пиров
с IdP), access review.

</details>

**D6.** Разработчик просит «доступ к прод-базе на час, срочно посмотреть данные».

<details><summary>Ответ</summary>

Не выдавать постоянный доступ и не давать прод-пароль. Варианты: реплика/обезличенная копия;
JIT-доступ на час с одобрением и read-only ролью; динамические креды Vault с TTL; доступ через
IAP/SSM port forwarding с записью сессии. Всё — с тикетом.

</details>

**D7.** Аудит показал 37 IAM-пользователей с access keys, которые не использовались больше года,
и 4 — с `AdministratorAccess`.

<details><summary>Ответ</summary>

Неиспользуемые ключи — деактивировать (с предупреждением владельцев), через 2 недели удалить;
`AdministratorAccess` — заменить ролями по задачам, админам — SSO + роль через Identity Center.
Процесс — ежеквартальный review и алерт на ключи старше N дней.

</details>

**D8.** Ночью сработал алерт «вход учёткой break-glass», дежурный ничего не знает.

<details><summary>Ответ</summary>

Считать возможной компрометацией, пока не доказано обратное: выяснить, кто и зачем
(возможно, коллега в инциденте), проверить действия учётки в аудите; если не свои — сменить
креды, отозвать сессии, запустить security-инцидент (тема 07).

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как дать GitLab CI доступ в облако безопасно?

<details><summary>Ответ</summary>

OIDC: GitLab выдаёт джобе ID-токен, облако по trust policy с условием `sub` (проект + ветка)
   выдаёт временные креды на час; отдельные роли для plan и prod, никаких ключей в переменных.

</details>

**2.** Что такое IAM role и чем она лучше пользователя с ключом?

<details><summary>Ответ</summary>

Роль — набор прав, который временно принимают (человек, сервис, CI) и получают креды на время;
   нет долгоживущего секрета, который утечёт, проще аудит и отзыв.

</details>

**3.** Как AWS принимает решение по политикам?

<details><summary>Ответ</summary>

Explicit Deny → ограничители (SCP, boundary) → нужен Allow в identity/resource политике →
   иначе implicit deny.

</details>

**4.** Что такое least privilege и как его добиваться на практике?

<details><summary>Ответ</summary>

Минимально необходимые права на нужный срок; начинаю узко, добавляю по AccessDenied, урезаю по
   данным Access Analyzer, проверяю политики до применения, разделяю аккаунты prod/dev.

</details>

**5.** Bastion, VPN или SSM/IAP — что выберешь и почему?

<details><summary>Ответ</summary>

По возможности identity-aware (SSM/IAP/OS Login): нет открытых портов, SSO+MFA, аудит сессий;
   VPN — для доступа к сети с сегментацией; bastion — если другого нет, с харденингом и логами.

</details>

**6.** Что делаешь при увольнении сотрудника?

<details><summary>Ответ</summary>

Отключаю в IdP (SCIM снимает учётки), завершаю сессии, удаляю VPN-пиры, SSH-сертификаты истекают
   сами, проверяю личные токены и ключи вне SSO, access review по его доступам.

</details>

**7.** Что такое SSO, SAML и OIDC?

<details><summary>Ответ</summary>

SSO — единый вход через IdP; SAML 2.0 — XML-протокол федерации (часто для консолей и SaaS);
   OIDC — надстройка над OAuth 2.0 с JWT (Kubernetes, Vault, CI).

</details>

**8.** Что такое break-glass доступ?

<details><summary>Ответ</summary>

Аварийный доступ на случай, когда обычный (SSO) недоступен: отдельная учётка с аппаратным MFA,
   креды в сейфе, алерт на использование, учения и ротация после.

</details>

**9.** Как управлять SSH-доступом к сотне серверов?

<details><summary>Ответ</summary>

SSH-сертификаты от CA с коротким сроком и principals (или OS Login/SSM), без раскладки ключей;
   конфиг sshd — Ansible-ролью; вход — только через VPN/IAP.

</details>

**10.** Как приложению в Kubernetes получить доступ к облачному хранилищу без ключей?

<details><summary>Ответ</summary>

Workload identity: ServiceAccount пода связывается с облачной ролью (IRSA/EKS Pod Identity,
    GKE Workload Identity, в YC — федерация сервисных аккаунтов с k8s), под получает временные креды.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю логику allow/deny AWS и почему explicit Deny сильнее
- [ ] Пишу least-privilege политику и проверяю её до применения
- [ ] Сопоставляю IAM AWS, Yandex Cloud и GCP
- [ ] Знаю, как ВМ, под и CI получают креды без статических ключей
- [ ] ⭐ Пишу OIDC trust policy с условием по `sub` и джобу `id_tokens`
- [ ] Поднял WireGuard и закрыл SSH на всё, кроме туннеля
- [ ] Выпускаю SSH-сертификаты на 8 часов со своим CA
- [ ] Есть чек-лист access review и runbook break-glass
- [ ] Могу провести offboarding по списку за 15 минут
