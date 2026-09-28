---
title: "08. AWS глубже"
description: "Organizations и Identity Center, эталонная VPC, ASG за ALB, RDS Multi-AZ и PITR, EKS и Pod Identity, CloudWatch, деньги AWS — конспект и задачи"
---

# 08. AWS глубже: то, что трогает девопс

> Блок → Облака → тема 08. Понятия (модели, ВМ, VPC, S3, managed) — в
> [01](/cloud/01-cloud-models)–[05](/cloud/05-managed-services), здесь они же на конкретном провайдере.
> IAM с точки зрения безопасности (логика allow/deny, OIDC из CI, SSM) здесь не повторяем,
> строим поверх. Инфраструктура кодом — [Terraform](/terraform/),
> k8s в облаке — [«16. Развёртывание кластера»](/kubernetes/16-cluster-deployment).
>
> **После темы ты умеешь:** разложить аккаунты по Organizations и пустить людей через
> Identity Center; собрать эталонную VPC на 2 AZ; поднять ASG за ALB; завести RDS PostgreSQL
> Multi-AZ с PITR; дать поду EKS доступ к S3 через Pod Identity; повесить алармы CloudWatch;
> найти в счёте NAT, межзонный трафик, публичные IPv4 и «сирот».
>
> ⚠️ Цены, версии и условия free tier — **проверь, сентябрь 2026**. Цены — us-east-1,
> в других регионах обычно дороже.

---

## 🗺️ Карта темы

```text:no-line-numbers
 AWS Organizations ── SCP / RCP (потолок прав) ── Identity Center (люди) ── Budgets
   └── аккаунт prod, регион eu-central-1
       └── VPC 10.20.0.0/16
           ├── AZ a ─ public 10.20.0.0/24 (ALB, NAT) ─ private 10.20.16.0/20 (ASG/EKS) ─ db 10.20.100.0/24 (RDS primary)
           ├── AZ b ─ public 10.20.1.0/24 (ALB, NAT) ─ private 10.20.32.0/20 (ASG/EKS) ─ db 10.20.101.0/24 (RDS standby)
           └── gateway endpoint S3 (бесплатный): трафик в S3 мимо NAT

 Route 53 ─► ALB (HTTPS, ACM) ─► target group ─► ASG / поды EKS ─► RDS
                                                  └─ Pod Identity ─► S3
 CloudWatch: метрики + логи ─► алармы ─► SNS ─► почта / Slack
```

---

## 1. Аккаунты, Organizations и доступ людей

Аккаунт AWS — **самая сильная граница изоляции**, сильнее любой политики. Поэтому prod
и dev живут в разных аккаунтах, объединённых в **AWS Organizations**:
```text:no-line-numbers
 management (только биллинг и Organizations, без нагрузок)
 ├── OU Security  : log-archive (CloudTrail всей организации), security-tooling
 ├── OU Workloads : prod, stage, dev
 └── OU Sandbox   : песочницы (жёсткие SCP и бюджеты)
```

| Механизм | Что делает | Важно |
|----------|-----------|-------|
| **SCP** | Потолок прав principal'ов в аккаунтах OU | Права **не даёт**; на management-аккаунт не действует |
| **RCP** (resource control policy) | Потолок для **ресурсов** (S3, KMS, STS…) | «Бакеты недоступны principal'ам вне организации» |
| **Permission boundary** | Потолок для конкретной роли/пользователя | Разработчик создаёт роли, но не выше границы |
| **Identity Center** | SSO людей во все аккаунты | Permission set → роль `AWSReservedSSO_*` в аккаунте |

Запрос пройдёт, только если его разрешают identity-политика, SCP, RCP и boundary; explicit
Deny в любой из них побеждает (схема — Security/05, §2).

| | IAM user | IAM role | Identity Center |
|---|----------|----------|-----------------|
| Креды | Постоянные: пароль, access keys | Временные (STS) | Временные через SSO-портал |
| Для кого | Исключения: софт без федерации | Сервисы, CI (OIDC), кросс-аккаунт | ⭐ Люди во всех аккаунтах |
| Риск | Утёкший ключ живёт годами | Широкая trust policy | Широкий permission set |

```bash
aws configure sso                        # один раз: start URL, регион, аккаунт, permission set
aws sso login --profile prod-readonly    # браузер → SSO + MFA → временные креды
```

**SCP-guardrail:** только наш регион, аудит не выключить.
```json
{ "Version": "2012-10-17", "Statement": [
  { "Sid": "DenyOtherRegions", "Effect": "Deny", "Resource": "*",
    "NotAction": ["iam:*", "organizations:*", "sts:*", "route53:*", "cloudfront:*", "support:*", "budgets:*", "ce:*"],
    "Condition": { "StringNotEquals": { "aws:RequestedRegion": ["eu-central-1"] } } },
  { "Sid": "ProtectCloudTrail", "Effect": "Deny", "Resource": "*",
    "Action": ["cloudtrail:StopLogging", "cloudtrail:DeleteTrail"] } ] }
```
`NotAction` нужен, потому что глобальные сервисы (IAM, Route 53, CloudFront) работают через
us-east-1 — без исключения запрет региона их сломает.

**Permission boundary:** разработчику разрешён `iam:CreateRole` только с условием
`iam:PermissionsBoundary = …/DevBoundary` — иначе он выдаст себе админа:
```bash
aws iam create-role --role-name reports-lambda --assume-role-policy-document file://trust.json \
  --permissions-boundary arn:aws:iam::111122223333:policy/DevBoundary
```

---

## 2. VPC: эталонная сеть на 2 AZ

Понятия — в [«03. Сети и VPC в облаке»](/cloud/03-network-vpc). AWS-специфика:

| Деталь | Что знать |
|--------|-----------|
| Публичная подсеть | = маршрут `0.0.0.0/0 → IGW` в её route table, а не «галочка»; AWS резервирует 5 адресов в каждой подсети |
| EKS и адреса | VPC CNI выдаёт подам **адреса VPC** → private-подсети крупные (`/20`, не `/24`) |
| NAT GW | Зональный; прод — по одному на AZ. С ноября 2025 есть **Regional NAT GW**: сам расширяется по AZ, но тарифицируется за каждую активную AZ |
| Gateway endpoint | S3 и DynamoDB, **бесплатный**, трафик идёт мимо NAT |
| Interface endpoint | ECR, STS, SSM, Logs…: ENI в подсети, платный за час **в каждой AZ** + за ГБ |
| Теги для k8s | `kubernetes.io/role/elb=1` на public, `kubernetes.io/role/internal-elb=1` на private — по ним выбираются подсети для LB |

