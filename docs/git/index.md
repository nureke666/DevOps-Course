---
title: "Git"
description: "Курс по Git: от основ до стратегий ветвления и Git в DevOps"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Что такое Git', desc: 'Система контроля версий, распределённость, коммит как снимок', status: 'active', link: '/git/01-git-intro' },
  { title: '02. Три области и init/add/commit', desc: 'Working tree, staging area, репозиторий — и команды init, add, commit, status, log, diff, .gitignore', status: 'active', link: '/git/02-basics-workflow' },
  { title: '03. Удалённые репозитории', desc: 'clone, push, pull, fetch, SSH-ключи, origin/main и git pull под капотом', status: 'active', link: '/git/03-remote-repos' },
  { title: '04. Ветки и слияние', desc: 'branch, switch/checkout, merge, fast-forward и трёхстороннее слияние, detached HEAD', status: 'active', link: '/git/04-branches' },
  { title: '05. Merge conflict', desc: 'Причины конфликтов слияния, разрешение, маркеры, профилактика', status: 'active', link: '/git/05-merge-conflicts' },
  { title: '06. Rebase и cherry-pick', desc: 'Перенос коммитов между ветками: rebase, интерактивный rebase, cherry-pick, force-with-lease', status: 'active', link: '/git/06-rebase-cherry-pick' },
  { title: '07. Отмена изменений и история', desc: 'restore, reset, revert, stash, reflog — как отменить что угодно на любой стадии', status: 'active', link: '/git/07-undo-history' },
  { title: '08. Теги и версионирование', desc: 'v1.0, v2.0, SemVer: аннотированные и lightweight-теги, теги в CI/CD', status: 'active', link: '/git/08-tags-versioning' },
  { title: '09. Стратегии ветвления', desc: 'GitFlow, GitHub Flow, GitLab Flow, Trunk-Based: сравнение и выбор', status: 'active', link: '/git/09-branching-strategies' },
  { title: '10. Markdown', desc: 'README, документация, конспекты: синтаксис, диалекты, docs as code', status: 'active', link: '/git/10-markdown' },
  { title: '11. Командная работа', desc: 'Pull/Merge Request, ревью, защита веток, CODEOWNERS, Conventional Commits', status: 'active', link: '/git/11-collaboration' },
  { title: '12. Git в работе DevOps', desc: 'Расследование, хуки, секреты, submodules/LFS, git в CI/CD', status: 'active', link: '/git/12-git-in-devops' },
  { title: '13. Практика: лабы', desc: 'Семь практических лаб: репозиторий конспектов, командная работа, релизы, CI, спасательные операции', status: 'active', link: '/git/13-practice-labs' },
  { title: '14. Вопросы с собеседований', desc: 'Главные вопросы по Git, практические задания и как себя вести на собесе', status: 'active', link: '/git/14-interview' },
]
</script>

# Git

Путь от основ до продвинутых сценариев: ветки, rebase, стратегии ветвления и то, как git используется в DevOps каждый день.

<RoadmapChain :items="lessons" />
