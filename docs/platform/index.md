---
title: "Platform Engineering"
description: "Платформа как продукт: CRD и kopf операторы, Kyverno/VAP политики, Service Mesh, Argo Rollouts, Crossplane и Backstage"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Platform Engineering: платформа как продукт", "desc": "IDP, golden path, платформа как продукт, Team Topologies, метрики DevEx и DORA, когда платформа не нужна", "status": "active", "link": "/platform/01-platform-engineering"},
  {"title": "02. CRD и операторы: API платформы и паттерн контроллера", "desc": "Схема и валидация CRD (OpenAPI, CEL), status, версии, паттерн контроллера, owner references, финализаторы, готовые операторы", "status": "active", "link": "/platform/02-crd-operators"},
  {"title": "03. Свой оператор на Python: kopf и LinkdApp", "desc": "kopf: CRD LinkdApp → Deployment + Service + HTTPRoute, reconcile, статус, идемпотентность, RBAC и деплой оператора, тесты; как устроен kubebuilder", "status": "active", "link": "/platform/03-writing-operator"},
  {"title": "04. Admission и политики: ограждения, а не шлагбаумы", "desc": "Validating и mutating webhook на Python, ValidatingAdmissionPolicy на CEL, Kyverno со стороны платформы, failurePolicy и как не положить кластер", "status": "active", "link": "/platform/04-admission-policy"},
  {"title": "05. Gateway API глубже и service mesh", "desc": "Мультитенантный Gateway API, ReferenceGrant, policy attachment, GRPCRoute, mesh руками: mTLS, трафик, наблюдаемость; когда mesh не нужен", "status": "active", "link": "/platform/05-gateway-mesh"},
  {"title": "06. Progressive delivery: Argo Rollouts, анализ метрик, feature flags", "desc": "Argo Rollouts: canary и blue-green, AnalysisTemplate на Prometheus, трафик через Gateway API, автооткат; Flagger; feature flags", "status": "active", "link": "/platform/06-progressive-delivery"},
  {"title": "07. Самообслуживание: Crossplane", "desc": "Crossplane v2: providers, XRD, Composition с functions, namespaced XR (Claims больше нет); Crossplane vs Terraform; «база по запросу» для команды", "status": "active", "link": "/platform/07-crossplane-self-service"},
  {"title": "08. Портал разработчика: Backstage", "desc": "Каталог и catalog-info.yaml, шаблоны (scaffolder), TechDocs, плагины, внедрение и метрики использования", "status": "active", "link": "/platform/08-backstage"},
  {"title": "09. Практика: мини-платформа в kind", "desc": "6 лаб — мини-платформа в kind: оператор LinkdApp, guardrails, canary с анализом, «база по запросу» через Crossplane, шаблон Backstage → репозиторий → ArgoCD, итоговый golden path", "status": "active", "link": "/platform/09-practice-labs"},
  {"title": "10. Вопросы с собеседований: Platform Engineering", "desc": "Главные вопросы с развёрнутыми ответами + ~40 коротких + ситуационные задачи", "status": "active", "link": "/platform/10-interview"},
]
</script>

# Platform Engineering

Платформа как продукт: CRD и kopf операторы, Kyverno/VAP политики, Service Mesh, Argo Rollouts, Crossplane и Backstage

<RoadmapChain :items="lessons" />
