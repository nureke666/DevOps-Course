---
title: "Ansible"
description: "Курс по Ansible: от inventory и модулей до плейбуков, ролей, vault, best practices и запуска из CI/CD"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Введение в Ansible', desc: 'Что такое Ansible, agentless-модель, push vs pull, место среди других инструментов', status: 'active', link: '/ansible/01-ansible-intro' },
  { title: '02. Установка и подключение', desc: 'Установка, SSH-подключение, python-интерпретатор, ansible.cfg, проверка связи', status: 'active', link: '/ansible/02-setup-connection' },
  { title: '03. Inventory', desc: 'Статический и динамический inventory, группы, group_vars/host_vars, окружения', status: 'active', link: '/ansible/03-inventory' },
  { title: '04. Ad-hoc команды', desc: 'Разовые команды для диагностики и срочных операций', status: 'active', link: '/ansible/04-ad-hoc' },
  { title: '05. Модули', desc: 'Идемпотентные модули вместо shell/command, ключевые модули ansible.builtin', status: 'active', link: '/ansible/05-modules' },
  { title: '06. Основы плейбуков', desc: 'Структура play, порядок выполнения, pre_tasks/tasks/post_tasks', status: 'active', link: '/ansible/06-playbook-basics' },
  { title: '07. Переменные и facts', desc: 'Приоритеты переменных, facts, register/set_fact, hostvars', status: 'active', link: '/ansible/07-variables-facts' },
  { title: '08. Условия и циклы', desc: 'when, loop, loop_control, блоки и обработка ошибок', status: 'active', link: '/ansible/08-conditions-loops' },
  { title: '09. Handlers и идемпотентность', desc: 'notify/handlers, changed_when, критерий changed=0, что ломает идемпотентность', status: 'active', link: '/ansible/09-handlers-idempotency' },
  { title: '10. Шаблоны и Jinja2', desc: 'template-модуль, фильтры Jinja2, генерация конфигов из inventory', status: 'active', link: '/ansible/10-templates-jinja2' },
  { title: '11. Роли', desc: 'Структура роли, defaults/vars, meta-зависимости, Ansible Galaxy, requirements.yml', status: 'active', link: '/ansible/11-roles' },
  { title: '12. Ansible Vault', desc: 'Шифрование файлов и значений, vault-id для окружений, использование в CI/CD', status: 'active', link: '/ansible/12-vault' },
  { title: '13. Best practices, отладка, CI/CD', desc: 'Эталонная структура проекта, ansible-lint, molecule, производительность, безопасный прод', status: 'active', link: '/ansible/13-best-practices' },
  { title: '14. Практика: лабы из роадмапа', desc: 'Плейбук с нуля, роль nginx, деплой контейнера, репозиторий с vault, Ansible в GitLab CI', status: 'active', link: '/ansible/14-practice-labs' },
  { title: '15. Вопросы с собеседований', desc: 'Playbook, роли, приоритеты переменных, handler, идемпотентность и 40+ дополнительных вопросов', status: 'active', link: '/ansible/15-interview' },
]
</script>

# Ansible

От inventory и идемпотентных модулей до плейбуков, ролей, Vault и запуска Ansible из CI/CD — с best practices и практическими лабами на каждом шаге.

<RoadmapChain :items="lessons" />
