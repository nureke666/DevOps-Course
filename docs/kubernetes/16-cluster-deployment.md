---
title: "16. Развёртывание кластера"
description: "kubeadm, kubespray, managed Kubernetes: сравнение подходов, обновление, drain/cordon, сертификаты"
---

# 16. Развёртывание кластера: kubeadm, kubespray, managed

> Роадмап → 6. Kubernetes → Теория → **Развертывание**: «Изучить способы развертывания
> кубера: через `kubeadm`, через `kubespray`, `managed kubernetes`».
> **После темы ты умеешь:** объяснить, что делает каждый способ, что берёт на себя облако
> и из чего состоит эксплуатация самосборного кластера.

---

## 🗺️ Карта темы

```text:no-line-numbers
  СКОЛЬКО РАБОТЫ НА ТЕБЕ
  ▲
  │  ┌──────────────────────────────────────────┐
  │  │ «С нуля» (kubernetes-the-hard-way)       │ учебный способ, в проде не делают
  │  ├──────────────────────────────────────────┤
  │  │ kubeadm         — руками, но по шагам    │ понимаешь устройство кластера
  │  ├──────────────────────────────────────────┤
  │  │ kubespray       — Ansible поверх kubeadm │ повторяемо, много нод, on-prem
  │  ├──────────────────────────────────────────┤
  │  │ managed (EKS/GKE/Yandex/VK/Sber)         │ control plane берёт на себя облако
  │  └──────────────────────────────────────────┘
  ▼
```

---

## 1. kubeadm — стандартный установщик

**Что это:** официальная утилита, которая поднимает control plane и подключает ноды.
Не ставит ОС, не настраивает сеть между машинами, не выбирает CNI — только кубер.

### Подготовка ноды (то, что почти дословно из блока Linux)

```bash
# 1. swap выключен — требование kubelet
sudo swapoff -a && sudo sed -i '/ swap / s/^/#/' /etc/fstab

# 2. модули ядра
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
sudo modprobe overlay && sudo modprobe br_netfilter

# 3. sysctl
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system

# 4. container runtime
sudo apt install -y containerd
containerd config default | sudo tee /etc/containerd/config.toml
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd

# 5. пакеты кубера — из репозитория pkgs.k8s.io; он СВОЙ на каждую минорную версию
sudo apt install -y apt-transport-https ca-certificates curl gpg
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key \
  | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' \
  | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt update
sudo apt install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

### Установка

```bash
sudo kubeadm init \
  --pod-network-cidr=10.244.0.0/16 \
  --control-plane-endpoint=k8s-api.example.com:6443 \
  --upload-certs

mkdir -p ~/.kube && sudo cp /etc/kubernetes/admin.conf ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

# CNI ставится отдельно — без него ноды останутся NotReady
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.32.2/manifests/calico.yaml

# подключение рабочих нод
sudo kubeadm join k8s-api.example.com:6443 --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>

kubeadm token create --print-join-command      # если токен потерялся (живёт 24 часа)
```

### ⭐ Что именно делает `kubeadm init`

```text:no-line-numbers
1. Предполётные проверки (preflight): swap, порты, версии, runtime
2. Генерация PKI: CA кластера, сертификаты apiserver, kubelet, etcd → /etc/kubernetes/pki
3. Создание kubeconfig'ов: admin.conf, kubelet.conf, controller-manager.conf, scheduler.conf
4. Запись СТАТИЧЕСКИХ ПОДОВ в /etc/kubernetes/manifests:
      etcd, kube-apiserver, kube-controller-manager, kube-scheduler
5. Запуск kubelet → kubelet поднимает эти поды → control plane ожил
6. Настройка bootstrap-токенов для подключения нод
7. Установка аддонов: CoreDNS и kube-proxy
```

Вот почему тема 02 — обязательная база: `kubeadm init` буквально собирает
описанную там архитектуру.

### Эксплуатация

```bash
# ⭐ обновление — строго на ОДНУ минорную за раз: v1.36.x → v1.37.x
#    (с v1.35 на v1.37 — только через v1.36; перескок kubeadm сделать не даст)

# 1. первый control plane: репозиторий → kubeadm → план → apply
sudo sed -i 's|/v1.36/|/v1.37/|' /etc/apt/sources.list.d/kubernetes.list
sudo apt-mark unhold kubeadm && sudo apt update \
  && sudo apt install -y kubeadm='1.37.x-*' && sudo apt-mark hold kubeadm   # x — последний патч: apt-cache madison kubeadm
