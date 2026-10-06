---
title: "FinOps"
description: "Экономика облаков, rightsizing подов по PromQL, автоскейлинг нод, spot-инстансы, OpenCost/Kubecost и Infracost в CI"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Что такое FinOps и как устроены деньги в облаке", "desc": "Фреймворк (фазы, принципы, роли), модель счёта, резервы/spot, юнит-экономика, теги, showback, бюджеты, TCO", "status": "active", "link": "/finops/01-finops-intro"},
  {"title": "02. Rightsizing в Kubernetes: requests, limits и реальное потребление", "desc": "Requests = деньги, PromQL p95/пик за 14 дней, CPU limits, VPA и in-place resize, guardrails, bin packing", "status": "active", "link": "/finops/02-k8s-rightsizing"},
  {"title": "03. Автоскейлинг как инструмент экономии: HPA, KEDA, ноды, spot, расписания", "desc": "Пол и цель HPA, KEDA и scale to zero, CA vs Karpenter, spot, non-prod по расписанию, размер нод", "status": "active", "link": "/finops/03-autoscaling-cost"},
  {"title": "04. OpenCost и Kubecost: сколько стоит каждый namespace", "desc": "Allocation-модель, custom pricing, API и kubectl cost, idle и общие расходы, Grafana, алерты, showback", "status": "active", "link": "/finops/04-kubecost-opencost"},
  {"title": "05. FinOps в инфраструктурном коде: Infracost, теги, бюджеты, чистка", "desc": "Infracost v0.10/v2 в MR, conftest-политики, default_tags + tflint, бюджеты, сироты, lifecycle, cost review", "status": "active", "link": "/finops/05-infracost-iac"},
  {"title": "06. Практика: 5 лаб по FinOps", "desc": "5 лаб: rightsizing с таблицей «до/после», OpenCost + showback, dev спит ночью (KEDA), Infracost в MR + политики, cost review счёта", "status": "active", "link": "/finops/06-practice-labs"},
  {"title": "07. Вопросы с собеседований: FinOps и оптимизация ресурсов", "desc": "10 главных вопросов с развёрнутыми ответами + 38 коротких + ситуационные задачи", "status": "active", "link": "/finops/07-interview"},
]
</script>

# FinOps и оптимизация ресурсов

Экономика облаков, rightsizing подов по PromQL, автоскейлинг нод, spot-инстансы, OpenCost/Kubecost и Infracost в CI

<RoadmapChain :items="lessons" />
