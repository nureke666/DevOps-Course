---
title: "ArgoCD"
description: "Курс по GitOps и ArgoCD: принципы GitOps, установка, Application, App of Apps, Helm/Kustomize, практика и собеседования"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Принципы GitOps', desc: 'Четыре принципа GitOps, push vs pull, Argo CD vs Flux, границы с Terraform', status: 'active', link: '/argocd/01-gitops-concepts' },
  { title: '02. Установка и устройство ArgoCD', desc: 'Компоненты, установка, доступ к UI, репозитории и кластеры, AppProject, RBAC', status: 'active', link: '/argocd/02-argocd-install' },
  { title: '03. Application: синхронизация и здоровье', desc: 'Sync- и health-статусы, automated/prune/selfHeal, sync waves и hooks, откаты', status: 'active', link: '/argocd/03-application' },
  { title: '04. App of Apps и ApplicationSet', desc: 'Паттерн App of Apps, генераторы ApplicationSet, структура репозитория, бутстрап кластера', status: 'active', link: '/argocd/04-app-of-apps' },
  { title: '05. Helm, Kustomize и секреты', desc: 'Деплой Helm-чартов и Kustomize через ArgoCD, multi-source, секреты (SOPS, Sealed Secrets, ESO)', status: 'active', link: '/argocd/05-helm-kustomize' },
  { title: '06. Практика: 4 лабы', desc: 'Установка и первое приложение, self-heal/prune/откаты, App of Apps, Helm-чарты и секреты', status: 'active', link: '/argocd/06-practice-labs' },
  { title: '07. Вопросы с собеседований', desc: 'Шесть главных вопросов и 30 дополнительных по GitOps и ArgoCD', status: 'active', link: '/argocd/07-interview' },
]
</script>

# ArgoCD

От принципов GitOps до установки ArgoCD, Application, App of Apps, Helm/Kustomize и секретов в проде.

<RoadmapChain :items="lessons" />
