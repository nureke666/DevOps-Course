---
title: "Распределённые системы"
description: "CAP/PACELC, репликация, консенсус Raft в etcd, упорядочивание сообщений, семантики доставки Kafka, split-brain и outbox"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Основы: частичные отказы, задержки и 8 заблуждений о сети", "desc": "8 заблуждений о сети, частичные отказы, задержки и таймауты, детекторы отказов, gray failure", "status": "active", "link": "/distributed/01-fallacies-basics"},
  {"title": "02. Согласованность, CAP и PACELC", "desc": "Linearizable → eventual, read-your-writes, CAP без мифов, PACELC, где на этой шкале PG, etcd, Kafka, S3, Redis", "status": "active", "link": "/distributed/02-consistency-cap"},
  {"title": "03. Репликация и шардирование", "desc": "Leader/follower, multi-leader, leaderless и кворумы R+W>N, аномалии лага, hash/range/consistent hashing, ребалансировка", "status": "active", "link": "/distributed/03-replication-partitioning"},
  {"title": "04. Консенсус и кворум: Raft, etcd, Patroni, Ceph, corosync", "desc": "Raft (термы, выборы, лог), 2f+1, размер кластера etcd, learner, Patroni DCS, MON в Ceph, corosync; как кворум спасает от split brain", "status": "active", "link": "/distributed/04-consensus-quorum"},
  {"title": "05. Время и порядок событий: часы, логические часы, лизы и fencing-токены", "desc": "NTP/chrony и дрейф, монотонные часы, Lamport и векторные часы, HLC, лизы, fencing-токены, спор о Redlock", "status": "active", "link": "/distributed/05-time-ordering"},
  {"title": "06. Режимы отказов: split brain, retry storm, метастабильность, exactly-once и outbox", "desc": "Split brain и fencing/STONITH, retry storm и метастабильность, backpressure, идемпотентность, exactly-once и outbox, саги, Jepsen", "status": "active", "link": "/distributed/06-failure-modes"},
  {"title": "07. Практика: 6 лаб по распределённым системам", "desc": "6 лаб: etcd из 3 нод под отказами и разделением сети, failover Patroni и попытка split brain, дрейф часов, Kafka acks и min.insync.replicas, ретраи без идемпотентности, outbox", "status": "active", "link": "/distributed/07-practice-labs"},
  {"title": "08. Вопросы с собеседований: распределённые системы", "desc": "Главные вопросы с развёрнутыми ответами + ~40 коротких + ситуационные задачи", "status": "active", "link": "/distributed/08-interview"},
]
</script>

# Распределённые системы для DevOps

CAP/PACELC, репликация, консенсус Raft в etcd, упорядочивание сообщений, семантики доставки Kafka, split-brain и outbox

<RoadmapChain :items="lessons" />
