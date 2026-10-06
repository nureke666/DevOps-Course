---
title: "MLOps и AI"
description: "GPU в Kubernetes, сервинг LLM (vLLM, Ollama), LLM Gateway, pgvector для RAG и пайплайны доставки моделей MLflow"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. ML- и LLM-системы глазами девопса", "desc": "Жизненный цикл модели, роли (DS, ML-инженер, MLOps), обучение vs инференс, архитектура LLM-приложения (RAG, агенты), чем это отличается от обычного сервиса", "status": "active", "link": "/mlops/01-ml-systems-for-devops"},
  {"title": "02. GPU в Kubernetes: драйвер, device plugin, GPU Operator, разделение, DRA, метрики, деньги", "desc": "Драйверы и container toolkit, device plugin, GPU Operator, nvidia.com/gpu, taints, time-slicing, MIG, DRA, DCGM-метрики, стоимость", "status": "active", "link": "/mlops/02-gpu-kubernetes"},
  {"title": "03. Сервинг моделей: vLLM, llama.cpp, Ollama, KServe, холодный старт, метрики, автоскейлинг", "desc": "vLLM, Ollama/llama.cpp, Triton, KServe; хранение моделей, холодный старт, батчинг, метрики TTFT и tokens/s, автоскейлинг по очереди", "status": "active", "link": "/mlops/03-model-serving"},
  {"title": "04. LLM-шлюз, RAG и векторные базы", "desc": "Шлюз (LiteLLM и аналоги): ключи, лимиты, учёт токенов, fallback, кэш; наблюдаемость (OTel GenAI); pgvector и Qdrant; данные и закон РК", "status": "active", "link": "/mlops/04-llm-gateway-rag"},
  {"title": "05. Пайплайны и реестр моделей: MLflow, DVC, оркестраторы, CT/CD", "desc": "MLflow tracking и registry, версионирование данных (DVC), пайплайны (Kubeflow Pipelines, Argo Workflows, Airflow), CT/CD моделей", "status": "active", "link": "/mlops/05-ml-pipelines"},
  {"title": "06. ИИ в работе девопса: ассистенты, агенты, проверка и безопасность", "desc": "Где ассистенты реально помогают, как проверять сгенерированный IaC, утечки секретов, prompt injection через логи и тикеты, агенты с доступом к кластеру, MCP, политика команды", "status": "active", "link": "/mlops/06-ai-in-devops-work"},
  {"title": "07. Практика: шесть лаб без GPU", "desc": "6 лаб без GPU: модель на CPU в kind, автоскейлинг сервинга по очереди, LLM-шлюз с лимитами и учётом, RAG на pgvector, MLflow registry → деплой, «безопасный агент»", "status": "active", "link": "/mlops/07-practice-labs"},
  {"title": "08. Вопросы с собеседований: AI/MLOps-инфраструктура", "desc": "Главные вопросы с развёрнутыми ответами + ~40 коротких + ситуационные задачи", "status": "active", "link": "/mlops/08-interview"},
]
</script>

# AI/MLOps-инфраструктура

GPU в Kubernetes, сервинг LLM (vLLM, Ollama), LLM Gateway, pgvector для RAG и пайплайны доставки моделей MLflow

<RoadmapChain :items="lessons" />
