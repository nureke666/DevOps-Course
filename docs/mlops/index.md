---
title: "MLOps и AI"
description: "GPU в Kubernetes, сервинг LLM (vLLM, Ollama), LLM Gateway, pgvector для RAG и пайплайны доставки моделей MLflow"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. ML- и LLM-системы глазами девопса", "desc": "Блок → AI/MLOps-инфраструктура → тема 01. Модель обучает не девопс —", "status": "active", "link": "/mlops/01-ml-systems-for-devops"}, {"title": "02. GPU в Kubernetes: драйвер, device plugin, GPU Operator, разделение, DRA, метрики, деньги", "desc": "Блок → AI/MLOps-инфраструктура → тема 02. GPU — самый дорогой ресурс кластера,", "status": "active", "link": "/mlops/02-gpu-kubernetes"}, {"title": "03. Сервинг моделей: vLLM, llama.cpp, Ollama, KServe, холодный старт, метрики, автоскейлинг", "desc": "Блок → AI/MLOps-инфраструктура → тема 03. Самая частая задача девопса в ML —", "status": "active", "link": "/mlops/03-model-serving"}, {"title": "04. LLM-шлюз, RAG и векторные базы", "desc": "Блок → AI/MLOps-инфраструктура → тема 04. Вопросы собеса: «Зачем вам LLM-шлюз, если", "status": "active", "link": "/mlops/04-llm-gateway-rag"}, {"title": "05. Пайплайны и реестр моделей: MLflow, DVC, оркестраторы, CT/CD", "desc": "Блок → AI/MLOps-инфраструктура → тема 05. Вопросы собеса: «Как модель попадает", "status": "active", "link": "/mlops/05-ml-pipelines"}, {"title": "06. ИИ в работе девопса: ассистенты, агенты, проверка и безопасность", "desc": "Блок → AI/MLOps-инфраструктура → тема 06. Вопросы собеса: «Пользуетесь ли вы ИИ в работе", "status": "active", "link": "/mlops/06-ai-in-devops-work"}, {"title": "07. Практика: шесть лаб без GPU", "desc": "Блок → AI/MLOps-инфраструктура → практика. Всё на CPU с маленькими моделями: GPU не нужен,", "status": "active", "link": "/mlops/07-practice-labs"}, {"title": "08. Вопросы с собеседований: AI/MLOps-инфраструктура", "desc": "Блок → AI/MLOps-инфраструктура → собеседование.", "status": "active", "link": "/mlops/08-interview"}]
</script>

# AI/MLOps-инфраструктура

GPU в Kubernetes, сервинг LLM (vLLM, Ollama), LLM Gateway, pgvector для RAG и пайплайны доставки моделей MLflow

<RoadmapChain :items="lessons" />
