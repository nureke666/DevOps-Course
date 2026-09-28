---
title: "Облака"
description: "Курс по облакам: модели IaaS/PaaS/SaaS, сеть и хранилище, managed-сервисы, AWS, Yandex Cloud, облака Казахстана"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Модели облаков: IaaS, PaaS, SaaS', desc: 'Структура облака, shared responsibility, биллинг, специфика Казахстана', status: 'active', link: '/cloud/01-cloud-models' },
  { title: '02. ВМ и подключение по SSH', desc: 'Создание ВМ через консоль/CLI, SSH-ключи и bastion, cloud-init, метаданные', status: 'active', link: '/cloud/02-compute-ssh' },
  { title: '03. Сеть в облаке: VPC', desc: 'VPC и подсети, security groups, NAT, балансировщики, диагностика «не коннектится»', status: 'active', link: '/cloud/03-network-vpc' },
  { title: '04. S3 и объектное хранилище', desc: 'Бакеты и объекты, доступ, версионирование, lifecycle, S3-совместимость', status: 'active', link: '/cloud/04-s3-storage' },
  { title: '05. Managed-сервисы', desc: 'Managed PostgreSQL и Kubernetes в AWS и Yandex Cloud, зоны ответственности', status: 'active', link: '/cloud/05-managed-services' },
  { title: '06. Практика: 5 лаб', desc: 'Первая ВМ, сеть проекта, объектное хранилище, managed-база, полный стенд', status: 'active', link: '/cloud/06-practice-labs' },
  { title: '07. Вопросы с собеседований', desc: 'Семь главных вопросов, 35 по темам и вопросы про облака Казахстана', status: 'active', link: '/cloud/07-interview' },
  { title: '08. AWS глубже', desc: 'Organizations, эталонная VPC, ASG за ALB, RDS Multi-AZ, EKS, CloudWatch, деньги', status: 'active', link: '/cloud/08-aws-deep' },
  { title: '09. Yandex Cloud глубже', desc: 'Ресурсная модель, IAM, VPC, Managed Kubernetes, Managed PostgreSQL, Object Storage', status: 'active', link: '/cloud/09-yandex-cloud' },
  { title: '10. Казахстанские облака', desc: 'Локализация ПДн, обзор провайдеров, OpenStack, гибридные схемы, due diligence', status: 'active', link: '/cloud/10-kz-clouds' },
]
</script>

# Облака

От моделей IaaS/PaaS/SaaS и сети до managed-сервисов, AWS, Yandex Cloud и облаков с ЦОД в Казахстане.

<RoadmapChain :items="lessons" />