```hcl
terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 6.0" } }   # сентябрь 2026: 6.66
}
provider "aws" {
  region = "eu-central-1"
  default_tags { tags = { project = "linkd", env = "lab", owner = "nurik", managed-by = "terraform" } }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.7"

  name             = "lab"
  cidr             = "10.20.0.0/16"
  azs              = ["eu-central-1a", "eu-central-1b"]
  public_subnets   = ["10.20.0.0/24", "10.20.1.0/24"]
  private_subnets  = ["10.20.16.0/20", "10.20.32.0/20"]
  database_subnets = ["10.20.100.0/24", "10.20.101.0/24"]   # + db subnet group
  enable_nat_gateway  = true
  single_nat_gateway  = true          # лаба; прод: one_nat_gateway_per_az = true
  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.eu-central-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}
```
⭐ Один NAT на VPC — экономия ценой отказоустойчивости: упала AZ с NAT — приватные подсети
второй AZ остались без выхода наружу.

---

## 3. EC2: Launch Template + Auto Scaling Group

Одиночная ВМ — это [«02. Compute и SSH-доступ»](/cloud/02-compute-ssh). В проде ВМ одноразовые:
**Launch Template** описывает машину, **ASG** держит нужное число в двух AZ и заменяет больные.

```hcl
data "aws_ssm_parameter" "al2023" {          # свежий AMI без хардкода ami-id
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}
# aws_iam_role "web" (Principal ec2.amazonaws.com) + политика AmazonSSMManagedInstanceCore
# + aws_iam_instance_profile "web" — вход через SSM вместо SSH (Security/05, §7)

resource "aws_launch_template" "web" {
  name_prefix            = "web-"
  image_id               = data.aws_ssm_parameter.al2023.value
  instance_type          = "t3.micro"
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile { name = aws_iam_instance_profile.web.name }
  metadata_options {
    http_tokens                 = "required"   # ⭐ IMDSv2
    http_put_response_hop_limit = 1
  }
  user_data = base64encode(<<-EOT
    #!/bin/bash
    dnf install -y nginx
    echo "ok from $(hostname)" > /usr/share/nginx/html/healthz
    systemctl enable --now nginx
  EOT
  )
}

resource "aws_autoscaling_group" "web" {
  name_prefix               = "web-"
  min_size                  = 2
  max_size                  = 4
  vpc_zone_identifier       = module.vpc.private_subnets   # обе AZ
  target_group_arns         = [aws_lb_target_group.web.arn]
  health_check_type         = "ELB"      # ⭐ больной по мнению ALB → замена
  health_check_grace_period = 120
  launch_template {
    id      = aws_launch_template.web.id
    version = aws_launch_template.web.latest_version
  }
  instance_refresh {                     # новый шаблон → плавная замена машин
    strategy = "Rolling"
    preferences { min_healthy_percentage = 50 }
  }
}

# SG «от группы к группе» (aws_vpc_security_group_ingress_rule/egress_rule):
#   alb ← 80/443 из 0.0.0.0/0 · web ← 80 только от sg alb (referenced_security_group_id)
#   egress web → всё (dnf, SSM)
```

| Приём | Зачем |
|-------|-------|
| `health_check_type = "ELB"` | По умолчанию ASG смотрит только статус EC2: nginx упал, а машина «здорова» |
| Instance refresh | Раскатка нового AMI/user_data без ручной ротации |
| Target tracking (`aws_autoscaling_policy`, `ASGAverageCPUUtilization` = 50) | «Держи CPU 50%» вместо ручных порогов |
| Spot через `mixed_instances_policy` | Stateless в разы дешевле; нужна обработка прерывания |

---

## 4. ALB и NLB

| | ALB (L7) | NLB (L4) |
|---|---------|----------|
| Протоколы | HTTP/HTTPS, gRPC, WebSocket | TCP, UDP, TLS |
| Маршрутизация | По host, path, заголовкам | По порту |
| IP | Меняются, есть только DNS-имя | Статический IP на AZ, можно свой EIP |
| IP клиента | `X-Forwarded-For` | Сохраняется (или proxy protocol v2) |
| Security groups | Да | Да, но задаются **при создании** |
| Когда | Веб, API, Ingress в EKS | Не-HTTP, статический IP для whitelist |

```hcl
resource "aws_lb" "web" {
  name_prefix        = "web-"
  load_balancer_type = "application"
  subnets            = module.vpc.public_subnets
  security_groups    = [aws_security_group.alb.id]
}
resource "aws_lb_target_group" "web" {
  name_prefix          = "web-"
  port                 = 80
  protocol             = "HTTP"
  vpc_id               = module.vpc.vpc_id
  deregistration_delay = 30              # по умолчанию 300 с — деплой «висит» 5 минут
  health_check { path = "/healthz" }     # matcher по умолчанию 200; ещё interval, *_threshold
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
```
В проде на 80 — `default_action { type = "redirect" }` на 443, а listener 443 с
`protocol = "HTTPS"`, `ssl_policy` (TLS 1.3) и `certificate_arn` из **ACM** — публичные
сертификаты ACM бесплатны и продлеваются сами при DNS-валидации.
`deregistration_delay` — это connection draining: сколько ALB ждёт, пока выводимая машина
допишет ответы. Связка с graceful shutdown приложения.

---

## 5. Route 53

| Что | Зачем |
|-----|-------|
| Public / private hosted zone | DNS домена в интернете / внутренние имена в VPC |
| **Alias**-запись | Как CNAME, но и на вершине зоны (`example.kz → ALB`); запросы к alias на ресурсы AWS бесплатны |
| Routing policy | simple, weighted (canary 90/10), latency, failover (с health check), geolocation |

В Terraform: `aws_route53_record` с `type = "A"` и блоком `alias` (`name = aws_lb.web.dns_name`,
`zone_id = aws_lb.web.zone_id`, `evaluate_target_health = true`).

> 💡 Домен `.kz` регистрируется у казахстанского регистратора, а зону можно держать в Route 53 —
> у регистратора прописываются NS-серверы зоны.

---

## 6. RDS PostgreSQL: Multi-AZ, реплики, PITR

| Вариант | Что это | Чтение со standby | Когда |
|---------|---------|-------------------|-------|
| Single-AZ | Один инстанс | — | dev/stage |
| **Multi-AZ DB instance** | Primary + синхронный standby в другой AZ | ❌ | ⭐ Типовой прод |
| Multi-AZ DB cluster | Writer + 2 читающих реплики в 3 AZ, полусинхронно | ✅ | Много чтения (только отдельные классы инстансов) |
| Read replica | Асинхронная копия, можно в другом регионе | ✅ | Отчёты, DR; promote — вручную |

**Бэкапы и PITR:** автоматические бэкапы с retention до 35 дней, журналы транзакций уходят
в S3 каждые 5 минут (отсюда `LatestRestorableTime`). ⭐ PITR **создаёт новый инстанс**, старый
не трогает — приложение переключаешь сам. Ручные снапшоты переживают удаление базы.

