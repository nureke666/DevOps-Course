---
layout: home
hero:
  name: "DevOps"
  text: "Конспекты и практика"
  tagline: "Личный учебный материал от Junior до Senior: базовый стек, углубление, специализации и карьера"
  actions:
    - theme: brand
      text: Начать с Git
      link: /git/
    - theme: alt
      text: Специализации
      link: /performance/
---

<script setup>
import RoadmapChain from './.vitepress/theme/components/RoadmapChain.vue'

const topicsBase = [
  { title: 'Git', desc: 'Основы, ветки, rebase, стратегии ветвления, Git в DevOps', status: 'active', link: '/git/' },
  { title: 'Linux', desc: 'Файловая система, процессы, права, systemd, сети, bash', status: 'active', link: '/linux/' },
  { title: 'Сети', desc: 'TCP/IP, DNS, HTTP, firewall, nginx, VPN', status: 'active', link: '/network/' },
  { title: 'Docker', desc: 'Контейнеры, образы, Dockerfile, compose, безопасность', status: 'active', link: '/docker/' },
  { title: 'CI/CD', desc: 'Пайплайны, GitOps, GitLab CI, Jenkins, GitHub Actions', status: 'active', link: '/cicd/' },
  { title: 'Ansible', desc: 'Inventory, модули, плейбуки, роли, Vault, CI/CD', status: 'active', link: '/ansible/' },
  { title: 'Kubernetes', desc: 'Pod, Deployment, Service, Ingress, Helm, RBAC, автоскейлинг', status: 'active', link: '/kubernetes/' },
  { title: 'Базы данных', desc: 'PostgreSQL, бэкапы, репликация, мониторинг, MySQL, миграции', status: 'active', link: '/databases/' },
  { title: 'Мониторинг', desc: 'Prometheus, PromQL, Alertmanager, Grafana, Zabbix', status: 'active', link: '/monitoring/' },
  { title: 'Логирование', desc: 'ELK, Loki, сборщики логов, OpenTelemetry', status: 'active', link: '/logging/' },
  { title: 'Облака', desc: 'IaaS/PaaS/SaaS, VPC, S3, managed-сервисы, AWS, Yandex Cloud, КЗ', status: 'active', link: '/cloud/' },
  { title: 'Очереди', desc: 'Kafka, RabbitMQ, гарантии доставки, DLQ', status: 'active', link: '/queues/' },
  { title: 'Terraform', desc: 'IaC, state и backend, модули, workflow в CI/CD, тестирование', status: 'active', link: '/terraform/' },
  { title: 'ArgoCD', desc: 'GitOps: Application, App of Apps, Helm/Kustomize, секреты', status: 'active', link: '/argocd/' },
  { title: 'Vault', desc: 'HashiCorp Vault: KV, auth methods, динамические секреты', status: 'active', link: '/vault/' },
]

const topicsAdvanced = [
  { title: 'Performance', desc: 'Метод USE, чек-лист «60 секунд», flame graphs, OOM killer, I/O latency, TCP, strace, cgroups, eBPF', status: 'active', link: '/performance/' },
  { title: 'Хранилища и Stateful', desc: 'LVM, RAID, Ceph, MinIO S3, StatefulSet, CSI, Patroni, WAL-G бэкапы БД и Velero DR', status: 'active', link: '/storage/' },
  { title: 'Виртуализация On-Prem', desc: 'KVM, QEMU, libvirt, мосты и VLAN, Proxmox VE, LXC и автоматизация через Packer, Terraform, Ansible', status: 'active', link: '/virtualization/' },
  { title: 'Platform Engineering', desc: 'CRD и kopf операторы, Kyverno/VAP политики, Service Mesh, Argo Rollouts, Crossplane, Backstage', status: 'active', link: '/platform/' },
  { title: 'SRE и Observability', desc: 'SLI/SLO/SLA, Error Budget, burn-rate алерты, OpenTelemetry трейсинг, онколл, постмортемы', status: 'active', link: '/sre/' },
  { title: 'Распределённые системы', desc: 'CAP/PACELC, репликация, кворумы Raft/etcd, time ordering, Kafka delivery semantics, split-brain', status: 'active', link: '/distributed/' },
  { title: 'Безопасность (DevSecOps)', desc: 'Харденинг Linux, OWASP/WAF на edge, сканирование уязвимостей Trivy в CI, IAM least privilege, k8s security', status: 'active', link: '/security/' },
  { title: 'FinOps и оптимизация', desc: 'Экономика облаков, rightsizing подов по PromQL, автоскейлинг нод, spot-инстансы, OpenCost, Infracost', status: 'active', link: '/finops/' },
  { title: 'AI/MLOps-инфраструктура', desc: 'GPU в Kubernetes, сервинг LLM (vLLM, Ollama), LLM Gateway, pgvector для RAG, пайплайны MLflow', status: 'active', link: '/mlops/' },
  { title: 'Python для DevOps', desc: 'CLI утилиты, HTTP API, парсинг логов, infra SDK (boto3, k8s, docker), prometheus_client, pytest', status: 'active', link: '/python/' },
]

const topicsPractice = [
  { title: 'Пет-проект linkd-platform', desc: 'Сквозной боевой проект: код → Docker → CI/CD → Terraform+Ansible → K8s → ArgoCD → Observability → Vault → DR', status: 'active', link: '/project/' },
  { title: 'Карьера и техсобеседования', desc: 'Стратегия поиска, форматы техсобесов, live troubleshooting, System Design для DevOps, офферы', status: 'active', link: '/career/' },
  { title: 'Leadership: Senior → Lead', desc: 'Архитектурные решения (ADR), техдолг, система дежурств (on-call), найм инженеров, бюджет команды', status: 'active', link: '/leadership/' },
  { title: 'Soft Skills и рост до мида', desc: 'Матрица грейдов, деловая переписка, оценка сроков, работа с разработчиками и бизнесом, менторинг', status: 'active', link: '/softskills/' },
  { title: 'English для IT', desc: 'Чтение документации без словаря, профессиональный вокабуляр, переписка в PR/Issues, собеседования', status: 'active', link: '/english/' },
]
</script>

<div class="vp-doc" style="max-width: 688px; margin: 0 auto; padding: 0 24px;">

## 🧭 Дорожная карта: Базовый DevOps

<RoadmapChain :items="topicsBase" />

## 🔬 Специализации и Senior-трек

<RoadmapChain :items="topicsAdvanced" />

## 🚀 Практика, карьера и софт-скиллы

<RoadmapChain :items="topicsPractice" />

</div>
