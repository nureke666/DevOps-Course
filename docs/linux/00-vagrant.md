---
title: "00. Стенд: Vagrant + libvirt/KVM"
description: "Как поднять учебную VM learn-linux: установка Vagrant с провайдером libvirt, снапшоты, типовые поломки стенда"
---

# 🧰 Стенд для Linux-блока: Vagrant + libvirt/KVM

> Шпаргалка: как поднять учебную VM `learn-linux`, на которой
> делаются все задачи блока Linux (и дальше — Network и Ansible).
> **После заметки ты умеешь:** ставить Vagrant с провайдером libvirt, поднимать одну или
> несколько VM из `Vagrantfile`, делать снапшоты и откатываться, чинить типовые поломки стенда.

---

## 🗺️ Как это устроено

```text:no-line-numbers
  Vagrantfile (код стенда, лежит в git)
        │  vagrant up
        ▼
  Vagrant ──► провайдер libvirt ──► KVM/QEMU (ядро хоста)
        │                               │
        │                               ▼
        │                      VM learn-linux (Ubuntu 22.04)
        │                      2 CPU · 2048 МБ · сеть 192.168.121.0/24
        ▼
  vagrant ssh  ─────────────────────► ты внутри VM
  vagrant snapshot save/restore ────► «сохранёнка» перед каждой темой
```

**Почему Vagrant, а не «руками в virt-manager»:** стенд описан кодом — его можно удалить
и поднять заново одной командой, положить в git и получить тот же результат на другой машине.
Это та же идея, что потом будет в Terraform и Ansible: инфраструктура как код.

---

## 1. Установка (Ubuntu/Debian-хост)

### 1.1. Проверить аппаратную виртуализацию

```bash
grep -cE '(vmx|svm)' /proc/cpuinfo   # > 0 — процессор умеет; 0 — включи VT-x/AMD-V в BIOS
ls -l /dev/kvm                       # файл должен существовать
```

### 1.2. KVM + libvirt

```bash
sudo apt update
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients virt-manager dnsmasq-base
sudo usermod -aG libvirt,kvm "$USER"    # дать себе доступ к libvirt
# ⚠️ перелогинься (или newgrp libvirt), иначе группы не применятся
virsh list --all                        # без sudo, без ошибок — значит, доступ есть
```

### 1.3. Vagrant

Вариант А — официальный репозиторий HashiCorp (свежая версия):

```bash
wget -O - https://apt.releases.hashicorp.com/gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install -y vagrant
```

Вариант Б — если репозиторий HashiCorp недоступен из твоей сети: `sudo apt install vagrant`
из репозитория Ubuntu (версия старее, для учёбы хватает).

### 1.4. Плагин vagrant-libvirt

```bash
sudo apt install -y libvirt-dev ruby-dev build-essential   # чтобы плагин собрался
vagrant plugin install vagrant-libvirt
vagrant plugin list                                         # vagrant-libvirt (x.y.z, global)
echo 'export VAGRANT_DEFAULT_PROVIDER=libvirt' >> ~/.bashrc # чтобы не писать --provider
```

> Если плагин не собирается — смотри актуальную инструкцию в README проекта
> `vagrant-libvirt` на GitHub: список build-зависимостей иногда меняется.

---

## 2. Vagrantfile для блока

```bash
mkdir -p ~/Projects/devops/stands/learn-linux && cd ~/Projects/devops/stands/learn-linux
```

```ruby
# ~/Projects/devops/stands/learn-linux/Vagrantfile
Vagrant.configure("2") do |config|
  config.vm.box      = "generic/ubuntu2204"
  config.vm.define   "learn-linux"
  config.vm.hostname = "learn-linux"

  # Папка проекта → /vagrant в VM. rsync — односторонняя копия хост → VM
  # (обновить: vagrant rsync, следить за изменениями: vagrant rsync-auto)
  config.vm.synced_folder ".", "/vagrant", type: "rsync"

  config.vm.provider :libvirt do |v|
    v.cpus   = 2
    v.memory = 2048
  end
end
```

Две VM для сетевых тем 17-22 (`web` + `app` в приватной сети) — готовый вариант в
[17_network_basics.md](/linux/17-network-basics), раздел «Мини-лаба».