```hcl
resource "aws_db_instance" "pg" {
  identifier                  = "linkd-pg"
  engine                      = "postgres"
  engine_version              = "17"      # aws rds describe-db-engine-versions --engine postgres
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  max_allocated_storage       = 100       # автоматический рост диска
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "linkd"
  username                    = "linkd_admin"
  manage_master_user_password = true      # ⭐ пароль в Secrets Manager, не в state
  multi_az                    = true
  db_subnet_group_name        = module.vpc.database_subnet_group_name
  vpc_security_group_ids      = [aws_security_group.db.id]   # 5432 только от web/EKS
  backup_retention_period     = 7
  backup_window                = "20:00-21:00"   # UTC = 01:00–02:00 по Астане
  deletion_protection         = true
  final_snapshot_identifier   = "linkd-pg-final"
}
```
```bash
aws rds describe-db-instances --db-instance-identifier linkd-pg \
  --query 'DBInstances[0].[Endpoint.Address,MultiAZ,AvailabilityZone,SecondaryAvailabilityZone,LatestRestorableTime]'
aws rds reboot-db-instance --db-instance-identifier linkd-pg --force-failover   # учебный failover
aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier linkd-pg \
  --target-db-instance-identifier linkd-pg-restore --restore-time 2026-09-27T10:00:00Z
```
- Failover меняет, куда указывает DNS-имя endpoint'а: приложение должно переподключаться
  и не кэшировать DNS навечно (классика — JVM).
- Параметры — через **parameter group** (static требуют ребута); старые мажорные версии уходят
  в платный **RDS Extended Support**. Проверка восстановления — твоя работа
  ([«05. Бэкап и восстановление»](/databases/05-backup-restore)).

---

## 7. EKS: кластер и Pod Identity

**Версии (сентябрь 2026):** standard support — 1.36, 1.35, 1.34; extended — 1.33, 1.32, 1.31.
Версия живёт 14 месяцев в standard ($0.10/ч за кластер) и ещё 12 в extended ($0.60/ч —
в 6 раз дороже, включён **по умолчанию**). После конца extended control plane обновят
принудительно, а ноды и add-ons — нет.

| Где запускать поды | Кто управляет нодами | Когда |
|--------------------|---------------------|-------|
| Managed node groups | AWS создаёт ASG; обновление версии — твоё действие | ⭐ Классика, полный контроль |
| Karpenter (свой) | Karpenter подбирает инстансы под поды | Разнородные нагрузки, spot |
| **Auto Mode** | AWS: ноды Bottlerocket без SSH/SSM, живут ≤ 21 дня; автоскейлинг (Karpenter), LB, EBS CSI, Pod Identity agent встроены | Мало людей на платформу; надбавка за инстанс |
| Fargate | Под = микро-ВМ | Редко: нет DaemonSet и Pod Identity |

**Add-ons:** `vpc-cni`, `coredns`, `kube-proxy`, `eks-pod-identity-agent`, `aws-ebs-csi-driver`;
AWS Load Balancer Controller ставится Helm'ом (в Auto Mode встроен). Доступ людей в кластер —
через **access entries** (EKS API), а не старый ConfigMap `aws-auth`.

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name                   = "lab"
  kubernetes_version     = "1.36"
  endpoint_public_access = true      # лаба; прод — приватный endpoint или список CIDR
  enable_cluster_creator_admin_permissions = true   # access entry для создателя
  addons = { coredns = {}, kube-proxy = {}, vpc-cni = { before_compute = true },
             eks-pod-identity-agent = { before_compute = true } }
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets
  eks_managed_node_groups = {
    default = { ami_type = "AL2023_x86_64_STANDARD", instance_types = ["t3.medium"],
                min_size = 2, max_size = 3, desired_size = 2 }
  }
}
```

**Pod Identity vs IRSA** — оба дают поду временные креды роли (идея — Security/05, §5):

| | IRSA | ⭐ EKS Pod Identity |
|---|------|---------------------|
| Механизм | OIDC-провайдер кластера в IAM + `AssumeRoleWithWebIdentity` | Агент на ноде (DaemonSet) + EKS Auth API |
| Trust policy | Своя под каждый кластер (issuer + `sub`) | Одна: `Service: pods.eks.amazonaws.com` — роль переиспользуется между кластерами |
| Привязка | Аннотация на ServiceAccount | Association в EKS API: namespace + SA → роль |
| Где работает | EKS, Fargate, свой k8s с OIDC | Только EKS на Linux EC2 |

**Приложение `reports` читает бакет `linkd-reports`:**
```hcl
resource "aws_iam_role" "reports" {
  name = "linkd-reports-s3-read"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "pods.eks.amazonaws.com" },
    Action = ["sts:AssumeRole", "sts:TagSession"] }] })
}
resource "aws_iam_role_policy" "reports_s3" {
  role = aws_iam_role.reports.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "s3:ListBucket", Resource = "arn:aws:s3:::linkd-reports" },
    { Effect = "Allow", Action = "s3:GetObject",  Resource = "arn:aws:s3:::linkd-reports/*" } ] })
}
resource "aws_eks_pod_identity_association" "reports" {
  cluster_name    = module.eks.cluster_name
  namespace       = "linkd"
  service_account = "reports"
  role_arn        = aws_iam_role.reports.arn
}
```
```bash
aws eks update-kubeconfig --name lab --region eu-central-1
kubectl create namespace linkd && kubectl -n linkd create serviceaccount reports   # без аннотаций
kubectl -n linkd run s3-check --image=amazon/aws-cli:latest --restart=Never \
  --overrides='{"spec":{"serviceAccountName":"reports"}}' -- s3 ls s3://linkd-reports/
