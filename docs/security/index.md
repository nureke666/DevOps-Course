---
title: "Безопасность (DevSecOps)"
description: "Харденинг Linux, OWASP и WAF на периметре, сканирование уязвимостей Trivy в CI, IAM least privilege и безопасность Kubernetes"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Security mindset: как думать о безопасности", "desc": "CIA, least privilege, defense in depth, zero trust, STRIDE-lite, карта безопасности в волте", "status": "active", "link": "/security/01-security-mindset"},
  {"title": "02. Харденинг Linux-сервера", "desc": "Единый чек-лист, auditd, AppArmor/SELinux, sysctl, CIS, Lynis, Ansible-роль", "status": "active", "link": "/security/02-linux-hardening"},
  {"title": "03. Безопасность веба и периметра (edge)", "desc": "OWASP Top 10:2025 глазами инфры, заголовки, rate limit, WAF + CRS, DDoS, testssl.sh", "status": "active", "link": "/security/03-web-edge-security"},
  {"title": "04. Управление уязвимостями", "desc": "CVE, CVSS v3.1/v4.0, EPSS, KEV, триаж Trivy, .trivyignore со сроком, SBOM, Renovate", "status": "active", "link": "/security/04-vuln-management"},
  {"title": "05. IAM и доступ", "desc": "Политики и роли, OIDC из GitLab CI, bastion/VPN/IAP, SSO, break-glass, SSH-сертификаты", "status": "active", "link": "/security/05-iam-access"},
  {"title": "06. Безопасность Kubernetes", "desc": "PSS/PSA, securityContext, Kyverno и VAP, kube-bench, Falco, cosign, encryption at rest", "status": "active", "link": "/security/06-k8s-security"},
  {"title": "07. Инциденты безопасности и compliance", "desc": "Playbooks, форензика, аудит-логи, закон РК о ПДн, PCI DSS, ISO 27001, аудит", "status": "active", "link": "/security/07-security-incidents-compliance"},
  {"title": "08. Практика: 5 лаб по безопасности", "desc": "5 лаб: харденинг + Lynis, security-стадия CI, kind (kube-bench, PSA, Kyverno, Falco), аудит edge, game day «утёк токен»", "status": "active", "link": "/security/08-practice-labs"},
  {"title": "09. Вопросы с собеседований: безопасность для DevOps", "desc": "Главные вопросы с развёрнутыми ответами + 42 коротких + ситуационные задачи", "status": "active", "link": "/security/09-interview"},
]
</script>

# Безопасность для DevOps (DevSecOps)

Харденинг Linux, OWASP и WAF на периметре, сканирование уязвимостей Trivy в CI, IAM least privilege и безопасность Kubernetes

<RoadmapChain :items="lessons" />
