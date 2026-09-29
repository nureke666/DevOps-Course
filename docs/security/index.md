---
title: "Безопасность (DevSecOps)"
description: "Харденинг Linux, OWASP и WAF на периметре, сканирование уязвимостей Trivy в CI, IAM least privilege и безопасность Kubernetes"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Security mindset: как думать о безопасности", "desc": "Блок → Безопасность → тема 01. Опирается на", "status": "active", "link": "/security/01-security-mindset"}, {"title": "02. Харденинг Linux-сервера", "desc": "Блок → Безопасность → тема 02. Опирается на", "status": "active", "link": "/security/02-linux-hardening"}, {"title": "03. Безопасность веба и периметра (edge)", "desc": "Блок → Безопасность → тема 03. Опирается на", "status": "active", "link": "/security/03-web-edge-security"}, {"title": "04. Управление уязвимостями", "desc": "Блок → Безопасность → тема 04. Опирается на", "status": "active", "link": "/security/04-vuln-management"}, {"title": "05. IAM и доступ", "desc": "Блок → Безопасность → тема 05. Опирается на", "status": "active", "link": "/security/05-iam-access"}, {"title": "06. Безопасность Kubernetes", "desc": "Блок → Безопасность → тема 06. Опирается на", "status": "active", "link": "/security/06-k8s-security"}, {"title": "07. Инциденты безопасности и compliance", "desc": "Блок → Безопасность → тема 07. Опирается на", "status": "active", "link": "/security/07-security-incidents-compliance"}, {"title": "08. Практика: 5 лаб по безопасности", "desc": "Блок → Безопасность → практика.", "status": "active", "link": "/security/08-practice-labs"}, {"title": "09. Вопросы с собеседований: безопасность для DevOps", "desc": "Блок → Безопасность → собеседование.", "status": "active", "link": "/security/09-interview"}]
</script>

# Безопасность для DevOps (DevSecOps)

Харденинг Linux, OWASP и WAF на периметре, сканирование уязвимостей Trivy в CI, IAM least privilege и безопасность Kubernetes

<RoadmapChain :items="lessons" />
