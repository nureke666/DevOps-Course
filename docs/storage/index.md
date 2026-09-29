---
title: "Хранилища"
description: "LVM, RAID, Ceph, MinIO S3, StatefulSet, CSI, Patroni, WAL-G бэкапы БД и disaster recovery через Velero"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Основы хранения: блок, файл, объект, IOPS, RAID", "desc": "Блок → Хранилища и stateful → тема 01. Опирается на", "status": "active", "link": "/storage/01-storage-basics"}, {"title": "02. LVM, файловые системы и RAID на Linux", "desc": "Блок → Хранилища и stateful → тема 02. Опирается на", "status": "active", "link": "/storage/02-lvm-filesystems"}, {"title": "03. NFS и MinIO: файловое и объектное хранилище своими руками", "desc": "Блок → Хранилища и stateful → тема 03. Опирается на", "status": "active", "link": "/storage/03-nfs-minio"}, {"title": "04. Ceph: распределённое хранилище", "desc": "Блок → Хранилища и stateful → тема 04. Опирается на 01storagebasics.md", "status": "active", "link": "/storage/04-ceph"}, {"title": "05. Stateful в Kubernetes: CSI, StatefulSet, Rook-Ceph, снапшоты", "desc": "Блок → Хранилища и stateful → тема 05. Опирается на", "status": "active", "link": "/storage/05-k8s-stateful"}, {"title": "06. Бэкапы и репликация БД: PITR, Patroni, CloudNativePG", "desc": "Блок → Хранилища и stateful → тема 06. Опирается на", "status": "active", "link": "/storage/06-db-backup-replication"}, {"title": "07. Velero и disaster recovery", "desc": "Блок → Хранилища и stateful → тема 07. Опирается на", "status": "active", "link": "/storage/07-velero-dr"}, {"title": "08. Практика: 5 лаб по хранилищам и stateful", "desc": "Блок → Хранилища и stateful → практика.", "status": "active", "link": "/storage/08-practice-labs"}, {"title": "09. Вопросы с собеседований: хранилища и stateful", "desc": "Блок → Хранилища и stateful → собеседование.", "status": "active", "link": "/storage/09-interview"}]
</script>

# Хранилища и Stateful

LVM, RAID, Ceph, MinIO S3, StatefulSet, CSI, Patroni, WAL-G бэкапы БД и disaster recovery через Velero

<RoadmapChain :items="lessons" />
