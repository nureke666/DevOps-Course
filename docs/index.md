---
layout: home
hero:
  name: "DevOps"
  text: "Конспекты и практика"
  tagline: "Личный учебный материал: Git, Linux, Сети, Docker, CI/CD, Ansible, Kubernetes"
  actions:
    - theme: brand
      text: Начать с Git
      link: /git/
---

<script setup>
import RoadmapChain from './.vitepress/theme/components/RoadmapChain.vue'

const topics = [
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
</script>

<div class="vp-doc" style="max-width: 688px; margin: 0 auto; padding: 0 24px;">

## Дорожная карта

<RoadmapChain :items="topics" />

</div>
