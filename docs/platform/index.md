---
title: "Platform Engineering"
description: "Платформа как продукт: CRD и kopf операторы, Kyverno/VAP политики, Service Mesh, Argo Rollouts, Crossplane и Backstage"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Platform Engineering: платформа как продукт", "desc": "Блок → Platform Engineering → тема 01. Вопросы собеса: «Что такое внутренняя платформа", "status": "active", "link": "/platform/01-platform-engineering"}, {"title": "02. CRD и операторы: API платформы и паттерн контроллера", "desc": "Блок → Platform Engineering → тема 02. Вопросы собеса: «Что такое оператор?»,", "status": "active", "link": "/platform/02-crd-operators"}, {"title": "03. Свой оператор на Python: kopf и LinkdApp", "desc": "Блок → Platform Engineering → тема 03. Вопросы собеса: «Писали ли вы оператор?»,", "status": "active", "link": "/platform/03-writing-operator"}, {"title": "04. Admission и политики: ограждения, а не шлагбаумы", "desc": "Блок → Platform Engineering → тема 04. Вопросы собеса: «Чем ValidatingAdmissionPolicy", "status": "active", "link": "/platform/04-admission-policy"}, {"title": "05. Gateway API глубже и service mesh", "desc": "Блок → Platform Engineering → трафик. Основы Gateway API (GatewayClass → Gateway →", "status": "active", "link": "/platform/05-gateway-mesh"}, {"title": "06. Progressive delivery: Argo Rollouts, анализ метрик, feature flags", "desc": "Блок → Platform Engineering → безопасная выкатка. Стратегии (rolling, blue-green, canary)", "status": "active", "link": "/platform/06-progressive-delivery"}, {"title": "07. Самообслуживание: Crossplane", "desc": "Блок → Platform Engineering → инфраструктура по запросу. Terraform, стейт и модули —", "status": "active", "link": "/platform/07-crossplane-self-service"}, {"title": "08. Портал разработчика: Backstage", "desc": "Блок → Platform Engineering → единая точка входа. Зачем портал и как мерить платформу —", "status": "active", "link": "/platform/08-backstage"}, {"title": "09. Практика: мини-платформа в kind", "desc": "Блок → Platform Engineering → практика. Шесть лаб собирают из тем 01–08 одну платформу:", "status": "active", "link": "/platform/09-practice-labs"}, {"title": "10. Вопросы с собеседований: Platform Engineering", "desc": "Блок → Platform Engineering → собеседование.", "status": "active", "link": "/platform/10-interview"}]
</script>

# Platform Engineering

Платформа как продукт: CRD и kopf операторы, Kyverno/VAP политики, Service Mesh, Argo Rollouts, Crossplane и Backstage

<RoadmapChain :items="lessons" />
