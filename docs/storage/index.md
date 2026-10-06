---
title: "Хранилища"
description: "LVM, RAID, Ceph, MinIO S3, StatefulSet, CSI, Patroni, WAL-G бэкапы БД и disaster recovery через Velero"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Основы хранения: блок, файл, объект, IOPS, RAID", "desc": "Блок/файл/объект, IOPS vs throughput vs latency, HDD/SSD/NVMe, RAID, EC, stateful", "status": "active", "link": "/storage/01-storage-basics"},
  {"title": "02. LVM, файловые системы и RAID на Linux", "desc": "LVM, lvextend -r, thin, снапшоты, pvmove, growpart, mdadm, ZFS", "status": "active", "link": "/storage/02-lvm-filesystems"},
  {"title": "03. NFS и MinIO: файловое и объектное хранилище своими руками", "desc": "NFS в k8s, своё S3: erasure coding, mc, политики, версии, lock, lifecycle", "status": "active", "link": "/storage/03-nfs-minio"},
  {"title": "04. Ceph: распределённое хранилище", "desc": "MON/MGR/OSD, PG, CRUSH, cephadm, ceph -s, RBD/CephFS/RGW", "status": "active", "link": "/storage/04-ceph"},
  {"title": "05. Stateful в Kubernetes: CSI, StatefulSet, Rook-Ceph, снапшоты", "desc": "CSI, StorageClass, StatefulSet, Rook-Ceph, VolumeSnapshot, Pending/Multi-Attach", "status": "active", "link": "/storage/05-k8s-stateful"},
  {"title": "06. Бэкапы и репликация БД: PITR, Patroni, CloudNativePG", "desc": "WAL-G/pgBackRest в S3, PITR, проверка бэкапов, Patroni, CloudNativePG", "status": "active", "link": "/storage/06-db-backup-replication"},
  {"title": "07. Velero и disaster recovery", "desc": "3-2-1-1-0, Velero + MinIO, тома через Kopia/CSI, DR-план, учения", "status": "active", "link": "/storage/07-velero-dr"},
  {"title": "08. Практика: 5 лаб по хранилищам и stateful", "desc": "5 лаб: LVM + mdadm, MinIO для бэкапов, Ceph из 3 нод, PITR через WAL-G, Velero restore", "status": "active", "link": "/storage/08-practice-labs"},
  {"title": "09. Вопросы с собеседований: хранилища и stateful", "desc": "Главные вопросы с развёрнутыми ответами + 42 коротких + ситуационные задачи", "status": "active", "link": "/storage/09-interview"},
]
</script>

# Хранилища и Stateful

LVM, RAID, Ceph, MinIO S3, StatefulSet, CSI, Patroni, WAL-G бэкапы БД и disaster recovery через Velero

<RoadmapChain :items="lessons" />
