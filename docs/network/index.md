---
title: "Сети"
description: "Курс по сетям для DevOps: от OSI/TCP-IP до nginx, HAProxy, VPN и современных прокси"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. OSI и TCP/IP', desc: 'Модель OSI и стек TCP/IP, инкапсуляция, диагностика по уровням, порты и 5-tuple, L4 vs L7', status: 'active', link: '/network/01-osi-tcpip' },
  { title: '02. L2: Ethernet, MAC, ARP, VLAN', desc: 'MAC-адреса, ARP-обмен, broadcast-домены, VLAN и L2 в контейнерах', status: 'active', link: '/network/02-l2-ethernet-arp' },
  { title: '03. L3: IP, маршрутизация, ICMP', desc: 'IP-заголовок, таблица маршрутизации, ICMP, MTU и Path MTU Discovery, NAT/conntrack', status: 'active', link: '/network/03-l3-ip-icmp' },
  { title: '04. L4: TCP и UDP', desc: 'Три рукопожатия, закрытие соединения, TIME_WAIT/CLOSE_WAIT, флаги TCP, порты и bind', status: 'active', link: '/network/04-l4-tcp-udp' },
  { title: '05. DNS', desc: 'DNS как протокол: рекурсия, типы записей, TTL и кеширование, DNS в Docker и Kubernetes', status: 'active', link: '/network/05-dns' },
  { title: '06. HTTP', desc: 'Структура запроса/ответа, методы, коды состояния, curl, keep-alive, кеширование', status: 'active', link: '/network/06-http' },
  { title: '07. TLS/SSL', desc: 'Handshake, сертификаты, SNI, openssl s_client, Let\'s Encrypt, терминация TLS', status: 'active', link: '/network/07-tls' },
  { title: '08. SSH', desc: 'Ключи, ~/.ssh/config, проброс портов, агент, known_hosts, hardening sshd', status: 'active', link: '/network/08-ssh' },
  { title: '09. Утилиты диагностики', desc: 'ping, traceroute/mtr, ss, nc, curl, nmap, iftop/iperf3 — по каким уровням и в каком порядке', status: 'active', link: '/network/09-net-tools' },
  { title: '10. tcpdump и Wireshark', desc: 'Захват трафика, фильтры BPF, чтение флагов TCP, Wireshark/tshark, дамп HTTPS', status: 'active', link: '/network/10-tcpdump-wireshark' },
  { title: '11. Файрвол: iptables/nftables', desc: 'iptables, nftables, ufw, conntrack, NAT, DOCKER-USER', status: 'active', link: '/network/11-firewall-iptables' },
  { title: '12. Nginx', desc: 'Веб-сервер, reverse proxy, балансировщик: конфиг, location, 502/504/413, rate limiting', status: 'active', link: '/network/12-nginx' },
  { title: '13. HAProxy и балансировка', desc: 'L4 vs L7, алгоритмы балансировки, активные health-check, runtime API, VIP/keepalived', status: 'active', link: '/network/13-haproxy-balancing' },
  { title: '14. Путь запроса в браузере', desc: 'Сквозной разбор «что происходит, когда вводишь адрес в браузере» — вопрос №1 всех собеседований', status: 'active', link: '/network/14-url-journey' },
  { title: '15. Практика: лабы по сети', desc: 'Семь сквозных лаб на двух ВМ: диагностика, DNS, HTTPS, балансировка, файрвол/NAT, VPN', status: 'active', link: '/network/15-practice-labs' },
  { title: '16. Вопросы с собеседований', desc: '6 главных вопросов роадмапа с развёрнутыми ответами и 54 дополнительных по темам блока', status: 'active', link: '/network/16-interview' },
  { title: '17. VPN', desc: 'IPsec, WireGuard, mesh-сети: site-to-site на strongSwan и WireGuard, MTU/MSS, split DNS', status: 'active', link: '/network/17-vpn' },
  { title: '18. Современные прокси', desc: 'Traefik, Envoy, Caddy: автообнаружение, xDS, circuit breaking, automatic HTTPS', status: 'active', link: '/network/18-modern-proxies' },
]
</script>

# Сети

От модели OSI и TCP-рукопожатия до nginx, HAProxy, VPN и современных прокси — сетевой фундамент, без которого не бывает продакшен-DevOps.

<RoadmapChain :items="lessons" />