> 💡 Нужна двусторонняя общая папка? `type: "nfs"` (на хосте нужен `nfs-kernel-server`)
> или `type: "virtiofs"`. Для учёбы rsync проще и ломается реже.

---

## 3. Шпаргалка команд

| Команда | Что делает |
|---------|-----------|
| `vagrant up` | создать/запустить VM по `Vagrantfile` |
| `vagrant ssh` / `vagrant ssh web` | зайти в VM (в мульти-VM — указать имя) |
| `vagrant status` | состояние VM этого проекта |
| `vagrant global-status --prune` | все VM на машине, из любых папок |
| `vagrant halt` | выключить (диск сохраняется) |
| `vagrant reload` | перезагрузить и применить изменения `Vagrantfile` |
| `vagrant suspend` / `resume` | заморозить / разморозить |
| `vagrant destroy -f` | удалить VM полностью |
| `vagrant provision` | заново прогнать provisioners (shell/ansible) |
| `vagrant ssh-config` | SSH-параметры VM (для обычного `ssh` и Ansible) |
| `vagrant box list` / `box prune` | скачанные образы / удалить старые версии |

### Снапшоты — главный инструмент блока

```bash
vagrant snapshot save clean          # ЗОЛОТОЙ снапшот — сразу после первого vagrant up
vagrant snapshot save before_13      # перед каждой темой
vagrant snapshot list
vagrant snapshot restore before_13   # откат после того, как всё сломано
vagrant snapshot delete before_05    # старые — удалять, они занимают место
vagrant snapshot save clean_net      # в мульти-VM без имени машины — снапшот всех VM
vagrant snapshot save web before_12  # …или только одной: [имя VM] имя_снапшота
```

### Ходить в VM обычным ssh (и натравить Ansible)

```bash
vagrant ssh-config --host learn-linux >> ~/.ssh/config
ssh learn-linux                      # теперь работает без vagrant
```

---

## 4. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| `Call to virConnectOpen failed: ... Permission denied` | нет в группе `libvirt` | `groups` → нет `libvirt`? `usermod -aG`, перелогиниться |
| `The provider 'libvirt' could not be found` | плагин не стоит или провайдер не выбран | `vagrant plugin install vagrant-libvirt`, `VAGRANT_DEFAULT_PROVIDER=libvirt` |
| Висит на `Waiting for domain to get an IP address...` | не запущена сеть libvirt / dnsmasq | `virsh net-list --all` → `virsh net-start default && virsh net-autostart default`; `sudo systemctl restart libvirtd` |
| `Network 192.168.121.0/24 is not available` | подсеть занята (VPN, docker) | в провайдере задать `v.management_network_address = "192.168.130.0/24"` |
| VirtualBox не стартует VM | KVM и VirtualBox одновременно не живут | для этого стенда используй только libvirt |
| Закончилось место на диске | образы и снапшоты в `/var/lib/libvirt/images` | `vagrant box prune`, удалить старые снапшоты, `virsh vol-list default` |
| Хост сам является VM, KVM не работает | нет nested virtualization | включить nested у гипервизора или учиться на железе |
| `/vagrant` пустая или старая | rsync копирует только при `up`/`reload` | `vagrant rsync` или `vagrant rsync-auto` в соседнем терминале |

---

## 💼 Как это в DevOps

- Vagrant встречается на проектах для **локальной проверки ролей Ansible** и воспроизводимых
  dev-стендов. В проде VM создают через Terraform/облако, но идея та же — стенд описан кодом.
- Снапшот перед экспериментом = привычка из прода «бэкап/снапшот диска перед обновлением».
- `vagrant ssh-config` + Ansible inventory — первый шаг к блоку Ansible.

## 🧠 Что запомнить

1. Стенд = `Vagrantfile` в git. Сломал — `destroy` и `up`, или откат снапшота.
2. Золотой снапшот `clean` делается сразу после первого `vagrant up`.
3. Перед каждой темой — `vagrant snapshot save before_NN`. Страх сломать стенд тормозит учёбу сильнее всего.
4. Доступ к libvirt = группа `libvirt` + перелогин. Это 80% проблем при первой установке.