kubectl -n linkd logs s3-check                          # список объектов = креды роли получены
kubectl -n linkd get pod s3-check -o yaml | grep -A1 AWS_CONTAINER   # …FULL_URI http://169.254.170.23/…
```
⚠️ Если в поде есть креды раньше по цепочке SDK (переменные `AWS_ACCESS_KEY_ID`, файл),
SDK возьмёт их, а не Pod Identity. И закрой подам IMDS ноды (hop limit 1 в launch template
нод), иначе под получит роль ноды.

---

## 8. CloudWatch: метрики, логи, алармы

| Что | Факт | Следствие |
|-----|------|-----------|
| Метрики EC2 | CPU, сеть, дисковые операции; **нет памяти и места на диске** | CloudWatch agent или node_exporter |
| Частота EC2 | Раз в 5 минут; detailed (1 мин) — платно | Для скейлинга включай detailed |
| Logs retention | ⭐ По умолчанию **никогда не удаляются** | Retention на каждой группе |

```hcl
resource "aws_sns_topic" "alerts" { name = "lab-alerts" }   # + подписка email (подтвердить письмом)
resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  alarm_name          = "web-target-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.web.arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3                   # 3 плохих минуты из 5 — меньше флаппинга
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"      # нет запросов = не авария
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
```
Ещё обязательные: `UnHealthyHostCount` (dimensions `TargetGroup` + `LoadBalancer`), RDS
`FreeStorageSpace`, `CPUUtilization`, `DatabaseConnections`, `ReplicaLag`.
```bash
aws logs put-retention-policy --log-group-name /aws/eks/lab/cluster --retention-in-days 14
aws cloudwatch set-alarm-state --alarm-name web-target-5xx --state-value ALARM --state-reason test
```
Основную наблюдаемость часто строят на Prometheus/Grafana ([Мониторинг](/monitoring/)),
забирая метрики AWS экспортером; CloudWatch остаётся источником метрик managed-сервисов.

---

## 9. Деньги: ловушки AWS

| Ловушка | Порядок цен (us-east-1) | Что делать |
|---------|-------------------------|-----------|
| **NAT Gateway** | $0.045/ч (≈ $33/мес за штуку) **+ $0.045 за ГБ** через него | S3 — через gateway endpoint; ECR — через endpoints или кэш; в dev — один NAT |
| **Межзонный трафик** | ≈ $0.01/ГБ в каждую сторону | Болтливые сервисы — в одной AZ; topology-aware routing в k8s |
| **Публичный IPv4** | $0.005/ч за **каждый** адрес, даже используемый (с 01.02.2024), ≈ $3.6/мес | Нагрузки без публичных IP, IPv6; Public IP Insights в VPC IPAM |
| **EKS extended support** | $0.60/ч против $0.10/ч (≈ $438 против $73 в месяц) | Обновлять кластер в пределах 14 месяцев |
| **Idle EBS и снапшоты** | Платишь за ГБ, даже без ВМ | Поиск `available`-дисков, lifecycle снапшотов |
| **Interface endpoints** | За час в **каждой AZ** + за ГБ | Считать: иногда NAT дешевле |
| **Забытые ALB, RDS, EKS** | Часы идут без нагрузки | Теги `owner`/`env`, еженедельный отчёт «сирот» |

```bash
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].[VolumeId,Size]' --output table
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' --output table
aws logs describe-log-groups --query 'logGroups[?retentionInDays==null].logGroupName'
aws ce get-cost-and-usage --time-period Start=2026-09-01,End=2026-09-27 --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE
```

**Free tier (аккаунты с 15 июля 2025):** $100 кредитов при регистрации и до $100 ещё за
задания; на выбор **Free plan** или **Paid plan**. Free plan не списывает деньги, но кончается
через 6 месяцев или с кредитами — аккаунт закрывается, данные хранятся 90 дней до апгрейда.
Часть сервисов на Free plan недоступна, а вступление в **Organizations / Control Tower
переводит аккаунт на Paid автоматически**. Аккаунты до 15.07.2025 — на старой схеме
«12 месяцев free tier». Бюджеты и аномалии стоит заводить в Terraform.

---

## 10. AWS и Казахстан

- **Региона AWS в Казахстане нет** (сентябрь 2026 — проверь на странице Global Infrastructure).
  Регион выбирают по замеру задержки от пользователей; из КЗ обычно смотрят на eu-central-1
  (Франкфурт) и ближневосточные регионы — меряй сам.
- Значит, **базы с ПДн граждан РК в AWS как основное хранилище держать нельзя**
  (Security/07, §7) — это гибрид «ПДн в КЗ, остальное в AWS», [«10. Облака Казахстана»](/cloud/10-kz-clouds).
- Оплата в долларах картой: курс тенге делает счёт волатильным — закладывай запас в бюджет.

---

## 🧪 Мини-лаба: ASG за ALB с бюджетом и уборкой

> Порядок стоимости — $0.1–0.2 в час (ALB + NAT + 2 × t3.micro + публичные IPv4). Уложись в 2 часа.

```bash
# 0. Сначала бюджет — до любых ресурсов
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo '{"BudgetName":"lab-10usd","BudgetLimit":{"Amount":"10","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' > budget.json
cat > notif.json <<'EOF'
[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},
  "Subscribers":[{"SubscriptionType":"EMAIL","Address":"me@example.kz"}]},
 {"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},
  "Subscribers":[{"SubscriptionType":"EMAIL","Address":"me@example.kz"}]}]
EOF
aws budgets create-budget --account-id "$ACCOUNT_ID" --budget file://budget.json \
  --notifications-with-subscribers file://notif.json

# 1. Код из §2, §3, §4, §8 (+ IAM-роль ВМ и SG alb/web) → ~/labs/aws-asg/main.tf
cd ~/labs/aws-asg && terraform init && terraform plan -out tf.plan && terraform apply tf.plan

# 2. Балансировка: ответы от двух машин
ALB=$(aws elbv2 describe-load-balancers --query 'LoadBalancers[0].DNSName' --output text)
for i in $(seq 1 6); do curl -s "http://$ALB/healthz"; done

# 3. Самоизлечение: убей машину и смотри замену
ASG_Q='AutoScalingGroups[0].Instances'
aws ec2 terminate-instances --instance-ids "$(aws autoscaling describe-auto-scaling-groups --query "$ASG_Q[0].InstanceId" --output text)"
watch -n 10 "aws autoscaling describe-auto-scaling-groups --query '$ASG_Q[].[InstanceId,AvailabilityZone,LifecycleState,HealthStatus]' --output table"

# 4. Вход без SSH; 5. поменяй user_data → apply → смотри instance refresh в консоли EC2
aws ssm start-session --target "$(aws autoscaling describe-auto-scaling-groups --query "$ASG_Q[0].InstanceId" --output text)"
# 6. Доставка аларма: письмо должно прийти
aws cloudwatch set-alarm-state --alarm-name web-target-5xx --state-value ALARM --state-reason lab

