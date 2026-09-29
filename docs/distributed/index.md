---
title: "Распределённые системы"
description: "CAP/PACELC, репликация, консенсус Raft в etcd, упорядочивание сообщений, семантики доставки Kafka, split-brain и outbox"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Основы: частичные отказы, задержки и 8 заблуждений о сети", "desc": "Блок → Распределённые системы → тема 01. TCP, RST и таймауты подключения — в", "status": "active", "link": "/distributed/01-fallacies-basics"}, {"title": "02. Согласованность, CAP и PACELC", "desc": "Блок → Распределённые системы → тема 02. Реплики PostgreSQL и synchronouscommit — в", "status": "active", "link": "/distributed/02-consistency-cap"}, {"title": "03. Репликация и шардирование", "desc": "Блок → Распределённые системы → тема 03. Реплика PostgreSQL руками — в", "status": "active", "link": "/distributed/03-replication-partitioning"}, {"title": "04. Консенсус и кворум: Raft, etcd, Patroni, Ceph, corosync", "desc": "Блок → Распределённые системы → тема 04. etcd в Kubernetes — в", "status": "active", "link": "/distributed/04-consensus-quorum"}, {"title": "05. Время и порядок событий: часы, логические часы, лизы и fencing-токены", "desc": "Блок → Распределённые системы → тема 05. Heartbeat и лизы как детектор отказов — в", "status": "active", "link": "/distributed/05-time-ordering"}, {"title": "06. Режимы отказов: split brain, retry storm, метастабильность, exactly-once и outbox", "desc": "Блок → Распределённые системы → тема 06. Базовые ретраи, backoff, circuit breaker, bulkhead", "status": "active", "link": "/distributed/06-failure-modes"}, {"title": "07. Практика: 6 лаб по распределённым системам", "desc": "Блок → Распределённые системы → практика. Лабы делаются руками в ~/labs/distributed/", "status": "active", "link": "/distributed/07-practice-labs"}, {"title": "08. Вопросы с собеседований: распределённые системы", "desc": "Блок → Распределённые системы → собеседование.", "status": "active", "link": "/distributed/08-interview"}]
</script>

# Распределённые системы для DevOps

CAP/PACELC, репликация, консенсус Raft в etcd, упорядочивание сообщений, семантики доставки Kafka, split-brain и outbox

<RoadmapChain :items="lessons" />
