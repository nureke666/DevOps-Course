---
title: "CI/CD"
description: "Курс по CI/CD: от концепций и GitOps до GitLab CI, Jenkins, GitHub Actions, качества и безопасности пайплайна"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. CI, CD и CD — концепции', desc: 'Разница Continuous Integration / Delivery / Deployment, принципы построения CI/CD, метрики DORA', status: 'active', link: '/cicd/01-cicd-concepts' },
  { title: '02. Стратегии ветвления и версионирование', desc: 'GitFlow, GitHub Flow, GitLab Flow, Trunk-Based со стороны пайплайнов и окружений', status: 'active', link: '/cicd/02-git-workflows' },
  { title: '03. Проектирование пайплайна', desc: 'Референсный пайплайн от триггера до отката, роль каждой стадии, стратегии выката', status: 'active', link: '/cicd/03-pipeline-design' },
  { title: '04. GitOps', desc: 'GitOps как модель доставки: push vs pull, reconciliation loop, Argo CD и Flux', status: 'active', link: '/cicd/04-gitops' },
  { title: '05. GitLab CI: pipeline, stage, job', desc: 'Pipeline, stage, job, .gitlab-ci.yml, предопределённые переменные, отладка пайплайна', status: 'active', link: '/cicd/05-gitlab-ci-basics' },
  { title: '06. GitLab CI: rules, variables, artifacts', desc: 'Правила запуска джоб, переменные и секреты, передача файлов, кэш, окружения', status: 'active', link: '/cicd/06-gitlab-ci-core' },
  { title: '07. Docker в GitLab CI и Registry', desc: 'dind, rootless BuildKit, buildah, kaniko (legacy), тегирование, кэш слоёв', status: 'active', link: '/cicd/07-gitlab-ci-docker' },
  { title: '08. GitLab CI: needs, extends, include, trigger', desc: 'DAG через needs, YAML-якоря, дочерние и межпроектные пайплайны, parallel/matrix', status: 'active', link: '/cicd/08-gitlab-ci-advanced' },
  { title: '09. GitLab Runner', desc: 'Установка, регистрация, executors (shell/docker/kubernetes), config.toml, диагностика stuck-джоб', status: 'active', link: '/cicd/09-gitlab-runner' },
  { title: '10. Jenkins: архитектура и основы', desc: 'Controller/agent, executors и labels, типы джоб, build triggers, JENKINS_HOME', status: 'active', link: '/cicd/10-jenkins-basics' },
  { title: '11. Jenkinsfile и декларативный пайплайн', desc: 'pipeline/agent/stages/steps, credentials, parameters, post, stash/unstash', status: 'active', link: '/cicd/11-jenkins-pipeline' },
  { title: '12. Jenkins: Groovy, Shared Libraries', desc: 'Scripted pipeline, параллельные стадии, Shared Libraries, Multibranch, docker/k8s-агенты', status: 'active', link: '/cicd/12-jenkins-advanced' },
  { title: '13. Качество и безопасность пайплайна', desc: 'Пирамида проверок, линтеры и quality gates, SAST/SCA/DAST, секреты и supply chain security', status: 'active', link: '/cicd/13-quality-security' },
  { title: '14. Практика: лабы из роадмапа', desc: 'Шесть сквозных лаб: пайплайн build-test-deploy, три окружения, шаблоны CI, Jenkins, откат', status: 'active', link: '/cicd/14-practice-labs' },
  { title: '15. Вопросы с собеседований', desc: 'Топ-вопросы про идеальный пайплайн, CI/CD/Deployment, extends/include, GitOps', status: 'active', link: '/cicd/15-interview' },
  { title: '16. GitHub Actions', desc: 'Для тех, кто знает GitLab CI: workflow, матрицы, GHCR, GitOps, OIDC, ARC и безопасность', status: 'active', link: '/cicd/16-github-actions' },
]
</script>

# CI/CD

От концепций Continuous Integration/Delivery/Deployment и GitOps до продакшен-пайплайнов на GitLab CI, Jenkins и GitHub Actions — с качеством, безопасностью и практикой на каждом шаге.

<RoadmapChain :items="lessons" />
