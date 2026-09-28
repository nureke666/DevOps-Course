---
title: "Docker"
description: "Курс по Docker: от контейнеров и образов до compose, безопасности и troubleshooting"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Контейнеры и архитектура Docker', desc: 'Контейнер как процесс Linux, namespaces, cgroups, архитектура docker: CLI → API → dockerd → containerd → runc', status: 'active', link: '/docker/01-containers-intro' },
  { title: '02. Образы: слои, overlay2, теги', desc: 'Из чего состоит docker-образ, copy-on-write, overlay2, тегирование и дайджесты', status: 'active', link: '/docker/02-images-layers' },
  { title: '03. Dockerfile: директивы и контекст сборки', desc: 'Все директивы Dockerfile, контекст сборки, CMD vs ENTRYPOINT, COPY vs ADD, ENV vs ARG', status: 'active', link: '/docker/03-dockerfile' },
  { title: '04. Кэш сборки, multi-stage и best practices', desc: 'Как работает кэш слоёв, multi-stage build, 13 best practice\'ов — 800 МБ → 30 МБ', status: 'active', link: '/docker/04-build-cache-multistage' },
  { title: '05. Registry и тегирование', desc: 'Registry — точка встречи CI и CD: тегирование, версионирование, дайджесты, безопасность образов', status: 'active', link: '/docker/05-registry-tags' },
  { title: '06. Жизненный цикл контейнера', desc: 'Состояния контейнера, docker run/stop/exec/inspect, сигналы, PID 1, коды выхода', status: 'active', link: '/docker/06-containers-lifecycle' },
  { title: '07. Данные: volumes, bind mounts, tmpfs', desc: 'Named volumes, bind mounts, tmpfs — как не терять данные при пересоздании контейнера', status: 'active', link: '/docker/07-volumes-storage' },
  { title: '08. Сеть в Docker', desc: 'bridge, host, none, overlay, macvlan; путь пакета от curl до процесса в контейнере', status: 'active', link: '/docker/08-network' },
  { title: '09. Docker Compose', desc: 'Многоконтейнерные приложения в YAML: services, depends_on, volumes, networks, profiles', status: 'active', link: '/docker/09-compose' },
  { title: '10. Безопасность контейнеров', desc: 'Non-root, capabilities, seccomp, секреты, сканирование образов (trivy/hadolint/cosign)', status: 'active', link: '/docker/10-security-best-practices' },
  { title: '11. Troubleshooting и обслуживание', desc: 'Методика диагностики контейнеров: коды выхода, OOM, сеть, ресурсы, пропавшие данные', status: 'active', link: '/docker/11-troubleshooting' },
  { title: '12. Практика: лабы', desc: 'Контейнеризация своего приложения, docker compose, мониторинг-стек Prometheus+Grafana', status: 'active', link: '/docker/12-practice-labs' },
  { title: '13. Вопросы с собеседований', desc: '6 главных вопросов роадмапа с развёрнутыми ответами и 40 дополнительных по темам Docker', status: 'active', link: '/docker/13-interview' },
]
</script>

# Docker

От «что такое контейнер на самом деле» до multi-stage сборок, compose-стека и продакшен-troubleshooting.

<RoadmapChain :items="lessons" />