sudo kubeadm upgrade plan
sudo kubeadm upgrade apply v1.37.x        # остальные control plane: sudo kubeadm upgrade node

# 2. каждая нода по очереди (сначала остальные control plane, потом рабочие):
#    пакет kubeadm='1.37.x-*' → sudo kubeadm upgrade node → drain →
#    kubelet и kubectl='1.37.x-*' → systemctl daemon-reload && systemctl restart kubelet → uncordon
kubectl drain node2 --ignore-daemonsets --delete-emptydir-data    # перед обслуживанием
kubectl uncordon node2

kubeadm certs check-expiration            # ⭐ сертификаты живут год
kubeadm certs renew all                   # upgrade apply/node продлевают их заодно
```

| Плюсы | Минусы |
|-------|--------|
| Официальный, предсказуемый | Всё остальное (ОС, сеть, LB, мониторинг) — на тебе |
| Отлично учит устройству кластера | Ручное масштабирование на десятки нод неудобно |
| Подходит для небольших кластеров | Обновления и сертификаты — твоя забота |

---

## 2. kubespray — Ansible поверх kubeadm

**Что это:** набор Ansible-ролей (проект Kubernetes SIG), который под капотом
использует kubeadm, но автоматизирует всё вокруг: подготовку ОС, установку runtime,
CNI, HA control plane, аддоны, обновления.

```bash
git clone https://github.com/kubernetes-sigs/kubespray.git && cd kubespray
pip install -r requirements.txt
cp -r inventory/sample inventory/mycluster

declare -a IPS=(10.0.0.11 10.0.0.12 10.0.0.13)
CONFIG_FILE=inventory/mycluster/hosts.yaml \
  python3 contrib/inventory_builder/inventory.py ${IPS[@]}

# основные настройки:
#   inventory/mycluster/group_vars/k8s_cluster/k8s-cluster.yml  (версия, CNI, домены)
#   inventory/mycluster/group_vars/k8s_cluster/addons.yml       (ingress, metrics, dashboard)

