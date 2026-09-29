---
title: "Виртуализация"
description: "KVM, QEMU, libvirt, сетевые мосты и VLAN, кластер Proxmox VE, LXC и автоматизация через Packer, Terraform и Ansible"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [{"title": "01. Виртуализация: зачем, как устроена, кто на рынке", "desc": "Блок → Виртуализация on-prem → тема 01. Опирается на", "status": "active", "link": "/virtualization/01-virtualization-intro"}, {"title": "02. KVM, QEMU и libvirt руками: virsh, cloud-init, qcow2, снапшоты", "desc": "Блок → Виртуализация on-prem → тема 02. Опирается на 01virtualizationintro.md,", "status": "active", "link": "/virtualization/02-kvm-qemu-libvirt"}, {"title": "03. Сеть для VM: libvirt-сети, bridge, macvtap, VLAN, bonding", "desc": "Блок → Виртуализация on-prem → тема 03. Опирается на", "status": "active", "link": "/virtualization/03-virt-networking"}, {"title": "04. Proxmox VE: VM, LXC, шаблоны, хранилища, кластер, HA, бэкапы, API", "desc": "Блок → Виртуализация on-prem → тема 04. Опирается на 02kvmqemulibvirt.md", "status": "active", "link": "/virtualization/04-proxmox"}, {"title": "05. Системные контейнеры: LXC, Incus, LXC в Proxmox", "desc": "Блок → Виртуализация on-prem → тема 05. Опирается на", "status": "active", "link": "/virtualization/05-lxc-containers"}, {"title": "06. Автоматизация: шаблоны, cloud-init, Packer, Terraform, Ansible, VMware", "desc": "Блок → Виртуализация on-prem → тема 06. Опирается на 02kvmqemulibvirt.md", "status": "active", "link": "/virtualization/06-virt-automation"}, {"title": "07. Практика: 5 лаб по виртуализации on-prem", "desc": "Блок → Виртуализация on-prem → практика.", "status": "active", "link": "/virtualization/07-practice-labs"}, {"title": "08. Вопросы с собеседований: виртуализация on-prem", "desc": "Блок → Виртуализация on-prem → собеседование.", "status": "active", "link": "/virtualization/08-interview"}]
</script>

# Виртуализация On-Prem

KVM, QEMU, libvirt, сетевые мосты и VLAN, кластер Proxmox VE, LXC и автоматизация через Packer, Terraform и Ansible

<RoadmapChain :items="lessons" />
