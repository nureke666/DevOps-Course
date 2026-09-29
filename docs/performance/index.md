---
title: "Performance"
description: "Метод USE, чек-лист «60 секунд», flame graphs, OOM killer, I/O latency, TCP-очереди, strace, cgroups и eBPF"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Методология: USE, «60 секунд» и load average", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 01. Опирается на", "status": "active", "link": "/performance/01-methodology"}, {"title": "02. CPU и память: perf, flame graphs, OOM killer", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 02. Опирается на", "status": "active", "link": "/performance/02-cpu-memory"}, {"title": "03. Диск и I/O: latency, page cache и «куда делось место»", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 03. Опирается на", "status": "active", "link": "/performance/03-disk-io"}, {"title": "04. Сеть глубже: очереди, TIMEWAIT, conntrack и дропы", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 04. Опирается на", "status": "active", "link": "/performance/04-network-deep"}, {"title": "05. strace и зависшие процессы", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 05. Опирается на", "status": "active", "link": "/performance/05-strace-hung-processes"}, {"title": "06. cgroups v2 и контейнеры", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 06. Опирается на", "status": "active", "link": "/performance/06-cgroups-containers"}, {"title": "07. eBPF, bcc и bpftrace: вопросы прямо к ядру", "desc": "Блок → Deep Linux Troubleshooting & Performance → тема 07. Опирается на", "status": "active", "link": "/performance/07-ebpf-bpftrace"}, {"title": "08. Практика: 6 инцидентов на стенде", "desc": "Блок → Deep Linux Troubleshooting & Performance → практика.", "status": "active", "link": "/performance/08-practice-labs"}, {"title": "09. Вопросы с собеседований: траблшутинг и производительность Linux", "desc": "Блок → Deep Linux Troubleshooting & Performance → собеседование.", "status": "active", "link": "/performance/09-interview"}]
</script>

# Deep Linux Troubleshooting & Performance

Метод USE, чек-лист «60 секунд», flame graphs, OOM killer, I/O latency, TCP-очереди, strace, cgroups и eBPF

<RoadmapChain :items="lessons" />