ansible-playbook -i inventory/mycluster/hosts.yaml --become cluster.yml
ansible-playbook -i inventory/mycluster/hosts.yaml --become scale.yml     # добавить ноды
ansible-playbook -i inventory/mycluster/hosts.yaml --become upgrade-cluster.yml
ansible-playbook -i inventory/mycluster/hosts.yaml --become reset.yml     # ⚠️ снести всё
```

Это прямое применение блока Ansible: inventory, group_vars, роли, плейбуки.

| Плюсы | Минусы |
|-------|--------|
| Повторяемость: кластер описан кодом | Долгая установка, много «магии» в ролях |
| HA control plane и etcd из коробки | Нужно знать Ansible, чтобы чинить |
| Обновления и масштабирование плейбуками | Отладка сложнее, чем у чистого kubeadm |
| Гибкий выбор CNI и аддонов | Версии кластера привязаны к релизам kubespray |

**Альтернативы в той же нише:** `k3s`/`RKE2` (легковесные дистрибутивы),
`Talos` (иммутабельная ОС под кубер), `kOps` (кластеры в облаках),
Cluster API (кубер, управляющий кластерами).

---

## 3. Managed Kubernetes

**Что это:** облако разворачивает и обслуживает control plane, а ты платишь
и работаешь с готовым API.

| Облако | Сервис |
|--------|--------|
| AWS | EKS |
| Google | GKE |
| Azure | AKS |
| Yandex Cloud | Managed Service for Kubernetes |
| VK Cloud / Cloud.ru / Selectel | свои managed-сервисы |

| Облако берёт на себя | Остаётся тебе |
|----------------------|---------------|
| API server, etcd, scheduler, controller-manager | Манифесты и чарты приложений |
| Обновления control plane, сертификаты | Обновление версий нод и node pool'ов |
| Доступность control plane (SLA) | Ресурсы, лимиты, автоскейлинг |
| Интеграция LoadBalancer и дисков (CSI) | RBAC, сетевые политики, безопасность |
| Бэкапы etcd | Мониторинг и логи приложений, стоимость |

```bash
# примеры создания
eksctl create cluster --name demo --nodes 3 --node-type t3.medium
gcloud container clusters create demo --num-nodes=3
yc managed-kubernetes cluster create --name demo ...
```

| Плюсы | Минусы |
|-------|--------|
| Не надо обслуживать control plane | Платно; цена растёт с масштабом |
| SLA и поддержка | Меньше контроля: версии, флаги API, CNI |
| Готовые интеграции (LB, диски, IAM, логи) | Привязка к провайдеру |
| Быстрый старт | Часть настроек недоступна |

> 💬 **Позиция для собеса:** «В проде по умолчанию беру managed, если он есть:
> control plane — самая неблагодарная часть эксплуатации. kubeadm и kubespray
> использую там, где облака нет: on-prem, изолированный контур, требования регуляторов.
> Понимать устройство надо в любом случае — инциденты разбираются одинаково».

---

## 4. Что входит в «кластер», кроме кубера

Голый кластер бесполезен. Минимальный набор, который ставят сразу:

| Слой | Компоненты |
|------|------------|
| Сеть | CNI (Calico/Cilium), CoreDNS |
| Вход | Ingress Controller, cert-manager, MetalLB (для bare-metal) |
| Хранилище | CSI-драйвер, StorageClass по умолчанию |
| Наблюдаемость | metrics-server, Prometheus + Grafana, логи (Loki/EFK) |
| Доставка | ArgoCD/Flux или доступ пайплайна |
| Безопасность | RBAC, Pod Security Admission, NetworkPolicy, сканер образов |
| Эксплуатация | бэкап etcd (или Velero), автоскейлер нод, PDB для системных компонентов |

---

## 5. Сравнительная таблица

| | kubeadm | kubespray | managed |
|---|---|---|---|
| Кто ставит control plane | ты | Ansible | облако |
| Кто обновляет | ты | плейбук | облако (по кнопке) |
| Сертификаты | ты (год!) | плейбук | облако |
| etcd и его бэкап | ты | ты (плейбуки помогают) | облако |
| HA | настраиваешь сам | из коробки | есть по умолчанию |
| Сколько нод разумно | до 10-20 | десятки и сотни | любое |
| Стоимость | железо | железо | железо + плата за сервис |
| Скорость старта | часы | часы | минуты |
| Где применяют | обучение, малый on-prem | крупный on-prem | большинство компаний в облаке |

---

## 6. Обслуживание ноды: drain и cordon

```bash
kubectl cordon node2                      # не планировать новые поды
kubectl drain node2 --ignore-daemonsets --delete-emptydir-data
# ... обновление ядра / kubelet / перезагрузка ...
kubectl uncordon node2
```

| Команда | Что делает |
|---------|------------|
| `cordon` | Помечает ноду `SchedulingDisabled`; работающие поды не трогает |
| `drain` | Cordon + вытеснение подов (с учётом PodDisruptionBudget) |
| `--ignore-daemonsets` | DaemonSet-поды не вытесняются — их всё равно пересоздадут на этой ноде |
| `--delete-emptydir-data` | Согласие на потерю данных в `emptyDir` |
| `uncordon` | Вернуть ноду в работу |

> ⚠️ Без **PodDisruptionBudget** `drain` может одновременно снести все реплики
> приложения. PDB — обязательная часть подготовки к обслуживанию (тема 19).

---

## 💼 Как это в DevOps

- Даже в managed-кластере знание kubeadm окупается: понимаешь, где что лежит
  и как разбирать инциденты уровня ноды.
- Кластер — это не «поставил и забыл»: обновления версий (минорный релиз примерно
  раз в 4 месяца: v1.36 — апрель 2026, v1.37 — август 2026; каждую минорную поддерживают
  около 14 месяцев), сертификаты, обновление нод, ротация ключей, проверка бэкапа etcd.
- Обновление кластера всегда идёт по одной минорной за раз (v1.36.x → v1.37.x) и по
  цепочке: control plane → ноды по одной (`drain` → обновление → `uncordon`) → проверка
  нагрузок. Отстал на три минорных — значит, три обновления подряд, а не одно.
- Версия кубера и версия kubectl должны отличаться не более чем на одну минорную.
- В резюме ценится фраза не «умею ставить кластер», а «обновлял прод-кластер
  без даунтайма и восстанавливал etcd из бэкапа».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Поднять кластер вручную | `kubeadm init` + CNI + `kubeadm join` |
| Получить команду join заново | `kubeadm token create --print-join-command` |
| Поднять много нод повторяемо | kubespray (`cluster.yml`) |
| Добавить ноды kubespray | `scale.yml` |
| Обновить кластер kubespray | `upgrade-cluster.yml` |
| Проверить срок сертификатов | `kubeadm certs check-expiration` |
| Продлить сертификаты | `kubeadm certs renew all` |
| Обновить кластер kubeadm | `kubeadm upgrade plan` → `apply v1.37.x` (только +1 минорная за раз) |
| Вывести ноду на обслуживание | `kubectl drain NODE --ignore-daemonsets` |
| Вернуть ноду | `kubectl uncordon NODE` |
| Быстрый кластер в облаке | `eksctl create cluster` / `gcloud container clusters create` |

---

## 🧠 Что запомнить

1. Три способа: **kubeadm** (руками), **kubespray** (Ansible поверх kubeadm), **managed**.
2. `kubeadm init` = PKI + kubeconfig'и + статические поды control plane + аддоны.
3. kubeadm **не ставит CNI**: без него ноды остаются `NotReady`.
4. Подготовка ноды: swap off, модули `overlay`/`br_netfilter`, sysctl, containerd
   с `SystemdCgroup = true`.
5. Токен join живёт 24 часа; новый — `kubeadm token create --print-join-command`.
6. Сертификаты kubeadm живут год — это реальная причина годовых аварий.
7. kubespray хорош повторяемостью и HA, но требует знания Ansible.
8. Managed снимает control plane, etcd и его бэкап, но не снимает ответственности
   за приложения, ресурсы, RBAC и стоимость.
9. Кластер — это ещё и CNI, Ingress, CSI, мониторинг, бэкапы: голый кубер бесполезен.
10. Обновление нод — через `drain` → обслуживание → `uncordon`, и обязательно с PDB.
11. Разница версий kubectl и кластера — не больше одной минорной.
12. Обновление kubeadm — строго на одну минорную за раз (v1.36.x → v1.37.x); apt-репозиторий
    pkgs.k8s.io свой на каждую минорную, его переключают перед обновлением пакетов.
13. Понимание архитектуры (тема 02) важнее умения запустить установщик.

---

## Задачи

> Практику этой темы можно делать на виртуалках (multipass/Vagrant) — стенд из блока
> Ansible подходит идеально. Если ставить кластер негде, выполняй «бумажные» задания:
> они всё равно готовят к собеседованию.

---

### Блок A. Теория

**A1.** Назови три способа развернуть кластер и в чём разница.

<details><summary>Ответ</summary>

`kubeadm` — официальный установщик, ставишь руками; `kubespray` — Ansible-роли
поверх kubeadm с автоматизацией всего окружения; `managed` — облако само
разворачивает и обслуживает control plane.

</details>

**A2.** ⭐ Что делает `kubeadm init`? Перечисли шаги.

<details><summary>Ответ</summary>

Preflight-проверки → генерация PKI → создание kubeconfig'ов → запись
статических подов control plane в `/etc/kubernetes/manifests` → запуск kubelet →
настройка bootstrap-токенов → установка аддонов (CoreDNS, kube-proxy).

</details>

**A3.** Почему после `kubeadm init` ноды остаются `NotReady`?

<details><summary>Ответ</summary>

Не установлен CNI-плагин: kubelet сообщает о неготовности сети,
и нода остаётся `NotReady`.

</details>

**A4.** Какие подготовительные действия нужны на ноде до установки?

<details><summary>Ответ</summary>

Отключить swap, загрузить модули `overlay` и `br_netfilter`, настроить
sysctl (форвардинг и bridge-nf-call), установить и настроить container runtime,
поставить kubelet/kubeadm/kubectl и зафиксировать их версии.

</details>

**A5.** Почему нужно выключать swap?

<details><summary>Ответ</summary>

kubelet рассчитывает ресурсы из предположения, что памяти ровно столько,
сколько физической: swap ломает планирование и лимиты (поддержка swap появляется
постепенно, но по умолчанию его выключают).

</details>

**A6.** Зачем модули `overlay` и `br_netfilter`?

<details><summary>Ответ</summary>

`overlay` нужен файловой системе контейнеров, `br_netfilter` — чтобы трафик
через мост проходил через iptables (иначе не работают правила Service и политики).

</details>

**A7.** Что делает `net.bridge.bridge-nf-call-iptables = 1`?

<details><summary>Ответ</summary>

Заставляет пакеты, идущие через Linux-мост, обрабатываться правилами
iptables — без этого не работают kube-proxy и NetworkPolicy.

</details>

**A8.** Почему важен `SystemdCgroup = true` в конфиге containerd?

<details><summary>Ответ</summary>

kubelet и runtime должны использовать один cgroup-драйвер; при
systemd-инициализации ОС это `systemd`. Несовпадение приводит к нестабильности
и отказу kubelet.

</details>

**A9.** Где лежат сертификаты кластера и сколько они живут?

<details><summary>Ответ</summary>

В `/etc/kubernetes/pki`; по умолчанию срок действия — один год
(CA — 10 лет).

</details>

**A10.** Что такое статические поды и какие компоненты так запускаются?

<details><summary>Ответ</summary>

Поды, которыми kubelet управляет напрямую из каталога манифестов:
`etcd`, `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`.

</details>

**A11.** Сколько живёт токен для `kubeadm join` и как получить новый?

<details><summary>Ответ</summary>

24 часа; новый — `kubeadm token create --print-join-command`.

</details>

**A12.** Что такое `--control-plane-endpoint` и зачем он нужен для HA?

<details><summary>Ответ</summary>

Общий адрес (DNS-имя или VIP) для обращения к API. Нужен, чтобы ноды
и клиенты не были привязаны к одной control-plane машине и HA был возможен.

</details>

**A13.** Что такое kubespray и что он использует под капотом?

<details><summary>Ответ</summary>

Набор Ansible-ролей от SIG Kubernetes, который автоматизирует установку
кластера; внутри использует kubeadm.

</details>

**A14.** Какие плейбуки есть в kubespray и что каждый делает?

<details><summary>Ответ</summary>

`cluster.yml` — установка; `scale.yml` — добавление нод;
`upgrade-cluster.yml` — обновление; `remove-node.yml` — удаление ноды;
`reset.yml` — полный откат установки.

</details>

**A15.** Плюсы и минусы kubespray по сравнению с чистым kubeadm.

<details><summary>Ответ</summary>

Плюсы: повторяемость, HA из коробки, обновления и масштабирование
плейбуками, выбор CNI и аддонов. Минусы: сложнее отлаживать, нужна экспертиза
в Ansible, установка дольше, зависимость от релизов kubespray.

</details>

**A16.** ⭐ Что берёт на себя managed-кластер, а что остаётся тебе?

<details><summary>Ответ</summary>

Облако: control plane (API, etcd, scheduler, controller-manager),
его обновления и доступность, бэкапы etcd, интеграции LB/CSI/IAM.
Ты: приложения, версии нод, ресурсы и лимиты, автоскейлинг, RBAC,
сетевые политики, мониторинг, стоимость.

</details>

**A17.** Назови четыре managed-сервиса Kubernetes.

<details><summary>Ответ</summary>

EKS (AWS), GKE (Google), AKS (Azure), Managed Kubernetes в Yandex Cloud
(а также VK Cloud, Selectel, Cloud.ru).

</details>

**A18.** Какие минусы у managed-подхода?

<details><summary>Ответ</summary>

Стоимость, меньший контроль над версиями и флагами API, ограниченный выбор
CNI и настроек, привязка к провайдеру.

</details>

**A19.** Что ещё нужно поставить в кластер, кроме самого кубера? Назови шесть слоёв.

<details><summary>Ответ</summary>

Сеть (CNI, CoreDNS), вход (Ingress Controller, cert-manager, MetalLB),
хранилище (CSI и StorageClass), наблюдаемость (metrics-server, Prometheus, логи),
доставка (ArgoCD/Flux или доступ CI), безопасность (RBAC, PSA, NetworkPolicy,
сканирование образов), эксплуатация (бэкапы, автоскейлер, PDB).

</details>

**A20.** ⭐ Чем `cordon` отличается от `drain`?

<details><summary>Ответ</summary>

`cordon` запрещает планирование новых подов на ноду, не трогая текущие;
`drain` дополнительно вытесняет поды с учётом PDB.

</details>

**A21.** Зачем `--ignore-daemonsets` при drain?

<details><summary>Ответ</summary>

Поды DaemonSet нельзя «переселить» — они по определению должны быть
на этой ноде, поэтому drain без флага откажется работать.

</details>

**A22.** Что может пойти не так при `drain` без PodDisruptionBudget?

<details><summary>Ответ</summary>

Могут быть вытеснены все реплики приложения одновременно — получится
полный простой сервиса.

</details>

**A23.** В каком порядке обновляют кластер?

<details><summary>Ответ</summary>

Сначала control plane (по одной ноде при HA), затем рабочие ноды
по одной: `drain` → обновление kubelet/ОС → `uncordon` → проверка нагрузок.
Перед всем этим — бэкап etcd и проверка совместимости версий. Обновляются строго
на одну минорную за раз (v1.36.x → v1.37.x): перескочить через версию kubeadm не даст.

</details>

**A24.** Какая допустимая разница версий kubectl и кластера?

<details><summary>Ответ</summary>

kubectl может отличаться от версии кластера не более чем на одну
минорную версию в любую сторону.

</details>

**A25.** Что такое k3s, RKE2, Talos, kOps, Cluster API — по одной строке?

<details><summary>Ответ</summary>

k3s — облегчённый дистрибутив кубера; RKE2 — дистрибутив с акцентом
на безопасность; Talos — иммутабельная ОС, управляемая только по API;
kOps — инструмент создания кластеров в облаках; Cluster API — управление
кластерами средствами самого Kubernetes.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
kubeadm init --pod-network-cidr=10.244.0.0/16
kubectl get nodes
# NAME    STATUS     ROLES           AGE
# node1   NotReady   control-plane   2m
```
Вопрос: чего не хватает?

