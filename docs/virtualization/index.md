---
title: "Виртуализация"
description: "KVM, QEMU, libvirt, сетевые мосты и VLAN, кластер Proxmox VE, LXC и автоматизация через Packer, Terraform и Ansible"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Виртуализация: зачем, как устроена, кто на рынке", "desc": "Type-1/2, VT-x/AMD-V, EPT/NPT, стек KVM+QEMU+libvirt, virtio, VM vs LXC vs Docker, VMware после Broadcom", "status": "active", "link": "/virtualization/01-virtualization-intro"},
  {"title": "02. KVM, QEMU и libvirt руками: virsh, cloud-init, qcow2, снапшоты", "desc": "⭐ virsh, virt-install + cloud-init, qcow2 и overlay, пулы, снапшоты, CPU/RAM, миграция, guest agent", "status": "active", "link": "/virtualization/02-kvm-qemu-libvirt"},
  {"title": "03. Сеть для VM: libvirt-сети, bridge, macvtap, VLAN, bonding", "desc": "⭐ Сети libvirt, bridge, macvtap, VLAN (trunk/access, VLAN-aware bridge), bonding, MTU, разбор по слоям", "status": "active", "link": "/virtualization/03-virt-networking"},
  {"title": "04. Proxmox VE: VM, LXC, шаблоны, хранилища, кластер, HA, бэкапы, API", "desc": "⭐ Nested-установка, репозитории PVE 9, шаблоны с cloud-init, хранилища, кластер и кворум, HA, vzdump/PBS, API", "status": "active", "link": "/virtualization/04-proxmox"},
  {"title": "05. Системные контейнеры: LXC, Incus, LXC в Proxmox", "desc": "Unprivileged и idmap, Incus вместо LXD, pct, nesting, bind mounts, выбор LXC/VM/Docker", "status": "active", "link": "/virtualization/05-lxc-containers"},
  {"title": "06. Автоматизация: шаблоны, cloud-init, Packer, Terraform, Ansible, VMware", "desc": "cloud-init глубоко, Packer, Terraform (libvirt 0.9, bpg/proxmox), динамический inventory, golden image, VMware vSphere", "status": "active", "link": "/virtualization/06-virt-automation"},
  {"title": "07. Практика: 5 лаб по виртуализации on-prem", "desc": "5 лаб: VM из облачного образа, bond + VLAN + bridge, Proxmox вложенно, учения бэкап/восстановление, Terraform + Ansible", "status": "active", "link": "/virtualization/07-practice-labs"},
  {"title": "08. Вопросы с собеседований: виртуализация on-prem", "desc": "10 главных вопросов с развёрнутыми ответами + 42 коротких + ситуационные задачи", "status": "active", "link": "/virtualization/08-interview"},
]
</script>

# Виртуализация On-Prem

KVM, QEMU, libvirt, сетевые мосты и VLAN, кластер Proxmox VE, LXC и автоматизация через Packer, Terraform и Ansible

<RoadmapChain :items="lessons" />
