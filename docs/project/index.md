---
title: "Пет-проект linkd"
description: "Сквозной боевой проект: сервис, Docker, GitLab CI, Terraform, Ansible, Kubernetes, ArgoCD, Prometheus, Vault и DR"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Приложение: linkd 2.0 и контракт с платформой", "desc": "контракт сервиса с платформой, свой код на Python", "status": "active", "link": "/project/01-app"},
  {"title": "02. Контейнеризация: образ и локальный стенд", "desc": "образ, compose-стенд с PostgreSQL", "status": "active", "link": "/project/02-docker"},
  {"title": "03. CI: от коммита до образа в registry и коммита в gitops", "desc": "живой пайплайн, registry, коммит в gitops", "status": "active", "link": "/project/03-ci"},
  {"title": "04. Инфраструктура: Terraform, Ansible и кластер одной командой", "desc": "IaC: Terraform + Ansible, два трека деплоя", "status": "active", "link": "/project/04-infra-terraform-ansible"},
  {"title": "05. Kubernetes и Helm: чарт linkd 2.0 и данные в кластере", "desc": "чарт под linkd 2.0, dev/prod, данные отдельно", "status": "active", "link": "/project/05-kubernetes-helm"},
  {"title": "06. GitOps: Argo CD собирает кластер из linkd-gitops", "desc": "app-of-apps, CI → gitops → кластер, откат", "status": "active", "link": "/project/06-gitops-argocd"},
  {"title": "07. Наблюдаемость: метрики, логи, трейсы и алерты по SLO", "desc": "SLO, алерты с тестами, логи, трейсы", "status": "active", "link": "/project/07-observability"},
  {"title": "08. Секреты и безопасность", "desc": "Vault + ESO, инвентаризация секретов", "status": "active", "link": "/project/08-secrets-security"},
  {"title": "09. Бэкапы и восстановление (DR)", "desc": "бэкап вне кластера, учения, RPO/RTO", "status": "active", "link": "/project/09-backup-dr"},
  {"title": "10. Оформление: README, ADR, резюме, рассказ на собесе", "desc": "README, ADR, строки резюме, рассказ", "status": "active", "link": "/project/10-readme-resume"},
  {"title": "11. Финальный прогон, демо и развитие", "desc": "сквозное демо, запись, план расширений", "status": "active", "link": "/project/11-demo-and-next"},
]
</script>

# linkd-platform — портфолио из проектов практики

Сквозной боевой проект: сервис, Docker, GitLab CI, Terraform, Ansible, Kubernetes, ArgoCD, Prometheus, Vault и DR

<RoadmapChain :items="lessons" />