<details><summary>Ответ</summary>

Не установлен CNI-плагин.

</details>

**B2.**
```bash
kubectl get pods -n kube-system
# coredns-xxx  0/1  Pending
```
Вопрос: связано ли это с B1?

<details><summary>Ответ</summary>

Да: CoreDNS не может запуститься, пока у подов нет сети.

</details>

**B3.**
```bash
kubeadm join ... --token abcdef.1234567890abcdef
# error: token is invalid or expired
```
Вопрос: почему и что делать?

<details><summary>Ответ</summary>

Токен bootstrap живёт сутки. Сгенерировать новый командой
`kubeadm token create --print-join-command`.

</details>

**B4.**
```bash
kubectl get nodes
# node2  Ready,SchedulingDisabled
```
Вопрос: что было сделано и как вернуть?

<details><summary>Ответ</summary>

Выполнен `kubectl cordon`. Вернуть — `kubectl uncordon node2`.

</details>

**B5.**
```bash
kubectl drain node2
# error: cannot delete Pods declare no controller (use --force)
```
Вопрос: о чём говорит ошибка?

<details><summary>Ответ</summary>

На ноде есть «голые» поды без контроллера: их некому пересоздать,
поэтому drain требует явного `--force`.

</details>

**B6.**
```bash
kubectl drain node2 --ignore-daemonsets
# evicting pod web-1
# error when evicting pod "web-1" (will retry after 5s): Cannot evict pod as it would
# violate the pod's disruption budget
```
Вопрос: это ошибка или защита?

