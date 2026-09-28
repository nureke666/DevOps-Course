---
title: "Vault"
description: "Курс по HashiCorp Vault: проблема секретов, архитектура, KV engine, auth methods, интеграции и динамические секреты"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Проблема секретов', desc: 'Почему привычные способы хранения секретов ненадёжны, требования к решению', status: 'active', link: '/vault/01-secrets-problem' },
  { title: '02. Что такое Vault и как он устроен', desc: 'Архитектура, seal/unseal, установка, токены, политики, аудит', status: 'active', link: '/vault/02-vault-intro' },
  { title: '03. KV secret engine', desc: 'KV v1 vs v2, версии и мягкое удаление, структура путей, доставка секретов', status: 'active', link: '/vault/03-kv-engine' },
  { title: '04. Auth methods и политики', desc: 'Способы аутентификации для людей, приложений, CI и Kubernetes, TTL и отзыв', status: 'active', link: '/vault/04-auth-methods' },
  { title: '05. Интеграции и динамические секреты', desc: 'Динамические креды для БД, Kubernetes, CI/CD, Ansible, Terraform', status: 'active', link: '/vault/05-vault-integrations' },
  { title: '06. Практика: 4 лабы', desc: 'Vault с нуля, политики и auth methods, динамические креды, Vault + Kubernetes + CI', status: 'active', link: '/vault/06-practice-labs' },
  { title: '07. Вопросы с собеседований', desc: 'Шесть главных вопросов и 30 дополнительных по всем темам блока', status: 'active', link: '/vault/07-interview' },
]
</script>

# Vault

От проблемы хранения секретов до архитектуры Vault, KV engine, auth methods
и динамических секретов для баз данных, Kubernetes, CI/CD, Ansible и Terraform.

<RoadmapChain :items="lessons" />
