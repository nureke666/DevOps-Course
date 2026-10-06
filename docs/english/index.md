---
title: "English для IT"
description: "Чтение документации без словаря, профессиональный вокабуляр, переписка в PR/Issues, стендапы и собеседования"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Уровень и система: как учить английский для IT", "desc": "CEFR для IT, самооценка, система 20–30 мин/день, Anki, что переключить на английский, ИИ как репетитор", "status": "active", "link": "/english/01-level-and-system"},
  {"title": "02. Чтение документации, ошибок и issues", "desc": "Skim / scan / intensive, структура доков, deprecated, as of, opt-in, MUST/SHOULD/MAY, changelog, ошибки и stack trace", "status": "active", "link": "/english/02-reading-docs"},
  {"title": "03. Лексика: глоссарий DevOps, фразовые глаголы, ложные друзья, произношение", "desc": "Глоссарий по областям, фразовые глаголы, setup / set up, ложные друзья, произношение nginx, etcd, cache", "status": "active", "link": "/english/03-vocabulary"},
  {"title": "04. Письмо: коммиты, MR, issues, чат, апдейты инцидентов", "desc": "Коммиты, MR, ответы на ревью, issue, чат, апдейт инцидента, письма; артикли, Present Perfect, тон", "status": "active", "link": "/english/04-writing"},
  {"title": "05. Речь: стендап, созвоны, переспрос, демо", "desc": "Стендап, объяснить проблему, переспрос, несогласие, созвоны, демо, произношение, shadowing", "status": "active", "link": "/english/05-speaking"},
  {"title": "06. Практика: 30 дней английского для IT", "desc": "План по дням на 4 недели, 5 лаб: чтение и слова, письмо, речь, инцидент на английском, тренировочное интервью", "status": "active", "link": "/english/06-practice-labs"},
  {"title": "07. Собеседование на английском для DevOps-позиции", "desc": "«Tell me about yourself», STAR по-английски, URL / Kubernetes / контейнер vs ВМ, думать вслух, ~35 вопросов с ответами, вопросы работодателю", "status": "active", "link": "/english/07-interview"},
]
</script>

# Английский для DevOps-инженера

Чтение документации без словаря, профессиональный вокабуляр, переписка в PR/Issues, стендапы и собеседования

<RoadmapChain :items="lessons" />
