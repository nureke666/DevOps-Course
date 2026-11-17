---
title: "1. Основы и метод"
description: "Требования и качества системы, оценки на салфетке, фреймворк ответа на 45 минут, бэкенд- и DevOps-собес, design doc и ADR"
---

<script setup>
import RoadmapChain from '../../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Что такое system design: требования, качества, SLO", "desc": "Функциональные и нефункциональные требования, качества системы, перцентили, SLI/SLO/SLA и как каждое качество обеспечивают бэкенд и эксплуатация", "status": "active", "link": "/system-design/basics/01-what-is-system-design"},
  {"title": "02. Оценки на салфетке: RPS, объём, трафик, задержки", "desc": "Степени двойки и десяти, таблица задержек, RPS из DAU и пик, хранение, полоса, память под кеш, число серверов, соединения, доступность и стоимость", "status": "active", "link": "/system-design/basics/02-estimations"},
  {"title": "03. Фреймворк ответа: 45 минут от уточнений до trade-offs", "desc": "Шаги и тайминг, уточняющие вопросы, API и модель данных, схема, deep dive, узкие места, как думать вслух и что ждут от middle и senior", "status": "active", "link": "/system-design/basics/03-interview-framework"},
  {"title": "04. Бэкенд-собес и DevOps-собес: две стороны одной схемы", "desc": "Чем отличаются задачи и ожидания, одна задача глазами бэкендера и девопса, стандартный блок «Эксплуатация» из 7 вопросов", "status": "active", "link": "/system-design/basics/04-backend-vs-devops"},
  {"title": "05. Design doc и ADR: как записать решение", "desc": "Зачем писать, структура design doc, варианты и trade-offs, ADR по шаблону, схемы C4, ревью дизайна и пример на linkd", "status": "active", "link": "/system-design/basics/05-design-doc-adr"},
]
</script>

# 1. Основы и метод

Фундамент курса: что спрашивают в system design, как переводить требования в числа, по каким
шагам строить ответ и как записать решение на работе.

> Блок → [System Design](/system-design/) → 1. Основы и метод. Начни отсюда: остальные блоки
> и все разборы задач опираются на фреймворк из темы 03 и блок «⚙️ Эксплуатация» из темы 04.

<RoadmapChain :items="lessons" />