<details><summary>Ответ</summary>

Это защита: PodDisruptionBudget не позволяет вытеснить под, так как
нарушится минимально допустимое число доступных реплик. Нужно дождаться,
пока появятся новые реплики на других нодах.

</details>

**B7.**
```bash
kubectl version
# Client Version: v1.37.0
# Server Version: v1.34.0
```
Вопрос: чем это грозит?

<details><summary>Ответ</summary>

Слишком большая разница версий (больше одной минорной): возможны
несовместимость API и странные ошибки. Нужно привести версию kubectl в соответствие.

</details>

**B8.**
```bash
# ровно через год после установки
kubectl get nodes
# Unable to connect to the server: x509: certificate has expired
```
Вопрос: что произошло и какая команда чинит?

<details><summary>Ответ</summary>

Истекли сертификаты кластера. Лечение: `kubeadm certs renew all`,
перезапуск статических подов control plane, обновление kubeconfig'ов.

</details>

---

### Блок C. Практика

#### C1. 🔑 Разбор статических подов (можно на kind)
```bash
docker exec -it devops-control-plane bash
ls /etc/kubernetes/manifests/
ls /etc/kubernetes/pki/
cat /etc/kubernetes/manifests/kube-apiserver.yaml
```
Выпиши: какие компоненты запущены статическими подами, где их сертификаты,
какие флаги показались важными.

