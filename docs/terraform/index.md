---
title: "Terraform"
description: "Курс по Terraform: IaC и основы, стейт и backend, переменные и модули, CI/CD, тестирование инфраструктурного кода"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Инфраструктура как код и место Terraform', desc: 'Три способа управлять инфраструктурой, декларативный подход, Terraform vs Ansible, OpenTofu', status: 'active', link: '/terraform/01-iac-intro' },
  { title: '02. Провайдер, ресурс, plan и apply', desc: 'Жизненный цикл init/plan/apply/destroy, синтаксис HCL, провайдеры AWS и Yandex Cloud', status: 'active', link: '/terraform/02-terraform-basics' },
  { title: '03. Стейт и backend', desc: 'Зачем нужен стейт, удалённый backend с блокировкой, импорт ресурсов, разделение стейтов', status: 'active', link: '/terraform/03-state-backend' },
  { title: '04. Переменные, выражения и зависимости', desc: 'variable/locals/data/output, count vs for_each, dynamic-блоки, templatefile', status: 'active', link: '/terraform/04-variables-outputs' },
  { title: '05. Модули', desc: 'Анатомия модуля, источники, moved-блок, репозиторий с окружениями, контракт AWS/Yandex', status: 'active', link: '/terraform/05-modules' },
  { title: '06. Рабочий процесс и CI/CD', desc: 'Окружения, Terraform в GitLab CI, секреты, чек-лист ревью MR', status: 'active', link: '/terraform/06-workflow-cicd' },
  { title: '07. Практика: 5 лаб', desc: 'От hello world на docker до модульной инфраструктуры в CI, варианты AWS и Yandex Cloud', status: 'active', link: '/terraform/07-practice-labs' },
  { title: '08. Вопросы с собеседований', desc: 'Семь главных вопросов и 38 дополнительных по всем темам блока', status: 'active', link: '/terraform/08-interview' },
  { title: '09. Тестирование инфраструктурного кода', desc: 'Пирамида тестирования IaC: линтеры, сканеры, conftest, terraform test с моками, Terratest', status: 'active', link: '/terraform/09-testing' },
]
</script>

# Terraform

От инфраструктуры как кода и основ HCL до стейта, модулей, CI/CD и полноценной пирамиды
тестирования инфраструктурного кода — с параллельными примерами для AWS и Yandex Cloud.

<RoadmapChain :items="lessons" />
