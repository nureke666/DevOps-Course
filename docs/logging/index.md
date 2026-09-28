---
title: "Логирование"
description: "Курс по логированию: основы, ELK, Loki + Grafana, сборщики логов, OpenTelemetry и Vector"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Основы логирования', desc: 'Путь лога от приложения до инженера, уровни, структурные логи, объём и retention', status: 'active', link: '/logging/01-logging-concepts' },
  { title: '02. ELK: Elasticsearch, Logstash, Kibana', desc: 'Роли компонентов, модель данных, Filebeat, Logstash/grok, ILM, эксплуатация', status: 'active', link: '/logging/02-elk-stack' },
  { title: '03. Loki + Grafana', desc: 'Модель лейблов Loki, Grafana Alloy, LogQL, алерты по логам, Loki vs ELK', status: 'active', link: '/logging/03-loki-grafana' },
  { title: '04. Сборщики логов', desc: 'Fluentd, Fluent Bit, Filebeat, Grafana Alloy, Vector — сравнение и конвейер', status: 'active', link: '/logging/04-collectors' },
  { title: '05. Источники логов', desc: 'journald и файлы Linux, Docker, Kubernetes, nginx, базы, аудит', status: 'active', link: '/logging/05-log-sources' },
  { title: '06. Практика: 5 лаб', desc: 'Loki + Alloy, ELK руками, парсинг и маскирование, алерты, OTel-логи и Vector', status: 'active', link: '/logging/06-practice-labs' },
  { title: '07. Вопросы с собеседований', desc: 'Шесть главных вопросов и 38 дополнительных по всем темам блока', status: 'active', link: '/logging/07-interview' },
  { title: '08. OpenTelemetry и Vector', desc: 'Модель LogRecord, логи по OTLP, Alloy как дистрибутив OTel Collector, Vector и VRL', status: 'active', link: '/logging/08-otel-logs-vector' },
]
</script>

# Логирование

От основ и ELK до Loki, современных сборщиков и логов через OpenTelemetry.

<RoadmapChain :items="lessons" />