#### C2. 🔑 kubeadm на виртуалках (если есть возможность)
Подними кластер из двух-трёх ВМ:
1. Подготовь ноды (swap, модули, sysctl, containerd).
2. `kubeadm init` на первой.
3. Поставь Calico.
4. Подключи вторую ноду.
5. Задеплой тестовое приложение.
Запиши каждую команду и все ошибки, которые встретил, — это самый ценный результат.

#### C3. Токен join
Получи новую команду подключения (`kubeadm token create --print-join-command`)
и разбери, из чего она состоит.

#### C4. Сертификаты
```bash
kubeadm certs check-expiration
```
Выпиши даты и подумай, как узнать об истечении заранее (мониторинг, напоминание).

#### C5. 🔑 drain и cordon
1. Запусти приложение на 3 реплики в кластере с 3 нодами.
2. `kubectl cordon node2` — что изменилось для новых подов?
3. `kubectl drain node2 --ignore-daemonsets` — куда переехали поды?
4. `kubectl uncordon node2` — вернулись ли поды обратно сами?
Запиши ответ на последний вопрос и объясни его.

<details><summary>Ответ</summary>

После `uncordon` поды сами обратно **не возвращаются**: кубер не перемещает
работающие поды. Балансировка произойдёт только при следующем пересоздании
(или с помощью descheduler).

