---
title: "Kubernetes"
description: "Курс по Kubernetes: от Pod и Deployment до Helm, RBAC, автоскейлинга и жизненного цикла кластера"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. Зачем нужен Kubernetes', desc: 'Reconciliation loop, декларативность, чем кубер отличается от docker compose и когда он не нужен', status: 'active', link: '/kubernetes/01-k8s-intro' },
  { title: '02. Архитектура кластера', desc: 'Control plane, worker node, путь kubectl apply до работающего контейнера', status: 'active', link: '/kubernetes/02-architecture' },
  { title: '03. kubectl и манифесты', desc: 'Анатомия манифеста, императивно vs декларативно, labels и selectors', status: 'active', link: '/kubernetes/03-kubectl-manifests' },
  { title: '04. Pod — минимальная единица', desc: 'Почему под, а не контейнер; фазы и статусы, init-контейнеры, sidecar-паттерны', status: 'active', link: '/kubernetes/04-pod' },
  { title: '05. Deployment и ReplicaSet', desc: 'RollingUpdate, откат, история ревизий, canary и blue-green на голых манифестах', status: 'active', link: '/kubernetes/05-deployment' },
  { title: '06. DaemonSet и StatefulSet', desc: 'Deployment vs StatefulSet vs DaemonSet, headless Service, volumeClaimTemplates', status: 'active', link: '/kubernetes/06-daemonset-statefulset' },
  { title: '07. Job и CronJob', desc: 'completions/parallelism/backoffLimit, CronJob и расписание, миграции БД как Job', status: 'active', link: '/kubernetes/07-job-cronjob' },
  { title: '08. ConfigMap и Secret', desc: 'env/envFrom/том, base64 не шифрование, приватный реестр, SOPS/ESO', status: 'active', link: '/kubernetes/08-configmap-secret' },
  { title: '09. Проверки (probes) и ресурсы', desc: 'liveness/readiness/startup пробы, requests и limits, QoS-классы', status: 'active', link: '/kubernetes/09-probes-resources' },
  { title: '10. Сеть под капотом', desc: 'CNI-плагины, kube-proxy, CoreDNS — путь пакета от пода к поду и от пода к Service', status: 'active', link: '/kubernetes/10-network-internals' },
  { title: '11. Service', desc: 'ClusterIP, NodePort, LoadBalancer, headless, ExternalName — «сервис есть, а не отвечает»', status: 'active', link: '/kubernetes/11-service' },
  { title: '12. Ingress и Ingress Controller', desc: 'Ingress vs Ingress Controller, TLS, аннотации nginx, переход на Gateway API', status: 'active', link: '/kubernetes/12-ingress' },
  { title: '13. NetworkPolicy', desc: 'Встроенный firewall уровня пода: default deny, селекторы, зависимость от CNI', status: 'active', link: '/kubernetes/13-networkpolicy' },
  { title: '14. Хранилище: PV, PVC, StorageClass', desc: 'Access Modes (RWO/ROX/RWX/RWOP), reclaimPolicy, CSI, расширение тома', status: 'active', link: '/kubernetes/14-storage' },
  { title: '15. Helm', desc: 'Чарты, values, шаблоны, релизы, откаты, хуки, зависимости', status: 'active', link: '/kubernetes/15-helm' },
  { title: '16. Развёртывание кластера', desc: 'kubeadm, kubespray, managed Kubernetes: сравнение подходов, drain/cordon', status: 'active', link: '/kubernetes/16-cluster-deployment' },
  { title: '17. RBAC', desc: 'Субъекты, Role/ClusterRole, RoleBinding/ClusterRoleBinding, минимальные привилегии для CI', status: 'active', link: '/kubernetes/17-rbac' },
  { title: '18. HPA и автоскейлинг', desc: 'Формула HPA, метрики CPU/память/custom, VPA, Cluster Autoscaler и Karpenter', status: 'active', link: '/kubernetes/18-hpa-autoscaling' },
  { title: '19. Планирование подов', desc: 'affinity/anti-affinity, taints и tolerations, topologySpreadConstraints, PDB', status: 'active', link: '/kubernetes/19-scheduling' },
  { title: '20. Траблшутинг кластера', desc: 'Алгоритм разбора: под не стартует, падает, сервис не отвечает, нода NotReady', status: 'active', link: '/kubernetes/20-troubleshooting' },
  { title: '21. Развилка: куда дальше', desc: 'GitOps (ArgoCD/Flux), операторы и CRD, service mesh, бэкап etcd и Velero', status: 'active', link: '/kubernetes/21-advanced-paths' },
  { title: '22. Практика: лабы из роадмапа', desc: 'Девять практических лаб: локальный кластер, Helm chart, отказоустойчивость, CI/CD', status: 'active', link: '/kubernetes/22-practice-labs' },
  { title: '23. Вопросы с собеседований', desc: '7 главных вопросов роадмапа, 81 дополнительный вопрос по темам блока', status: 'active', link: '/kubernetes/23-interview' },
  { title: '24. Жизненный цикл кластера', desc: 'Обновления, version skew, устаревшие API, бэкап etcd, сертификаты kubeadm', status: 'active', link: '/kubernetes/24-cluster-lifecycle' },
  { title: '25. Экосистема вокруг кластера', desc: 'external-dns, Helm-чарты в OCI, KEDA (scale to zero), Karpenter, Reloader', status: 'active', link: '/kubernetes/25-ecosystem' },
]
</script>

# Kubernetes

От первого `kubectl apply` до RBAC, автоскейлинга, Helm и жизненного цикла продакшен-кластера.

<RoadmapChain :items="lessons" />
