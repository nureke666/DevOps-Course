---
title: "Python для DevOps"
description: "CLI утилиты, HTTP API, парсинг логов, infra SDK (boto3, kubernetes, docker), prometheus_client и тестирование с pytest"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Окружение и каркас скрипта", "desc": "bash vs Python, venv/pip/pipx/uv, main() и коды выхода", "status": "active", "link": "/python/01-python-setup"},
  {"title": "02. Python-минимум для скриптов", "desc": "Коллекции, comprehension, исключения, with, dataclass, грабли", "status": "active", "link": "/python/02-basics-for-scripts"},
  {"title": "03. Файлы, ОС и внешние команды", "desc": "pathlib, атомарная запись, subprocess.run, сигналы, архивы", "status": "active", "link": "/python/03-files-os-subprocess"},
  {"title": "04. CLI, логирование и конфиги", "desc": "argparse, logging, YAML/TOML, приоритет настроек, dry-run", "status": "active", "link": "/python/04-cli-logging-config"},
  {"title": "05. HTTP и API: requests, httpx, ретраи, пагинация", "desc": "Таймауты, ретраи с backoff, пагинация, GitLab, Telegram", "status": "active", "link": "/python/05-http-api"},
  {"title": "06. Разбор логов и отчёты", "desc": "regex, nginx access.log, Counter, генераторы, перцентили", "status": "active", "link": "/python/06-parsing-logs"},
  {"title": "07. Инфраструктурные библиотеки: SSH, Docker, Kubernetes, S3, Prometheus", "desc": "paramiko/fabric, docker, kubernetes, boto3, prometheus_client", "status": "active", "link": "/python/07-infra-libs"},
  {"title": "08. Упаковка и качество: pyproject, ruff, pytest, Docker, CI", "desc": "pyproject, ruff, pytest с моками, Dockerfile, GitLab CI", "status": "active", "link": "/python/08-packaging-quality"},
  {"title": "09. Практика: 5 лаб по Python для DevOps", "desc": "5 лаб: бэкап в MinIO, health-checker, анализатор логов, уборщик подов, exporter + CI", "status": "active", "link": "/python/09-practice-labs"},
  {"title": "10. Вопросы с собеседований: Python для DevOps", "desc": "8 главных вопросов, 40 коротких, 7 задач «напиши скрипт» с решениями", "status": "active", "link": "/python/10-interview"},
]
</script>

# Python для DevOps

CLI утилиты, HTTP API, парсинг логов, infra SDK (boto3, kubernetes, docker), prometheus_client и тестирование с pytest

<RoadmapChain :items="lessons" />
