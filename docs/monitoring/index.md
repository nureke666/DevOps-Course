---
title: "Мониторинг"
description: "Курс по мониторингу: Prometheus, PromQL, Alertmanager, Grafana, Zabbix, долгое хранение метрик"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Основы мониторинга', desc: 'Метрики, логи и трейсы, pull vs push, кардинальность, SLI/SLO/SLA, error budget', status: 'active', link: '/monitoring/01-monitoring-concepts' },
  { title: '02. Prometheus: архитектура и сбор', desc: 'Устройство Prometheus, prometheus.yml, service discovery, relabeling, TSDB и retention', status: 'active', link: '/monitoring/02-prometheus-basics' },
  { title: '03. Типы метрик и PromQL', desc: 'Counter, gauge, histogram, summary; rate/irate/increase, агрегация, перцентили', status: 'active', link: '/monitoring/03-promql' },
  { title: "04. Exporter'ы", desc: 'Карта основных экспортеров, node_exporter, cAdvisor, blackbox_exporter, инструментирование', status: 'active', link: '/monitoring/04-exporters' },
  { title: '05. Алерты и Alertmanager', desc: 'Правило алерта, жизненный цикл, маршрутизация, группировка, inhibit, silence', status: 'active', link: '/monitoring/05-alertmanager' },
  { title: '06. Grafana', desc: 'Data sources, панели, переменные дашборда, provisioning как код, Explore', status: 'active', link: '/monitoring/06-grafana' },
  { title: '07. Что мониторить: 4 сигнала, USE, RED, SLO', desc: 'RED и USE методы, четыре золотых сигнала, переход от SLO к порогам алертов', status: 'active', link: '/monitoring/07-what-to-monitor' },
  { title: '08. Практика: 6 лаб', desc: 'Стек Prometheus + Grafana с нуля, RED-дашборд, алерты в телеграм, мониторинг в Kubernetes', status: 'active', link: '/monitoring/08-practice-labs' },
  { title: '09. Вопросы с собеседований', desc: '8 главных вопросов и 49 дополнительных по темам блока', status: 'active', link: '/monitoring/09-interview' },
  { title: '10. Zabbix', desc: 'Классический мониторинг инфраструктуры: passive/active, триггеры, discovery, proxy', status: 'active', link: '/monitoring/10-zabbix' },
  { title: '11. Долгое хранение и Operator', desc: 'remote_write, VictoriaMetrics/Thanos/Mimir, kube-prometheus-stack, ServiceMonitor', status: 'active', link: '/monitoring/11-long-term-and-operator' },
]
</script>

# Мониторинг

От метрик и SLI/SLO до Prometheus, Alertmanager, Grafana, Zabbix и долгого хранения метрик в проде.

<RoadmapChain :items="lessons" />