</details>

#### C6. drain с PDB
1. Создай PodDisruptionBudget с `minAvailable: 2` для приложения из C5.
2. Сделай `drain` ноды, где две реплики.
3. Наблюдай, как кубер не даёт нарушить бюджет.
4. Объясни, зачем это нужно при обновлении кластера.

<details><summary>Ответ</summary>

При `minAvailable: 2` и трёх репликах drain вытеснит поды по одному,
дожидаясь готовности замены на других нодах.

</details>

#### C7. Kubespray «на бумаге»
Изучи структуру репозитория kubespray и выпиши:
1. Где задаётся версия кубера.
2. Где выбирается CNI.
3. Где включаются аддоны (ingress, metrics-server).
4. Какой плейбук добавляет ноды, какой обновляет кластер.
Это можно сделать без запуска, просто прочитав `inventory/sample`.

#### C8. Managed «на бумаге»
Открой документацию любого доступного облака и выпиши:
1. Как создать кластер (команда CLI).
2. Что такое node pool и как настроить автоскейлинг.
3. Кто отвечает за обновление control plane и нод.
4. Сколько стоит control plane в месяц.
Сравни с kubeadm-вариантом по трудозатратам.

#### C9. Обвязка кластера
Составь чек-лист «кластер готов к проду»: перечисли компоненты каждого слоя
из конспекта (§4) и напиши, что из них уже стоит в твоём kind-кластере.

#### C10. Симуляция обновления
На kind-кластере:
1. Посмотри версии нод (`kubectl get nodes -o wide`).
2. Опиши по шагам, как обновлял бы прод-кластер: что делаешь до, во время и после.
3. Отдельно пропиши план отката.

#### C11. Бэкап etcd (со звёздочкой)
Сними снапшот etcd на control-plane ноде kind:
```bash
docker exec devops-control-plane sh -c 'ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /tmp/etcd-backup.db'
```
Скопируй файл наружу и опиши процедуру восстановления (подробнее — тема 21).

<details><summary>Ответ</summary>

Восстановление: остановить control plane, выполнить `etcdctl snapshot restore`
в новый каталог данных, подменить каталог etcd и запустить компоненты заново.

</details>

#### C12. Сравнение (со звёздочкой)
Составь таблицу «kubeadm / kubespray / managed» под свою (реальную или
воображаемую) компанию: 10 нод on-prem и 30 нод в облаке. Что выберешь и почему?

---

### Блок D. Инциденты

**D1.** После установки кластера все поды в `Pending`, ноды `NotReady`. Первая гипотеза?

<details><summary>Ответ</summary>

Не установлен CNI (или его поды не запустились).

</details>

**D2.** kubelet не стартует, в логах — про cgroup driver. Что произошло?

<details><summary>Ответ</summary>

Несовпадение cgroup-драйверов kubelet и containerd. Привести к `systemd`
в конфиге containerd и перезапустить сервисы.

</details>

**D3.** Нода подключилась, но поды на ней не получают сеть. Где смотреть?

<details><summary>Ответ</summary>

Поды CNI на этой ноде, логи kubelet, наличие конфигурации в
`/etc/cni/net.d`, модули ядра и sysctl, сетевые правила между нодами.

</details>

**D4.** Через год кластер перестал отвечать на `kubectl`. Диагноз и лечение.

<details><summary>Ответ</summary>

Истекли сертификаты (год). `kubeadm certs renew all`, перезапуск
статических подов, обновление `~/.kube/config`.

</details>

**D5.** Во время обновления ноды приложение стало недоступно, хотя реплик было три.
Что не настроили?

<details><summary>Ответ</summary>

PodDisruptionBudget и/или anti-affinity: все реплики оказались на одной
ноде либо были вытеснены одновременно.

</details>

