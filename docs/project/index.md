---
title: "Пет-проект linkd"
description: "Сквозной боевой проект: сервис, Docker, GitLab CI, Terraform, Ansible, Kubernetes, ArgoCD, Prometheus, Vault и DR"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Приложение: linkd 2.0 и контракт с платформой", "desc": "Цель этапа: положить в linkd-platform сервис linkd 2.0 и собственные утилиты вокруг", "status": "active", "link": "/project/01-app"}, {"title": "02. Контейнеризация: образ и локальный стенд", "desc": "Цель этапа: перенести образ из 04-shipyard в портфолио, довести его до linkd 2.0", "status": "active", "link": "/project/02-docker"}, {"title": "03. CI: от коммита до образа в registry и коммита в gitops", "desc": "Цель этапа: пайплайн из 05-conveyor начинает работать по-настоящему на gitlab.com:", "status": "active", "link": "/project/03-ci"}, {"title": "04. Инфраструктура: Terraform, Ansible и кластер одной командой", "desc": "Цель этапа: собрать в infra/ результаты 11-blueprint (Terraform) и 06-fleet", "status": "active", "link": "/project/04-infra-terraform-ansible"}, {"title": "05. Kubernetes и Helm: чарт linkd 2.0 и данные в кластере", "desc": "Цель этапа: перенести чарт из 07-orbit в портфолио, довести его до linkd 2.0", "status": "active", "link": "/project/05-kubernetes-helm"}, {"title": "06. GitOps: Argo CD собирает кластер из linkd-gitops", "desc": "Цель этапа: перенести app-of-apps из 12-autopilot на публичный linkd-gitops,", "status": "active", "link": "/project/06-gitops-argocd"}, {"title": "07. Наблюдаемость: метрики, логи, трейсы и алерты по SLO", "desc": "Цель этапа: собрать в портфолио результаты 08-observatory и 14-pulse так, чтобы", "status": "active", "link": "/project/07-observability"}, {"title": "08. Секреты и безопасность", "desc": "Цель этапа: убрать из портфолио последние ручные kubectl create secret, свести", "status": "active", "link": "/project/08-secrets-security"}, {"title": "09. Бэкапы и восстановление (DR)", "desc": "Цель этапа: связать три проекта в одну защиту данных: что и как бэкапить —", "status": "active", "link": "/project/09-backup-dr"}, {"title": "10. Оформление: README, ADR, резюме, рассказ на собесе", "desc": "Цель этапа: упаковать linkd-platform так, чтобы рекрутеру хватило 30 секунд,", "status": "active", "link": "/project/10-readme-resume"}, {"title": "11. Финальный прогон, демо и развитие", "desc": "Цель этапа: доказать, что портфолио работает целиком и без подсказок: один", "status": "active", "link": "/project/11-demo-and-next"}]
</script>

# linkd-platform — портфолио из проектов практики

Сквозной боевой проект: сервис, Docker, GitLab CI, Terraform, Ansible, Kubernetes, ArgoCD, Prometheus, Vault и DR

<RoadmapChain :items="lessons" />
