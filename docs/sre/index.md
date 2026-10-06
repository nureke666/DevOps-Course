---
title: "SRE и Observability"
description: "SLI/SLO/SLA, Error Budget, burn-rate алерты, OpenTelemetry трейсинг, инцидент-менеджмент, постмортемы и отказоустойчивость"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Что такое SRE", "desc": "SRE vs DevOps vs Platform, toil, принципы, error budget как договор", "status": "active", "link": "/sre/01-sre-intro"},
  {"title": "02. SLI, SLO и error budget", "desc": "Выбор SLI, расчёт бюджета, multi-window multi-burn-rate алерты", "status": "active", "link": "/sre/02-sli-slo-error-budget"},
  {"title": "03. Трейсинг и OpenTelemetry", "desc": "Span/trace, traceparent, sampling, OTel Collector, Tempo, exemplars", "status": "active", "link": "/sre/03-tracing-opentelemetry"},
  {"title": "04. Инцидент-менеджмент и on-call", "desc": "SEV1–4, роли, жизненный цикл, runbook, on-call", "status": "active", "link": "/sre/04-incident-management"},
  {"title": "05. Постмортемы", "desc": "Blameless, шаблон, contributing factors, action items", "status": "active", "link": "/sre/05-postmortems"},
  {"title": "06. Паттерны надёжности, нагрузка и chaos engineering", "desc": "Таймауты, ретраи с jitter, circuit breaker, k6, chaos engineering", "status": "active", "link": "/sre/06-reliability-patterns"},
  {"title": "07. Практика: 4 лабы по SRE и observability", "desc": "4 лабы: трейсинг на стенде, SLO с burn-rate, нагрузка k6, game day + постмортем", "status": "active", "link": "/sre/07-practice-labs"},
  {"title": "08. Вопросы с собеседований: SRE и observability", "desc": "Главные вопросы с развёрнутыми ответами + ~40 коротких + ситуационные задачи", "status": "active", "link": "/sre/08-interview"},
]
</script>

# SRE и Observability

SLI/SLO/SLA, Error Budget, burn-rate алерты, OpenTelemetry трейсинг, инцидент-менеджмент, постмортемы и отказоустойчивость

<RoadmapChain :items="lessons" />
