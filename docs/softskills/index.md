---
title: "Soft Skills"
description: "Матрица грейдов, деловая письменная коммуникация, оценка сроков, работа с разработчиками и бизнесом, менторство"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Грейды и рост: junior → middle → senior → lead", "desc": "Оси роста, матрица грейдов, самооценка, 1:1, разговор о повышении, T-shaped", "status": "active", "link": "/softskills/01-grades-growth"},
  {"title": "02. Письменная коммуникация", "desc": "BLUF, сообщения в чат, тикеты, статус-апдейты, design doc, документация", "status": "active", "link": "/softskills/02-written-communication"},
  {"title": "03. Как спрашивать и учиться в команде", "desc": "Таймбокс и шаблон вопроса, XY-проблема, онбординг, фидбек, work log", "status": "active", "link": "/softskills/03-asking-learning"},
  {"title": "04. Сроки, приоритеты и ожидания", "desc": "Декомпозиция, оценка диапазоном, раннее «не успеваю», «нет, но…», прерывания", "status": "active", "link": "/softskills/04-estimation-priorities"},
  {"title": "05. Работа с разработчиками и бизнесом", "desc": "DevOps как сервис, paved road, язык бизнеса, как предлагать и отказывать, конфликты", "status": "active", "link": "/softskills/05-devs-and-business"},
  {"title": "06. Ошибки, давление и выгорание", "desc": "«Я сломал прод», признание ошибки, blameless, границы, выгорание", "status": "active", "link": "/softskills/06-mistakes-pressure"},
  {"title": "07. Ревью, фидбек и менторство: путь к сеньору", "desc": "Тон ревью, SBI, объяснять просто, демо, менторство, влияние без полномочий", "status": "active", "link": "/softskills/07-review-mentoring"},
  {"title": "08. Практика: 7 лаб на реальной работе", "desc": "7 лаб на 4 недели: work log, письмо, журнал оценок, 1:1 и план, design doc, демо, тренировочный собес", "status": "active", "link": "/softskills/08-practice-labs"},
  {"title": "09. Behavioral-собеседование: STAR, истории, мотивация", "desc": "STAR, банк историй, «расскажи о себе», переход из бэкенда, 10 главных вопросов, ~30 коротких, вопросы работодателю", "status": "active", "link": "/softskills/09-interview"},
]
</script>

# Soft skills: рост от джуна до мида

Матрица грейдов, деловая письменная коммуникация, оценка сроков, работа с разработчиками и бизнесом, менторство

<RoadmapChain :items="lessons" />
