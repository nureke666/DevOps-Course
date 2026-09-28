---
title: "Linux"
description: "Курс по Linux: от основ командной строки до ядра, systemd, сетей и bash-скриптинга"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '00. Стенд: Vagrant + libvirt/KVM', desc: 'Как поднять учебную VM learn-linux: установка Vagrant с провайдером libvirt, снапшоты, типовые поломки стенда', status: 'active', link: '/linux/00-vagrant' },
  { title: '01. История, ядро, дистрибутивы', desc: 'Что такое ядро и дистрибутив, чем отличаются deb/apt и rpm/dnf, почему в проде почти всегда LTS', status: 'active', link: '/linux/01-getting-started' },
  { title: '02. Command Line', desc: 'Навигация по файловой системе, cp/mv/rm/find, exit codes, globbing — жизнь в терминале', status: 'active', link: '/linux/02-command-line' },
  { title: '03. Text-Fu', desc: 'Потоки stdin/stdout/stderr, пайпы, grep/sort/uniq/awk-основы — главный рабочий навык линуксоида', status: 'active', link: '/linux/03-text-fu' },
  { title: '04. Advanced Text-Fu', desc: 'Regex, sed, awk и vim — правка конфигов и отчёты по данным без GUI', status: 'active', link: '/linux/04-advanced-text-fu' },
  { title: '05. User Management', desc: 'Пользователи, группы, root: /etc/passwd, /etc/shadow, /etc/group, sudo', status: 'active', link: '/linux/05-user-management' },
  { title: '06. Permissions', desc: 'chmod, chown, umask, setuid/setgid/sticky bit и диагностика Permission denied', status: 'active', link: '/linux/06-permissions' },
  { title: '07. Processes', desc: 'Процессы, сигналы, приоритеты: ps, kill, nice, состояния процессов, job control, /proc', status: 'active', link: '/linux/07-processes' },
  { title: '08. Packages', desc: 'Пакеты и репозитории: apt, dpkg, tar/gzip, зависимости, сборка из исходников', status: 'active', link: '/linux/08-packages' },
  { title: '09. Devices', desc: 'Устройства, /dev, udev, sysfs и dd: имена дисков, стабильные UUID, побайтовое копирование', status: 'active', link: '/linux/09-devices' },
  { title: '10. Файловая система', desc: 'Разделы, монтирование, fstab, inode, ссылки, поиск места на диске', status: 'active', link: '/linux/10-the-filesystem' },
  { title: '11. Загрузка системы', desc: 'GRUB, initramfs, systemd PID 1, сброс пароля root, диагностика незагружающегося сервера', status: 'active', link: '/linux/11-boot-the-system' },
  { title: '12. Ядро Linux', desc: 'User space vs kernel space, системные вызовы, strace, модули ядра, sysctl', status: 'active', link: '/linux/12-kernel' },
  { title: '13. Init: systemd', desc: 'SysV, Upstart, systemd — юниты, unit-файлы, таргеты, таймеры, управление сервисами', status: 'active', link: '/linux/13-init' },
  { title: '14. Мониторинг процессов и cron', desc: 'top/htop, load average, iostat, память, потоки, cron — диагностика «сервер тормозит»', status: 'active', link: '/linux/14-process-utilization' },
  { title: '15. Логирование', desc: 'journald, rsyslog, logrotate: куда текут логи в Linux, уровни severity, ротация', status: 'active', link: '/linux/15-logging' },
  { title: '16. Network Sharing', desc: 'rsync, NFS, Samba, HTTP: как передавать и расшаривать файлы между серверами', status: 'active', link: '/linux/16-network-sharing' },
  { title: '17. Основы сетей', desc: 'OSI и TCP/IP, инкапсуляция, MAC/IP/порты, TCP vs UDP, ARP, DHCP', status: 'active', link: '/linux/17-network-basics' },
  { title: '18. Subnetting', desc: 'Подсети, CIDR, VLSM, NAT, IPv6 — расчёт подсетей в уме и проектирование адресации VPC', status: 'active', link: '/linux/18-subnetting' },
  { title: '19. Маршрутизация', desc: 'Таблица маршрутизации, longest prefix match, TTL и traceroute, distance vector vs link state, BGP', status: 'active', link: '/linux/19-routing' },
  { title: '20. Network Config', desc: 'Настройка сети: ip, netplan, NetworkManager, DNS, ARP — временные и постоянные изменения', status: 'active', link: '/linux/20-network-config' },
  { title: '21. Troubleshooting', desc: 'Диагностика сети снизу вверх: ICMP, ping, traceroute/mtr, ss, tcpdump, готовые алгоритмы', status: 'active', link: '/linux/21-troubleshooting' },
  { title: '22. DNS', desc: 'Путь резолвинга, типы записей, dig, /etc/hosts vs DNS, алгоритм «DNS не работает»', status: 'active', link: '/linux/22-dns' },
  { title: '23. Bash Scripting: основы', desc: 'Shebang, переменные, кавычки, parameter expansion, аргументы, коды возврата', status: 'active', link: '/linux/23-bash-basics' },
  { title: '24. Bash: условия, циклы, функции, массивы', desc: 'if/case, [[ ]] vs (( )), циклы и ловушки subshell, функции с local, массивы', status: 'active', link: '/linux/24-bash-control-flow' },
  { title: '25. Надёжный bash-скрипт', desc: 'set -euo pipefail, trap, безопасные временные файлы, flock, человеческий CLI', status: 'active', link: '/linux/25-bash-robust' },
  { title: '26. Bash в DevOps: боевые паттерны', desc: 'entrypoint для контейнера, wait-for, curl+jq, ретраи с backoff, параллельность', status: 'active', link: '/linux/26-bash-devops-practice' },
  { title: '27. Практика: лабы', desc: 'Семь сквозных лаб по блоку Linux: онбординг, свой сервис, диск полон, сервер тормозит, сеть, emergency mode', status: 'active', link: '/linux/27-practice-labs' },
  { title: '28. Вопросы с собеседований', desc: '6 главных вопросов, 42 темы блока, live-траблшутинг и задачи «напиши на доске»', status: 'active', link: '/linux/28-interview' },
]
</script>

# Linux

От первого входа в терминал до ядра, systemd, сетей на уровне ОС и bash-скриптинга — фундамент, без которого не работает ни Docker, ни Kubernetes, ни CI/CD.

<RoadmapChain :items="lessons" />
