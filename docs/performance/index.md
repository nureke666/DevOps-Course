---
title: "Performance"
description: "Метод USE, чек-лист «60 секунд», flame graphs, OOM killer, I/O latency, TCP-очереди, strace, cgroups и eBPF"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Методология: USE, «60 секунд» и load average", "desc": "Метод вместо случайных команд, чтение vmstat/mpstat/iostat/sar, гипотеза → замер", "status": "active", "link": "/performance/01-methodology"},
  {"title": "02. CPU и память: perf, flame graphs, OOM killer", "desc": "perf, flame graphs, steal, RSS/PSS/USS, утечки, OOM killer, overcommit", "status": "active", "link": "/performance/02-cpu-memory"},
  {"title": "03. Диск и I/O: latency, page cache и «куда делось место»", "desc": "iostat -x по колонкам, fio, dirty pages, inodes, «диск полон, а файлов нет»", "status": "active", "link": "/performance/03-disk-io"},
  {"title": "04. Сеть глубже: очереди, TIMEWAIT, conntrack и дропы", "desc": "ss -ti, TIME_WAIT, SYN/accept queue, retransmits, conntrack, fd-утечки, дропы NIC", "status": "active", "link": "/performance/04-network-deep"},
  {"title": "05. strace и зависшие процессы", "desc": "strace -f -T -tt -c, D-state, /proc/PID/stack, зомби, gdb, py-spy", "status": "active", "link": "/performance/05-strace-hung-processes"},
  {"title": "06. cgroups v2 и контейнеры", "desc": "memory.events, cpu.stat и throttling, PSI, nsenter, kubectl debug", "status": "active", "link": "/performance/06-cgroups-containers"},
  {"title": "07. eBPF, bcc и bpftrace: вопросы прямо к ядру", "desc": "bcc-инструменты, one-liners bpftrace, экосистема (Cilium, Falco, Parca)", "status": "active", "link": "/performance/07-ebpf-bpftrace"},
  {"title": "08. Практика: 6 инцидентов на стенде", "desc": "6 инцидентов: CPU hog + flame graph, утечка до OOM, «диск полон, файлов нет», conntrack/порты, throttling в контейнере, D-state + strace", "status": "active", "link": "/performance/08-practice-labs"},
  {"title": "09. Вопросы с собеседований: траблшутинг и производительность Linux", "desc": "Главные вопросы с развёрнутыми ответами + 44 коротких + ситуационные задачи", "status": "active", "link": "/performance/09-interview"},
]
</script>

# Deep Linux Troubleshooting & Performance

Метод USE, чек-лист «60 секунд», flame graphs, OOM killer, I/O latency, TCP-очереди, strace, cgroups и eBPF

<RoadmapChain :items="lessons" />
