---
title: "Leadership"
description: "Архитектурные решения (ADR), техдолг, проектирование on-call дежурств, найм, бюджет команды и выбор трека роста"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. От мидла к сеньору", "desc": "Признаки сеньора, scope и ownership системы, glue work, ловушки героя и бутылочного горлышка, promo-пакет", "status": "active", "link": "/leadership/01-middle-to-senior"},
  {"title": "02. Архитектурные решения: ADR, RFC, design review", "desc": "ADR, RFC-процесс, design review своих и чужих доков, trade-offs, обратимые и необратимые решения, pre-mortem", "status": "active", "link": "/leadership/02-architecture-decisions"},
  {"title": "03. Техническая стратегия платформы", "desc": "Roadmap платформы, реестр техдолга, build vs buy vs managed, миграции и deprecation, стандарты и tech radar", "status": "active", "link": "/leadership/03-tech-strategy"},
  {"title": "04. Дежурства как система", "desc": "Дизайн ротации, handoff, нагрузка и метрики, гигиена алертов, эскалации, онбординг в дежурство, компенсация", "status": "active", "link": "/leadership/04-oncall-as-system"},
  {"title": "05. Найм и собеседования: сторона команды", "desc": "Профиль роли и вакансия, структура интервью, scorecard, калибровка, bias, дебриф, онбординг новичка", "status": "active", "link": "/leadership/05-hiring-interviewing"},
  {"title": "06. Команда, план и бюджет", "desc": "Ёмкость и план квартала, KTLO vs развитие, приоритизация, бюджет и вендоры, headcount, отчёт руководству", "status": "active", "link": "/leadership/06-team-and-budget"},
  {"title": "07. Tech lead, staff, engineering manager: что после сеньора", "desc": "Три трека после сеньора, архетипы staff, неделя каждой роли, делегирование, сложные разговоры, как выбрать и вернуться", "status": "active", "link": "/leadership/07-lead-staff-em"},
  {"title": "08. Практика: 7 лаб на работе и в linkd-platform", "desc": "7 лаб на работе и в linkd-platform: ADR + design review, реестр долга и roadmap, аудит алертов и дизайн ротации, интервью со scorecard, план квартала, promo-пакет, выбор трека", "status": "active", "link": "/leadership/08-practice-labs"},
  {"title": "09. Собеседование на senior / lead DevOps", "desc": "Чем senior-собес отличается, главные вопросы с развёрнутыми ответами, ~40 коротких, ситуационные задачи, вопросы работодателю", "status": "active", "link": "/leadership/09-interview"},
]
</script>

# Leadership: middle → senior → lead / staff

Архитектурные решения (ADR), техдолг, проектирование on-call дежурств, найм, бюджет команды и выбор трека роста

<RoadmapChain :items="lessons" />
