---
title: "SRE и Observability"
description: "SLI/SLO/SLA, Error Budget, burn-rate алерты, OpenTelemetry трейсинг, инцидент-менеджмент, постмортемы и отказоустойчивость"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Что такое SRE", "desc": "Блок → SRE и Observability → тема 01. Опирается на", "status": "active", "link": "/sre/01-sre-intro"}, {"title": "02. SLI, SLO и error budget", "desc": "Блок → SRE и Observability → тема 02. Продолжает", "status": "active", "link": "/sre/02-sli-slo-error-budget"}, {"title": "03. Трейсинг и OpenTelemetry", "desc": "Блок → SRE и Observability → тема 03. Три сигнала введены в", "status": "active", "link": "/sre/03-tracing-opentelemetry"}, {"title": "04. Инцидент-менеджмент и on-call", "desc": "Блок → SRE и Observability → тема 04. Алерты и маршрутизация — в", "status": "active", "link": "/sre/04-incident-management"}, {"title": "05. Постмортемы", "desc": "Блок → SRE и Observability → тема 05. Продолжает 04incidentmanagement.md", "status": "active", "link": "/sre/05-postmortems"}, {"title": "06. Паттерны надёжности, нагрузка и chaos engineering", "desc": "Блок → SRE и Observability → тема 06. Пробы и ресурсы в кубере — в", "status": "active", "link": "/sre/06-reliability-patterns"}, {"title": "07. Практика: 4 лабы по SRE и observability", "desc": "Блок → SRE и Observability → практика.", "status": "active", "link": "/sre/07-practice-labs"}, {"title": "08. Вопросы с собеседований: SRE и observability", "desc": "Блок → SRE и Observability → собеседование.", "status": "active", "link": "/sre/08-interview"}]
</script>

# SRE и Observability

SLI/SLO/SLA, Error Budget, burn-rate алерты, OpenTelemetry трейсинг, инцидент-менеджмент, постмортемы и отказоустойчивость

<RoadmapChain :items="lessons" />
