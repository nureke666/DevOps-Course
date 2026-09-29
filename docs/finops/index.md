---
title: "FinOps"
description: "Экономика облаков, rightsizing подов по PromQL, автоскейлинг нод, spot-инстансы, OpenCost/Kubecost и Infracost в CI"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Что такое FinOps и как устроены деньги в облаке", "desc": "Блок → FinOps и оптимизация ресурсов → тема 01. Опирается на", "status": "active", "link": "/finops/01-finops-intro"}, {"title": "02. Rightsizing в Kubernetes: requests, limits и реальное потребление", "desc": "Блок → FinOps → тема 02. Опирается на", "status": "active", "link": "/finops/02-k8s-rightsizing"}, {"title": "03. Автоскейлинг как инструмент экономии: HPA, KEDA, ноды, spot, расписания", "desc": "Блок → FinOps → тема 03. Опирается на", "status": "active", "link": "/finops/03-autoscaling-cost"}, {"title": "04. OpenCost и Kubecost: сколько стоит каждый namespace", "desc": "Блок → FinOps → тема 04. Опирается на", "status": "active", "link": "/finops/04-kubecost-opencost"}, {"title": "05. FinOps в инфраструктурном коде: Infracost, теги, бюджеты, чистка", "desc": "Блок → FinOps → тема 05. Опирается на", "status": "active", "link": "/finops/05-infracost-iac"}, {"title": "06. Практика: 5 лаб по FinOps", "desc": "Блок → FinOps и оптимизация ресурсов → практика.", "status": "active", "link": "/finops/06-practice-labs"}, {"title": "07. Вопросы с собеседований: FinOps и оптимизация ресурсов", "desc": "Блок → FinOps и оптимизация ресурсов → собеседование.", "status": "active", "link": "/finops/07-interview"}]
</script>

# FinOps и оптимизация ресурсов

Экономика облаков, rightsizing подов по PromQL, автоскейлинг нод, spot-инстансы, OpenCost/Kubecost и Infracost в CI

<RoadmapChain :items="lessons" />