# 7. ⭐ Уборка и проверка «сирот» (все списки пустые)
terraform destroy
aws ec2 describe-nat-gateways --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws ec2 describe-addresses --query 'Addresses[].PublicIp'; aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
```
Расширение (≈ $0.3–0.5/ч): модуль EKS (§7), роль и association для `reports`, `aws s3 ls`
из пода — и **сразу** `terraform destroy`.

---

## 11. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| Всё в одном аккаунте | Ошибка в dev ломает prod | Organizations: prod/stage/dev раздельно |
| Люди входят IAM users с ключами | Вечные ключи в `~/.aws/credentials` | Identity Center + `aws sso login` |
| SCP с запретом региона без `NotAction` | Ломаются IAM, Route 53, CloudFront | Исключить глобальные сервисы |
| Один NAT на прод-VPC / S3 через NAT | Упала AZ — нет выхода; счёт за ГБ | NAT на AZ; gateway endpoint S3 |
| Private-подсети `/24` под EKS | Поды не получают IP | `/20` и крупнее |
| ASG с EC2 health check | Мёртвое приложение на «здоровой» машине | `health_check_type = "ELB"` |
| Приложение ходит в RDS по IP | После failover — ошибки | DNS-имя endpoint'а, короткий DNS-кэш |
| Нет `deletion_protection` на RDS | `terraform destroy` снёс прод-базу | `deletion_protection` + final snapshot |
| EKS не обновляли 14+ месяцев | Control plane ×6 в счёте | План обновлений, алерт на дату конца поддержки |
| Free plan + Organizations «для практики» | Аккаунт стал платным | Сначала бюджет, потом эксперименты |

---

## 💼 Как это в DevOps

- Первые вопросы в AWS-команде: сколько аккаунтов, как в них входят, где CloudTrail, кто
  получает алерты бюджета. Ответы говорят о зрелости больше, чем набор сервисов.
- Всё из темы живёт в Terraform: `terraform-aws-modules/{vpc,eks,rds}` с пином версии,
  ручные клики — только read-only.
- CI ходит в AWS по OIDC (Security/05, §6), поды — через
  Pod Identity, ВМ — через instance profile. Статический access key в проекте — повод для задачи.
- На собесе по AWS почти всегда: public/private и NAT, SG vs NACL, ALB vs NLB, Multi-AZ vs
  read replica, IRSA/Pod Identity, «почему вырос счёт».
- Ежемесячно: Cost Explorer по сервисам, «сироты», версии EKS и RDS против календаря поддержки.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Войти через SSO / кто я | `aws sso login --profile <p>` / `aws sts get-caller-identity` |
| Свежий AMI AL2023 | SSM-параметр `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` |
| Здоровье таргетов | `aws elbv2 describe-target-health --target-group-arn <arn>` |
| Зайти на ВМ без SSH | `aws ssm start-session --target <instance-id>` |
| Учебный failover RDS | `aws rds reboot-db-instance --db-instance-identifier <id> --force-failover` |
| PITR | `aws rds restore-db-instance-to-point-in-time --source-… --target-… --restore-time …` |
| Kubeconfig / версии EKS | `aws eks update-kubeconfig --name <c>` / `aws eks describe-cluster-versions` |
| Роль для SA | `aws eks create-pod-identity-association --cluster-name … --namespace … --service-account … --role-arn …` |
| Retention логов | `aws logs put-retention-policy --log-group-name … --retention-in-days 14` |
| Проверить аларм | `aws cloudwatch set-alarm-state --alarm-name … --state-value ALARM --state-reason test` |
| Расходы по сервисам | `aws ce get-cost-and-usage … --group-by Type=DIMENSION,Key=SERVICE` |

---

## 🧠 Что запомнить

1. Аккаунт — самая сильная граница: prod, stage, dev и логи — в разных аккаунтах Organizations.
2. SCP, RCP и permission boundary только ограничивают максимум; люди входят через Identity
   Center, программы — через роли.
3. Эталонная VPC: public/private/db-подсети в двух AZ, NAT на AZ в проде, gateway endpoint S3.
4. Под EKS private-подсети делают крупными: поды получают адреса VPC.
5. ВМ в проде — Launch Template + ASG в двух AZ с ELB health check и instance refresh.
6. ALB — для HTTP и Ingress, NLB — для TCP/UDP и статических IP; `deregistration_delay`
   связан с graceful shutdown.
7. RDS Multi-AZ instance — синхронный standby без чтения; для чтения — cluster или read
   replica; PITR создаёт новый инстанс.
8. EKS стоит $0.10/ч 14 месяцев, дальше $0.60/ч; Pod Identity проще IRSA — одна trust policy
   `pods.eks.amazonaws.com` и association вместо аннотаций.
9. Сюрпризы счёта: NAT (час + ГБ), межзонный трафик, каждый публичный IPv4, забытые диски,
   логи без retention, extended support.
10. Региона AWS в Казахстане нет: ПДн граждан РК держат в КЗ, AWS — для остального.

---

## Задачи

> ⚠️ Сначала бюджет с уведомлением, потом ресурсы. NAT, ALB, EKS, RDS и публичные IPv4
> тарифицируются почасово — `terraform destroy` в конце каждого занятия.

---

### Блок A. Теория

**A1.** Почему prod и dev разводят по разным аккаунтам, а не по IAM-политикам внутри одного?

<details><summary>Ответ</summary>

Аккаунт — самая сильная граница: ресурсы, квоты, IAM и биллинг изолированы. Ошибка
в политике внутри одного аккаунта открывает prod; между аккаунтами доступ появляется только
явно (роль с trust). Плюс раздельный учёт денег и blast radius.

</details>

**A2.** Чем SCP отличается от IAM-политики? Действует ли SCP на management-аккаунт?

<details><summary>Ответ</summary>

IAM-политика даёт права principal'у; SCP ничего не даёт, а задаёт потолок для всех
principal'ов аккаунтов в OU (включая root аккаунта-участника). На management-аккаунт SCP
не действуют — поэтому в нём не держат нагрузок.

</details>

**A3.** Что такое RCP и какую задачу она решает, которую не решает SCP?

<details><summary>Ответ</summary>

RCP ограничивает то, что можно делать с **ресурсами** аккаунтов, независимо от того,
чей principal стучится: например, запретить доступ к бакетам и KMS-ключам организации
principal'ам извне. SCP касается только своих principal'ов.

</details>

**A4.** Зачем нужна permission boundary? Приведи сценарий делегирования.

<details><summary>Ответ</summary>

Чтобы делегировать создание ролей без эскалации: разработчик может создавать роли
для Lambda/подов, но только с boundary `DevBoundary`; итоговые права роли — пересечение её
политик и boundary, выше не выдать.

</details>

**A5.** IAM user, IAM role, Identity Center — кому что выдавать?

<details><summary>Ответ</summary>

Людям — Identity Center (SSO, временные креды, одна точка offboarding). Сервисам и CI —
роли (instance profile, Pod Identity, OIDC). IAM user с ключами — только исключения, где
федерация невозможна, с ротацией и минимальными правами.

</details>

**A6.** Почему запрет «всё, кроме eu-central-1» в SCP пишут через `NotAction`?

<details><summary>Ответ</summary>

Глобальные сервисы (IAM, Organizations, STS, Route 53, CloudFront, Support, Billing)
обрабатываются через us-east-1; `Deny "*"` по региону сломает их. `NotAction` исключает их
из запрета.

</details>

**A7.** Что делает подсеть в AWS публичной? Сколько адресов подсети забирает AWS?

<details><summary>Ответ</summary>

Маршрут `0.0.0.0/0` на Internet Gateway в route table подсети (и публичные IP у
ресурсов). AWS резервирует 5 адресов в каждой подсети (сеть, роутер, DNS, резерв, broadcast).

</details>

**A8.** ⭐ Один NAT Gateway на VPC или по одному на AZ — плюсы и минусы. Что меняет Regional NAT GW?

<details><summary>Ответ</summary>

Один NAT дешевле (≈ $33/мес за штуку + трафик), но падение его AZ лишает выхода всю VPC;
плюс межзонный трафик до NAT. NAT на AZ — отказоустойчиво и без межзонного трафика, но дороже.
Regional NAT GW сам расширяется по AZ, где есть нагрузки, — меньше ручной работы, а платишь
за каждую активную AZ так же.

</details>

**A9.** Чем gateway endpoint отличается от interface endpoint? Какой из них бесплатный?

<details><summary>Ответ</summary>

Gateway endpoint (S3, DynamoDB) — запись в route table, бесплатный. Interface endpoint
(ECR, STS, SSM, Logs и др.) — ENI с приватным IP в подсетях, платный почасово за каждую AZ
и за ГБ.

</details>

**A10.** Почему под EKS private-подсети делают `/20`, а не `/24`?

<details><summary>Ответ</summary>

VPC CNI даёт каждому поду адрес из подсети VPC; ноды резервируют адреса пачками.
`/24` (251 адрес) кончится на нескольких нодах — поды не создадутся.

</details>

**A11.** Зачем ASG `health_check_type = "ELB"` и `health_check_grace_period`?

<details><summary>Ответ</summary>

По умолчанию ASG знает только статус EC2 (машина жива). С `ELB` машина, проваливающая
health check балансировщика, считается больной и заменяется. Grace period даёт время на
загрузку и user_data, чтобы новую машину не убили сразу.

</details>

**A12.** ALB или NLB: назови по два случая для каждого.

<details><summary>Ответ</summary>

ALB: HTTP-API с маршрутизацией по host/path; Ingress в EKS; HTTPS с сертификатом ACM.
NLB: не-HTTP протоколы (TCP/UDP, например MQTT, игровые серверы); нужен статический IP для
whitelist у партнёра; сохранение IP клиента на L4.

</details>

**A13.** ⭐ Multi-AZ DB instance, Multi-AZ DB cluster и read replica — чем отличаются?

<details><summary>Ответ</summary>

Multi-AZ instance — primary + синхронный standby в другой AZ, standby не читается,
только failover. Multi-AZ cluster — writer + 2 читающих реплики в 3 AZ с полусинхронной
репликацией, быстрее failover и есть чтение (ограниченный набор классов). Read replica —
асинхронная копия (можно в другом регионе) для чтения и DR, promote вручную, возможен лаг.

</details>

**A14.** Как работает PITR в RDS и что происходит с исходной базой?

<details><summary>Ответ</summary>

RDS хранит автоматические бэкапы и журналы транзакций (выгружаются в S3 каждые
5 минут); восстановление на момент в пределах retention создаёт **новый** инстанс. Исходный
не меняется; переключить приложение и удалить лишнее — твоя работа.

</details>

**A15.** ⭐ Сравни IRSA и EKS Pod Identity: механизм, trust policy, ограничения.

<details><summary>Ответ</summary>

IRSA: OIDC-провайдер кластера в IAM, токен SA обменивается на креды через
`AssumeRoleWithWebIdentity`, trust policy завязана на issuer конкретного кластера, SA
аннотируется. Pod Identity: агент на ноде + EKS Auth API, trust policy одна
(`pods.eks.amazonaws.com`, `sts:AssumeRole` + `sts:TagSession`), связь — association в EKS API,
роль переиспользуется между кластерами. Pod Identity работает только в EKS на Linux EC2
(не Fargate, не Windows); IRSA — и на Fargate, и в своём k8s с OIDC.

</details>

**A16.** Что такое EKS extended support и сколько он стоит относительно standard?

<details><summary>Ответ</summary>

После 14 месяцев standard версия ещё 12 месяцев живёт в extended: патчи безопасности,
но $0.60/ч за кластер вместо $0.10/ч. Включён по умолчанию; по окончании control plane
обновят принудительно.

</details>

**A17.** Что даёт EKS Auto Mode и чего в нём нельзя (по сравнению с managed node groups)?

<details><summary>Ответ</summary>

AWS управляет нодами (Bottlerocket, автоскейлинг на Karpenter, замена не реже чем
через 21 день), LB, EBS CSI, сетью, Pod Identity agent встроен. Нельзя зайти на ноду (нет SSH
и SSM), нельзя свой AMI и ручную настройку ОС; за инстансы — надбавка к цене EC2.

</details>

**A18.** Каких метрик EC2 нет в CloudWatch по умолчанию и что с этим делать?

<details><summary>Ответ</summary>

Памяти и занятого места на диске: это внутри ОС, гипервизор их не видит. Ставят
CloudWatch agent или node_exporter + Prometheus.

</details>

---

### Блок B. «Оцени конфигурацию»

```text:no-line-numbers
B1.  Разработчики входят в prod-аккаунт IAM user'ами с access keys в ~/.aws/credentials
B2.  SCP: Deny "*" при aws:RequestedRegion != eu-central-1 (без исключений)
B3.  VPC для EKS: private-подсети 10.0.1.0/24 и 10.0.2.0/24
B4.  Прод-VPC на 2 AZ, single_nat_gateway = true
B5.  Ноды EKS в private-подсетях, тянут 40 ГБ образов из ECR в день, endpoints нет
B6.  ASG: min=1, max=1, одна подсеть, health_check_type = "EC2"
B7.  Launch Template: http_tokens = "optional"
B8.  Target group: deregistration_delay = 300, приложение завершается за 2 секунды
B9.  RDS: multi_az = true, приложение подключается по IP primary
B10. RDS: deletion_protection = false, skip_final_snapshot = true в прод-модуле
B11. aws_db_instance с password = var.db_password в terraform.tfvars
B12. EKS 1.31, «работает — не трогаем», upgrade policy по умолчанию
B13. Pod Identity association есть, а в Deployment env AWS_ACCESS_KEY_ID из Secret
B14. Trust policy роли для Pod Identity: Principal Service pods.eks.amazonaws.com, Action sts:AssumeRole, sts:TagSession
B15. Лог-группы /aws/eks/*/cluster без retention
B16. 12 EIP в аккаунте, из них 5 не привязаны
```

<details><summary>Ответ</summary>

**B1.** Плохо: вечные ключи у людей в prod. Identity Center + `aws sso login`, ключи удалить.
**B2.** Сломаются IAM, STS, Route 53, CloudFront, Billing — нужен `NotAction` с глобальными
сервисами.
**B3.** Мало адресов для VPC CNI — поды упрутся в IP. `/20` или крупнее, либо prefix
delegation/доп. CIDR.
**B4.** Экономно, но AZ с NAT — точка отказа для всей VPC. Для прода — NAT на AZ.
**B5.** 40 ГБ/день × $0.045 через NAT — лишние деньги. Gateway endpoint S3 (слои ECR лежат
в S3) + interface endpoints `ecr.api`/`ecr.dkr`, или pull-through cache.
**B6.** Нет отказоустойчивости: одна машина, одна AZ, и больное приложение не заменяется.
min=2 в двух AZ, `ELB` health check.
**B7.** IMDSv1 доступен: SSRF в приложении → креды роли ВМ. `required` + hop limit 1.
**B8.** Каждая выводимая машина ждёт 5 минут впустую; ставь 30–60 с под реальное время
graceful shutdown.
**B9.** После failover primary другой — IP не тот. Подключаться по DNS-имени endpoint'а.
**B10.** Одна команда — и прод-базы нет вместе с автоматическими бэкапами. Включить
`deletion_protection`, final snapshot, ручные снапшоты/AWS Backup в другой аккаунт.
**B11.** Пароль в state и в репо. `manage_master_user_password = true` (Secrets Manager).
**B12.** 1.31 в extended — $0.60/ч, и в ноябре 2026 кончится extended: control plane обновят
принудительно. Планировать апгрейд по одной минорной версии.
**B13.** Статический ключ раньше в цепочке SDK — Pod Identity не используется, а ключ висит
в Secret. Убрать env и Secret.
**B14.** Правильная trust policy для Pod Identity.
**B15.** Логи хранятся вечно и растут в счёте. Retention 7–30 дней в Terraform.
**B16.** 5 непривязанных EIP платятся впустую (как и все 12 — за каждый IPv4 $0.005/ч).
Освободить лишние, проверить, нужны ли публичные адреса вообще.

</details>

---

### Блок C. Практика

#### C1. 🔑 Бюджет до всего
Создай бюджет на $10 с уведомлениями `ACTUAL` 50% и `FORECASTED` 100% через
`aws budgets create-budget`. Проверь в консоли Billing, что он есть.

<details><summary>Ответ</summary>

`describe-budgets --account-id …` показывает бюджет; письмо о подписке приходит,
когда сработает порог.

</details>

#### C2. SSO-профиль
Если есть Identity Center — настрой `aws configure sso` и зайди `aws sso login`. Если нет —
создай роль с trust на свой аккаунт и зайди через `aws sts assume-role`. Сравни ARN из
`get-caller-identity` с ARN IAM user.

<details><summary>Ответ</summary>

У роли ARN вида `arn:aws:sts::<acc>:assumed-role/<role>/<session>`, у пользователя —
`arn:aws:iam::<acc>:user/<name>`; креды роли временные (есть `AWS_SESSION_TOKEN`).

</details>

#### C3. 🔑 Эталонная VPC
Terraform-модулем `terraform-aws-modules/vpc/aws` подними VPC на 2 AZ (public/private/db),
один NAT, gateway endpoint S3. Найди в route table private-подсети маршрут на endpoint
(префикс-лист `pl-…`).

<details><summary>Ответ</summary>

В route table private-подсети появляется маршрут с назначением `pl-…` (префикс-лист
S3) на `vpce-…`.

</details>

#### C4. ASG за ALB
Launch Template (AL2023, IMDSv2, nginx в user_data) + ASG min=2 в двух AZ + ALB с health
check `/healthz`. Докажи `curl`'ом, что отвечают две машины.

#### C5. Самоизлечение и раскатка
1. Убей одну машину — засеки время до замены.
2. Останови nginx на второй через SSM — что сделает ASG с `EC2` и с `ELB` health check?
3. Поменяй user_data, `terraform apply` — посмотри instance refresh.

<details><summary>Ответ</summary>

С `EC2` health check ASG машину с остановленным nginx не заменит (ALB её просто
исключит); с `ELB` — заменит после провала проверок и grace period.

</details>

#### C6. RDS (по желанию, платно)
Подними `db.t4g.micro` Multi-AZ с `manage_master_user_password`. Достань пароль из Secrets
Manager, подключись с ВМ через `psql`, сделай `--force-failover` и посмотри, как меняется
`AvailabilityZone` и сколько длился разрыв.

<details><summary>Ответ</summary>

После failover меняются `AvailabilityZone` и `SecondaryAvailabilityZone` местами;
разрыв обычно порядка минуты-двух, приложение должно переподключиться.

</details>

#### C7. PITR
Создай таблицу, вставь строку, через 10 минут удали её. Восстанови базу на момент до
удаления в **новый** инстанс, проверь строку, удали восстановленный инстанс.

<details><summary>Ответ</summary>

Ключевой момент — восстановление не трогает исходную базу; имя нового инстанса
задаёшь сам.

</details>

#### C8. 🔑 EKS + Pod Identity (платно, ≈ час)
Кластер модулем `eks ~> 21.0`, add-on `eks-pod-identity-agent`, роль с trust
`pods.eks.amazonaws.com`, association для `linkd/reports`. Из пода `aws s3 ls` своего бакета
работает, чужого — `AccessDenied`. Затем `terraform destroy`.

<details><summary>Ответ</summary>

Из пода `aws sts get-caller-identity` показывает `assumed-role/linkd-reports-s3-read/…`;
чужой бакет — `AccessDenied`, потому что политика роли разрешает только `linkd-reports`.

</details>

#### C9. Алармы
Аларм на `HTTPCode_Target_5XX_Count` и `UnHealthyHostCount` с SNS на почту. Спровоцируй
`UnHealthyHostCount` (останови nginx) и дождись письма.

#### C10. 🔑 Охота на сирот
Напиши скрипт `aws-orphans.sh`: непривязанные EIP, диски `available`, NAT, ALB без
здоровых таргетов, лог-группы без retention. Прогони после `destroy` — вывод должен быть пустым.

<details><summary>Ответ</summary>

Основа — запросы из §9 конспекта; для ALB без таргетов —
`describe-target-health` по каждой target group.

</details>

---

### Блок D. Инциденты

**D1.** Счёт за месяц: $180 из них «EC2-Other — NatGateway-Bytes». Как найти источник
и что сделать?

<details><summary>Ответ</summary>

Cost Explorer по usage type и ресурсам, VPC Flow Logs на ENI NAT → кто качает.
Типично: трафик в S3/ECR через NAT (→ gateway endpoint S3, endpoints ECR), выгрузки в интернет,
логи и метрики наружу. Дальше — endpoints, кэш образов, сжатие.

</details>

**D2.** После падения AZ `eu-central-1a` поды в `eu-central-1b` живы, но не могут скачать
образы и ходить во внешние API. Почему?

<details><summary>Ответ</summary>

Единственный NAT стоял в упавшей AZ — у private-подсетей второй AZ маршрут в никуда.
NAT на каждую AZ (или Regional NAT GW) и endpoints для AWS-сервисов.

</details>

**D3.** Новые поды EKS висят в `ContainerCreating` с ошибкой про IP-адреса. Что проверить?

<details><summary>Ответ</summary>

Свободные IP в подсетях (`aws ec2 describe-subnets --query 'Subnets[].AvailableIpAddressCount'`),
лимит ENI/IP на тип инстанса, логи `aws-node`. Решение — крупнее подсети, доп. CIDR, prefix
delegation.

</details>

**D4.** Приложение в поде получает `AccessDenied` к S3, хотя association создана. Пять причин.

<details><summary>Ответ</summary>

Нет add-on `eks-pod-identity-agent` или он не запущен на ноде; под использует другой SA
или namespace; под создан до association (нужен рестарт); статические креды раньше в цепочке
SDK; старый SDK без поддержки Pod Identity; политика роли не покрывает ARN (бакет vs `/*`);
trust policy без `sts:TagSession`.

</details>

**D5.** После failover RDS приложение 10 минут сыпало ошибками подключения, потом само
починилось. Что было и как исправить?

<details><summary>Ответ</summary>

Приложение закэшировало старый адрес primary (DNS-кэш JVM/пула) или держало мёртвые
соединения. Короткий TTL DNS-кэша, проверка соединений в пуле, retry с backoff; RDS Proxy
ускоряет переключение.

</details>

**D6.** `terraform destroy` в dev-аккаунте удалил базу вместе с автоматическими бэкапами,
а данные нужны. Что можно было сделать заранее?

<details><summary>Ответ</summary>

Автоматические бэкапы удаляются вместе с инстансом (если их не оставить), final snapshot
выключили. Нужны `deletion_protection`, final snapshot, ручные снапшоты или AWS Backup с копией
в другой аккаунт, `prevent_destroy` в Terraform для критичных ресурсов.

</details>

**D7.** В счёте появилась строка EKS $0.60/ч за кластер. Что случилось и что делать?

<details><summary>Ответ</summary>

Версия кластера вышла из standard support. Планово обновлять по одной минорной версии:
проверить deprecated API, обновить control plane, add-ons, ноды.

</details>

**D8.** Разработчик создал себе роль с `AdministratorAccess`, хотя у него «ограниченные»
права. Как такое возможно и как закрыть?

<details><summary>Ответ</summary>

Разрешён `iam:CreateRole` + `iam:AttachRolePolicy` без permission boundary и с trust
на себя — классическая эскалация. Требовать boundary условием `iam:PermissionsBoundary`,
запретить снимать её, guardrail в SCP.

</details>

**D9.** Деплой через ALB длится 6 минут на каждую машину, хотя приложение стартует за 20 секунд.

<details><summary>Ответ</summary>

`deregistration_delay` по умолчанию 300 с — ALB ждёт 5 минут на каждую выводимую машину.
Поставить под время graceful shutdown (30–60 с).

</details>

**D10.** В AWS-аккаунт компании загрузили дамп базы клиентов из Казахстана «для аналитики».
Что не так и что делать?

<details><summary>Ответ</summary>

Персональные данные граждан РК должны храниться в базе на территории Казахстана — копия
за рубежом, в том числе для аналитики, нарушает требование локализации (Security/07, §7).
Остановить загрузку, удалить копию (с подтверждением удаления из бэкапов/версий бакета),
сообщить ответственному за ПДн; для аналитики — обезличенные данные или обработка внутри КЗ.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как организовать аккаунты AWS для компании из 30 инженеров?

<details><summary>Ответ</summary>

Organizations: management без нагрузок, OU Security (log-archive, security), Workloads
(prod/stage/dev), Sandbox; SCP-guardrails, Identity Center для людей, CloudTrail всей
организации, бюджеты на аккаунт.

</details>

**2.** Как устроена оценка политик: identity, resource, SCP, boundary?

<details><summary>Ответ</summary>

Explicit Deny в любой политике → отказ; иначе должны разрешать SCP, RCP, boundary и session
policy (ограничители), и нужен Allow в identity- или resource-based политике.

</details>

**3.** Нарисуй VPC для веб-приложения с базой на 2 AZ.

<details><summary>Ответ</summary>

Public-подсети с ALB и NAT, private — приложение, db — RDS Multi-AZ; по подсети каждого
типа в двух AZ, SG «от группы к группе», endpoint S3.

</details>

**4.** Зачем NAT Gateway и почему он часто главный пункт счёта?

<details><summary>Ответ</summary>

Даёт приватным ресурсам исходящий доступ без входящего. Платится и за час, и за каждый ГБ —
через него часто неосознанно идут образы, S3 и логи.

</details>

**5.** ALB vs NLB?

<details><summary>Ответ</summary>

ALB — L7 (HTTP, маршрутизация, TLS, WAF); NLB — L4 (TCP/UDP, статические IP, IP клиента,
огромное число соединений).

</details>

**6.** Как ASG понимает, что машину пора заменить?

<details><summary>Ответ</summary>

По health check: EC2 status и, если включено, health check ALB; плюс grace period.
Больную машину завершает и создаёт новую по Launch Template.

</details>

**7.** Multi-AZ vs read replica в RDS?

<details><summary>Ответ</summary>

Multi-AZ — отказоустойчивость (синхронный standby, автоматический failover); read replica —
масштабирование чтения и DR (асинхронно, promote вручную).

</details>

**8.** Как дать поду в EKS доступ к S3 без ключей?

<details><summary>Ответ</summary>

EKS Pod Identity (или IRSA): роль с минимальной политикой, association на namespace/SA,
SDK получает временные креды от агента; статических ключей нет.

</details>

**9.** Как обновлять EKS и почему это нельзя откладывать?

<details><summary>Ответ</summary>

По одной минорной версии: проверить deprecated API, обновить control plane, add-ons, ноды.
Через 14 месяцев — extended support в 6 раз дороже, через 26 — принудительный апгрейд.

</details>

**10.** Почему вырос счёт AWS и как будешь разбираться?

<details><summary>Ответ</summary>

Cost Explorer по сервисам и usage type, теги, аномалии; типичные причины — NAT и трафик,
забытые ресурсы, логи, публичные IPv4, extended support; дальше — endpoints, rightsizing,
уборка, Savings Plans для стабильной базы.

</details>

---

### 🎯 Чек-лист

- [ ] Бюджет с `ACTUAL` и `FORECASTED` создаю до любых ресурсов
- [ ] Объясняю SCP, RCP, permission boundary и Identity Center
- [ ] Собрал VPC на 2 AZ модулем, знаю цену NAT и зачем endpoint S3
- [ ] ⭐ Поднимал ASG за ALB с ELB health check и instance refresh
- [ ] Различаю ALB и NLB и понимаю `deregistration_delay`
- [ ] Знаю разницу Multi-AZ instance / cluster / read replica и делал PITR
- [ ] ⭐ Дал поду EKS доступ к S3 через Pod Identity без ключей
- [ ] Знаю календарь версий EKS и цену extended support
- [ ] Настроил алармы CloudWatch с SNS и проверил доставку
- [ ] После лабы прогоняю поиск «сирот» и вижу пустой вывод