**D6.** После перезагрузки сервера кластер не поднялся: kubelet ругается на swap.
Что забыли?

<details><summary>Ответ</summary>

Swap включился обратно после перезагрузки — не была отключена запись
в `/etc/fstab`.

</details>

**D7.** В kubespray-кластере обновление сломалось на середине. Что делать
и как этого избежать?

<details><summary>Ответ</summary>

Прочитать вывод плейбука, исправить причину и запустить `upgrade-cluster.yml`
снова (плейбуки идемпотентны). Профилактика: обновлять сначала тестовый кластер,
делать бэкап etcd, обновлять по одной ноде.

</details>

**D8.** Managed-кластер обновили автоматически ночью, часть приложений упала.
Что можно было сделать заранее?

<details><summary>Ответ</summary>

Отключить автообновление или задать окно обслуживания, подписаться
на уведомления о версиях, заранее проверять устаревшие API
(`kubectl convert`, `pluto`, `kubent`), иметь PDB и несколько реплик.

</details>

**D9.** `kubectl drain` висит уже 20 минут. Причины?

<details><summary>Ответ</summary>

Мешает PDB (нет запаса реплик), под не завершается (долгий grace period,
финализаторы), «голые» поды, зависшие тома.

</details>

**D10.** После добавления ноды поды на неё не планируются. Что проверить?

<details><summary>Ответ</summary>

Taint'ы на ноде, метки и `nodeSelector`/`affinity` у подов, статус ноды
(`Ready`), `SchedulingDisabled` после cordon, нехватка ресурсов.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как развернуть кластер? Какие способы знаешь?

<details><summary>Ответ</summary>

kubeadm, kubespray (и подобные инструменты автоматизации), managed-сервисы облаков;
для обучения — установка «с нуля».

</details>

**2.** ⭐ Что делает kubeadm init?

<details><summary>Ответ</summary>

Проверки, PKI, kubeconfig'и, статические поды control plane, запуск kubelet,
bootstrap-токены, аддоны CoreDNS и kube-proxy.

</details>

**3.** Почему нужно отключать swap и включать br_netfilter?

<details><summary>Ответ</summary>

Swap ломает учёт памяти и планирование; `br_netfilter` нужен, чтобы трафик
через мост обрабатывался iptables (Service и политики).

</details>

**4.** Что такое kubespray?

<details><summary>Ответ</summary>

Набор Ansible-ролей для повторяемой установки и обслуживания кластера
поверх kubeadm.

</details>

**5.** ⭐ Что берёт на себя managed Kubernetes?

<details><summary>Ответ</summary>

Control plane, его обновления и доступность, etcd и бэкапы, интеграции
с облачными LB, дисками и IAM.

</details>

**6.** Как обновляют кластер?

<details><summary>Ответ</summary>

По шагам: бэкап, обновление control plane, затем ноды по одной
через `drain`/`uncordon`, с проверкой нагрузок и планом отката.

</details>

**7.** Что такое drain и cordon?

<details><summary>Ответ</summary>

`cordon` — запрет планирования новых подов; `drain` — ещё и вытеснение текущих.

</details>

**8.** Как вывести ноду на обслуживание без даунтайма?

<details><summary>Ответ</summary>

Несколько реплик, PodDisruptionBudget, anti-affinity, `drain` по одной ноде,
проверка после каждой.

</details>

**9.** Как долго живут сертификаты kubeadm и что делать при истечении?

<details><summary>Ответ</summary>

Год; `kubeadm certs renew all` с перезапуском control plane; регулярные
обновления кластера продлевают их автоматически.

</details>

**10.** Что ещё нужно поставить, кроме самого кубера?

<details><summary>Ответ</summary>

CNI, Ingress Controller, cert-manager, CSI и StorageClass, мониторинг и логи,
систему доставки, средства безопасности и бэкапы.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Могу перечислить шаги `kubeadm init` по памяти
- [ ] Знаю, почему нода `NotReady` без CNI
- [ ] Помню подготовку ноды: swap, модули, sysctl, cgroup driver
- [ ] Знаю про срок жизни сертификатов и команду продления
- [ ] Понимаю, что делает kubespray и какие у него плейбуки
- [ ] Могу объяснить зону ответственности managed-кластера
- [ ] Делал `cordon`/`drain`/`uncordon` и видел работу PDB
- [ ] Знаю порядок обновления кластера и план отката
- [ ] Составил чек-лист «что ещё нужно в кластере, кроме кубера»
