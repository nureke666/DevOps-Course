---
title: "Очереди"
description: "Курс по очередям сообщений: основы асинхронности, Kafka, RabbitMQ, практика и вопросы с собеседований"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Основы очередей сообщений', desc: 'Синхронность vs асинхронность, гарантии доставки, идемпотентность, DLQ, backpressure', status: 'active', link: '/queues/01-queues-concepts' },
  { title: '02. Kafka: концепции', desc: 'Брокер, топик, партиции, оффсеты, продюсеры, консьюмеры, консьюмер-группы, репликация', status: 'active', link: '/queues/02-kafka-basics' },
  { title: '03. Kafka: эксплуатация', desc: 'Поднять кластер, CLI для топиков и групп, лаг, мониторинг, безопасность, инциденты', status: 'active', link: '/queues/03-kafka-ops' },
  { title: '04. RabbitMQ', desc: 'Exchange, binding, очереди, ack и prefetch, DLX, кластер, quorum queues, сравнение с Kafka', status: 'active', link: '/queues/04-rabbitmq' },
  { title: '05. Практика: 4 лабы', desc: 'Kafka руками, консьюмер-группы и лаг, RabbitMQ маршрутизация, мониторинг и инциденты', status: 'active', link: '/queues/05-practice-labs' },
  { title: '06. Вопросы с собеседований', desc: 'Семь главных вопросов и 35 дополнительных по Kafka и RabbitMQ', status: 'active', link: '/queues/06-interview' },
]
</script>

# Очереди

От асинхронного взаимодействия и гарантий доставки до Kafka, RabbitMQ и разбора
типовых инцидентов брокеров сообщений.

<RoadmapChain :items="lessons" />
