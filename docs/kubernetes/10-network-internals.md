---
title: "10. ⭐ Сеть под капотом"
description: "CNI-плагины, kube-proxy, CoreDNS — путь пакета от пода к поду и от пода к Service"
---

# 10. ⭐ Сеть под капотом: CNI, kube-proxy, CoreDNS

> Роадмап → 6. Kubernetes → Теория → **Сеть**: «Самая сложная тема внутри кубера,
> на её понимание может уйти значительное время». Часть «под капотом»:
> **CNI-плагины, kube-proxy, CoreDNS, работа сети на уровне нод**.
> **После темы ты умеешь:** проследить путь пакета от пода к поду и от пода к сервису
> и понимать, кто именно отвечает за каждый участок.

---

## 🗺️ Карта темы

```text:no-line-numbers
  ┌─────────────────────────── НОДА 1 ────────────────────────┐   ┌──── НОДА 2 ────┐
  │  POD A 10.244.1.5        POD B 10.244.1.6                 │   │ POD C 10.244.2.4│
  │    eth0│                    eth0│                         │   │    eth0│        │
  │   veth─┘                   veth─┘                         │   │   veth─┘        │
  │        └──── cni0 / bridge ─────┘                         │   │        │        │
  │                    │                                      │   │        │        │
  │           таблица маршрутов ноды                          │   │        │        │
  │                    │                                      │   │        │        │
  │        iptables/IPVS (программирует kube-proxy)           │   │        │        │
  │                    │                                      │   │        │        │
  │                  eth0 ноды 192.168.0.11 ──────────────────┼───┼── eth0 192.168.0.12
  └───────────────────────────────────────────────────────────┘   └─────────────────┘
                     ▲                          ▲                        ▲
                     │                          │                        │
                  CNI-плагин            kube-proxy               CoreDNS (обычный под)
              даёт подам IP и        правила Service→под      имена → ClusterIP
              связность между нодами
```

---

## 1. Четыре правила сетевой модели Kubernetes ⭐

Кубер **не реализует** сеть сам — он задаёт требования, которые обязан выполнить
CNI-плагин:

1. Каждый под получает **собственный IP**.
2. Любой под может обратиться к любому другому поду **напрямую по IP, без NAT**.
3. Агенты ноды (kubelet и т. д.) могут обращаться к подам на этой ноде.
4. IP, который под видит у себя, — тот же, что видят остальные (нет подмены адреса).

Отсюда «плоская сеть»: с точки зрения пода кластер выглядит как одна большая локальная
сеть. Никакого проброса портов, как в Docker, здесь нет.

**Три диапазона адресов, которые надо различать:**

| Диапазон | Что это | Пример |
|----------|---------|--------|
| Pod CIDR | Адреса подов, выдаёт CNI | `10.244.0.0/16` (по ноде — `/24`) |
| Service CIDR | Виртуальные адреса сервисов, не существуют на интерфейсах | `10.96.0.0/12` |
| Node network | Реальная сеть машин | `192.168.0.0/24` |

---

## 2. CNI-плагин: кто даёт подам сеть

**CNI (Container Network Interface)** — стандарт, по которому kubelet просит плагин
настроить сеть для пода.

Что происходит при старте пода:
```text:no-line-numbers
kubelet → CRI создаёт sandbox (pause-контейнер)
       → вызывает CNI-плагин:
            • создать veth-пару: один конец в namespace пода (eth0), другой на ноде
            • выдать IP из Pod CIDR этой ноды (IPAM)
            • прописать маршрут по умолчанию внутри пода
            • обеспечить связность до подов на других нодах
```

| Плагин | Как связывает ноды | Особенности |
|--------|--------------------|-------------|
| **Flannel** | VXLAN-оверлей (или host-gw) | Простой, без NetworkPolicy |
| **Calico** | Маршрутизация (BGP) или VXLAN/IPIP | ⭐ Популярен, полноценные NetworkPolicy, быстрый |
| **Cilium** | eBPF | ⭐ Может **заменить kube-proxy**, L7-политики, отличная наблюдаемость |
| **Weave Net** | Собственный оверлей | Проще, но реже используется в новых кластерах |
| **kindnet** | Простые маршруты | Только для kind |

**Оверлей vs маршрутизация:**

| | Оверлей (VXLAN/IPIP) | Маршрутизация (BGP, host-gw) |
|---|---|---|
| Как | Пакет пода заворачивается в пакет ноды | Ноды знают маршруты к Pod CIDR друг друга |
| Плюсы | Работает в любой сети | Быстрее, нет накладных расходов |
| Минусы | Оверхед, уменьшение MTU (отсюда «странные» зависания больших ответов) | Требуется поддержка со стороны сети |

```bash
ls /etc/cni/net.d/                          # конфиг CNI на ноде
kubectl get pods -n kube-system -l k8s-app=calico-node
kubectl get nodes -o jsonpath='{.items[*].spec.podCIDR}'
ip route                                    # на ноде: маршруты к подам
ip -d link show                             # vxlan-интерфейсы, если оверлей
```

> ⚠️ **MTU** — классическая беда оверлеев: внешний заголовок VXLAN «съедает» 50 байт.
> Симптом: мелкие запросы проходят, большие зависают. Разбор — тема 20 и блок Linux (17).

---

## 3. kube-proxy: как работает Service ⭐

**Service — это не процесс и не под.** Это правило в ядре каждой ноды.
ClusterIP не принадлежит никакому интерфейсу: пакет на этот адрес перехватывается
и переписывается (DNAT) на IP одного из подов.

```text:no-line-numbers
 под делает запрос на 10.96.0.42:80 (ClusterIP сервиса)
        │
        ▼
 netfilter на ноде-источнике:
   цепочка KUBE-SERVICES → KUBE-SVC-XXXX → случайный выбор →
   KUBE-SEP-YYYY → DNAT на 10.244.2.4:8080
        │
        ▼
 пакет уходит напрямую на нужный под (возможно, на другой ноде)
```

| Что важно | Пояснение |
|-----------|-----------|
| kube-proxy **не пропускает трафик** через себя | Он только программирует ядро; данные идут через netfilter/IPVS |
| Балансировка | Случайная (iptables) или по алгоритму (IPVS: rr, lc, sh) |
| Источник данных | Объекты Service и EndpointSlice из API |
| Где выполняется | На **каждой** ноде |
| Что при падении kube-proxy | Новые сервисы и изменения не применяются; старые правила продолжают работать |

**Режимы:**

| Режим | Суть | Когда |
|-------|------|-------|
| `iptables` | Цепочки NAT, линейный перебор правил | По умолчанию, до сотен сервисов |
| `ipvs` | Хеш-таблицы ядра, алгоритмы балансировки | Тысячи сервисов, нужна предсказуемость |
| `nftables` | Более новая реализация, замена iptables | Свежие кластеры |
| нет kube-proxy | Замена на eBPF (Cilium) | Максимальная производительность |

```bash
kubectl -n kube-system get ds kube-proxy
sudo iptables -t nat -L KUBE-SERVICES -n | head
sudo ipvsadm -Ln                           # если режим IPVS
kubectl get endpointslices -l kubernetes.io/service-name=web
```

**EndpointSlice.** Раньше список адресов за сервисом хранился в одном объекте Endpoints;
в больших кластерах он становился огромным и перегружал API. Теперь адреса разбиты
на срезы (EndpointSlice) по 100 адресов. `kubectl get endpoints` всё ещё работает
для совместимости.

---

## 4. CoreDNS: имена внутри кластера ⭐

CoreDNS — обычный Deployment в `kube-system`, доступный через Service `kube-dns`
(обычно `10.96.0.10`). kubelet прописывает его в `/etc/resolv.conf` каждого пода.

**Формат имён:**

```text:no-line-numbers
<service>.<namespace>.svc.cluster.local        ← сервис
<pod-ip-с-дефисами>.<namespace>.pod.cluster.local
<pod>.<service>.<namespace>.svc.cluster.local  ← под StatefulSet (headless)
```

Из пода можно обращаться короче:

| Откуда | Запрос | Куда попадёт |
|--------|--------|--------------|
| Тот же namespace | `backend` | `backend.<свой ns>.svc.cluster.local` |
| Другой namespace | `backend.prod` | `backend.prod.svc.cluster.local` |
| Полное имя | `backend.prod.svc.cluster.local.` | без поиска по суффиксам |

**`/etc/resolv.conf` внутри пода:**
```text:no-line-numbers
nameserver 10.96.0.10
search myapp.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

> ⚠️ **`ndots:5` — источник «медленного DNS».** Если в имени меньше 5 точек,
> резолвер сначала переберёт все суффиксы из `search`. Запрос к `api.example.com`
> (2 точки) породит 4 неудачных запроса и только потом верный. Лечение:
> ставить точку в конце (`api.example.com.`) или задавать `dnsConfig` с `ndots: 2`.

```yaml
spec:
  dnsPolicy: ClusterFirst        # по умолчанию
  dnsConfig:
    options:
      - { name: ndots, value: "2" }
```

```bash
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
kubectl -n kube-system get cm coredns -o yaml       # Corefile
kubectl run dns-test --rm -it --image=busybox:1.36 --restart=Never -- nslookup web
```

**Что настраивается в Corefile:** форвардеры во внешний DNS, кэш, `hosts`-записи,
плагины (`rewrite`, `template`). Для крупных кластеров ставят **NodeLocal DNSCache** —
DaemonSet с локальным кэшем на каждой ноде.

---

## 5. Путь пакета: три сценария ⭐

### A. Под → под на той же ноде
```text:no-line-numbers
pod A eth0 → veth → bridge cni0 → veth → pod B eth0
```
Без выхода из ноды, без NAT. Самый быстрый путь.

### B. Под → под на другой ноде
```text:no-line-numbers
pod A eth0 → veth → bridge → маршрут ноды →
    [оверлей: инкапсуляция VXLAN | маршрутизация: как есть] →
    физическая сеть → нода 2 → bridge → veth → pod C
```
Без NAT (правило 2 сетевой модели).

### C. Под → Service
```text:no-line-numbers
pod A → DNS-запрос в CoreDNS → получает ClusterIP 10.96.0.42
      → пакет на 10.96.0.42 → netfilter/IPVS на ноде: DNAT на IP пода
      → далее как сценарий A или B
```
Ответ проходит обратное преобразование, и приложение не догадывается о подмене.

### D. Снаружи → в кластер
Через NodePort, LoadBalancer или Ingress — это тема 11 и 12.

---

## 6. Инструменты диагностики сети

```bash
# временный под с сетевыми утилитами
kubectl run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- bash
  # внутри: dig, nslookup, curl, tcpdump, ip, ss, traceroute, mtr, iperf3

# проверки по шагам
nslookup web                             # DNS работает?
curl -v http://10.244.2.4:8080           # прямой IP пода работает?
curl -v http://10.96.0.42:80             # ClusterIP работает?
curl -v http://web.default.svc:80        # имя + ClusterIP?

# со стороны кластера
kubectl get endpointslices -A
kubectl -n kube-system logs -l k8s-app=kube-dns
kubectl get pods -o wide                 # какие IP и на каких нодах
```

**Алгоритм «сервис не отвечает» (сверху вниз):**

```text:no-line-numbers
1. kubectl get endpoints <svc>        пусто? → метки/readiness (тема 11)
2. curl по IP пода напрямую           не работает? → приложение или CNI
3. curl по ClusterIP                  не работает? → kube-proxy на ноде-источнике
4. nslookup <svc>                     не резолвится? → CoreDNS
5. проверить NetworkPolicy            есть default-deny? (тема 13)
6. с разных нод                       работает не отовсюду? → CNI между нодами / MTU
```

---

## 💼 Как это в DevOps

- 80 % «непонятных» проблем в кубере — сетевые, и почти все разбираются этим алгоритмом.
- Выбор CNI — решение на весь срок жизни кластера: смена плагина означает переустановку.
  В managed-кластерах его выбирают при создании.
- `ndots:5` и MTU — два эффекта, о которых стоит знать заранее: они дают самые
  «мистические» симптомы (медленно, но работает; работает, но не всегда).
- CoreDNS — единая точка отказа для имён: при его недоступности «ложится всё»,
  хотя поды живы. Поэтому его держат в нескольких репликах с anti-affinity,
  а на крупных кластерах добавляют NodeLocal DNSCache.
- Знание, что kube-proxy только программирует ядро, экономит часы:
  трафик не идёт «через компонент», значит и искать надо в правилах, а не в процессе.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Узнать IP подов и ноды | `kubectl get pods -o wide` |
| Проверить DNS из пода | `kubectl run netshoot --rm -it --image=nicolaka/netshoot -- nslookup web` |
| Посмотреть Pod CIDR нод | `kubectl get nodes -o jsonpath='{.items[*].spec.podCIDR}'` |
| Найти адреса за сервисом | `kubectl get endpointslices -l kubernetes.io/service-name=web` |
| Посмотреть правила Service | `iptables -t nat -L KUBE-SERVICES -n` / `ipvsadm -Ln` |
| Логи DNS | `kubectl -n kube-system logs -l k8s-app=kube-dns` |
| Конфиг CoreDNS | `kubectl -n kube-system get cm coredns -o yaml` |
| Уменьшить ndots | `dnsConfig.options: [{name: ndots, value: "2"}]` |
| Проверить CNI на ноде | `ls /etc/cni/net.d/`, `ip route`, `ip -d link` |
| Посмотреть MTU | `ip link show` внутри пода и на ноде |

---

## 🧠 Что запомнить

1. Кубер задаёт правила сети, а реализует их **CNI-плагин**.
2. Каждый под имеет свой IP; поды общаются **без NAT** — плоская сеть.
3. Три диапазона: Pod CIDR, Service CIDR, сеть нод. Service CIDR виртуален.
4. CNI создаёт veth-пару, выдаёт IP и обеспечивает связность между нодами.
5. Оверлей (VXLAN) работает везде, но режет MTU; маршрутизация (BGP) быстрее.
6. Service реализуется правилами ядра, которые пишет **kube-proxy**;
   сам он трафик не пропускает.
7. Режимы kube-proxy: iptables, IPVS, nftables; Cilium может его заменить.
8. Адреса подов за сервисом хранятся в **EndpointSlice**.
9. CoreDNS даёт имена вида `svc.namespace.svc.cluster.local`; это обычный под.
10. `ndots:5` вызывает лишние DNS-запросы — источник «медленного» резолва.
11. Падение CoreDNS выглядит как «упало всё», хотя приложения живы.
12. Алгоритм разбора: endpoints → IP пода → ClusterIP → DNS → NetworkPolicy → между нодами.

---

## Задачи

> Роадмап честно предупреждает: это самая сложная тема. Не пытайся пройти её за вечер —
> лучше вернуться к задачам дважды с интервалом в несколько дней.

---

### Блок A. Теория

**A1.** ⭐ Назови четыре правила сетевой модели Kubernetes.

<details><summary>Ответ</summary>

Каждый под имеет свой IP; поды общаются друг с другом напрямую без NAT;
агенты ноды могут обращаться к подам на ней; адрес, который под видит у себя,
совпадает с тем, что видят другие.

</details>

**A2.** Почему в кубере нет проброса портов, как в Docker?

<details><summary>Ответ</summary>

Потому что у каждого пода собственный IP в плоской сети: не нужно
мультиплексировать порты хоста, как в Docker на одном хосте.

</details>

**A3.** Какие три диапазона адресов существуют в кластере и чем они отличаются?

<details><summary>Ответ</summary>

Pod CIDR — реальные адреса подов, выдаёт CNI; Service CIDR — виртуальные адреса
сервисов, существующие только в правилах ядра; сеть нод — физическая сеть машин.

</details>

**A4.** Существует ли ClusterIP на каком-нибудь сетевом интерфейсе?

<details><summary>Ответ</summary>

Нет. Это виртуальный адрес: пакеты к нему перехватываются netfilter/IPVS
и переписываются на адрес конкретного пода.

</details>

**A5.** ⭐ Что делает CNI-плагин при создании пода? Опиши по шагам.

<details><summary>Ответ</summary>

Создаёт сетевой namespace пода (через pause-контейнер), делает veth-пару
(eth0 внутри пода и интерфейс на ноде), выделяет IP из Pod CIDR (IPAM),
прописывает маршруты и обеспечивает связность до подов на других нодах.

</details>

**A6.** Что такое veth-пара?

<details><summary>Ответ</summary>

Пара виртуальных интерфейсов, соединённых «проводом»: один конец
в namespace пода, другой — на ноде.

</details>

**A7.** Назови четыре CNI-плагина и их ключевое отличие.

<details><summary>Ответ</summary>

Flannel (простой оверлей, без политик), Calico (маршрутизация/BGP
и полноценные NetworkPolicy), Cilium (eBPF, может заменить kube-proxy, L7-политики),
Weave (собственный оверлей).

</details>

**A8.** Чем оверлейная сеть отличается от маршрутизируемой? Плюсы и минусы.

<details><summary>Ответ</summary>

Оверлей инкапсулирует пакеты подов в пакеты нод: работает в любой сети,
но добавляет накладные расходы и уменьшает MTU. Маршрутизация требует, чтобы сеть
знала о Pod CIDR, зато быстрее и прозрачнее.

</details>

**A9.** Почему при VXLAN возникают проблемы с MTU и как выглядит симптом?

<details><summary>Ответ</summary>

Внешний заголовок занимает часть полезной нагрузки (для VXLAN — около 50 байт).
Если MTU не уменьшен, большие пакеты фрагментируются или отбрасываются:
мелкие запросы проходят, крупные ответы зависают.

</details>

**A10.** ⭐ Что делает kube-proxy? Проходит ли трафик через его процесс?

<details><summary>Ответ</summary>

Следит за Service и EndpointSlice и программирует правила ядра
(iptables/IPVS/nftables). Трафик через его процесс **не идёт**.

</details>

**A11.** Какие режимы работы kube-proxy бывают и чем IPVS лучше iptables?

<details><summary>Ответ</summary>

iptables, IPVS, nftables (и полная замена на eBPF). IPVS использует
хеш-таблицы вместо длинных цепочек, лучше масштабируется и поддерживает
алгоритмы балансировки.

</details>

**A12.** Откуда kube-proxy берёт информацию о том, куда слать трафик?

<details><summary>Ответ</summary>

Из API-сервера: объекты Service и EndpointSlice (через watch).

</details>

**A13.** Что такое EndpointSlice и зачем он появился вместо Endpoints?

<details><summary>Ответ</summary>

Разбиение списка адресов сервиса на срезы (обычно по 100). Появился,
чтобы не гонять по кластеру гигантские объекты Endpoints при каждом изменении.

</details>

**A14.** Что перестанет работать при падении kube-proxy на одной ноде?

<details><summary>Ответ</summary>

На этой ноде перестанут обновляться правила: новые сервисы и изменения
не применятся. Уже настроенные правила продолжат работать; прямые обращения
к IP подов не затронуты.

</details>

**A15.** ⭐ Что такое CoreDNS и где он работает?

<details><summary>Ответ</summary>

DNS-сервер кластера; работает как обычный Deployment в `kube-system`
и доступен через Service `kube-dns` (обычно `10.96.0.10`).

</details>

**A16.** Как формируется полное DNS-имя сервиса?

<details><summary>Ответ</summary>

`<service>.<namespace>.svc.cluster.local`.

</details>

**A17.** Как обратиться к сервису из другого namespace?

<details><summary>Ответ</summary>

`<service>.<namespace>`, например `backend.prod`.

</details>

**A18.** Что такое `ndots:5` и какую проблему он создаёт?

<details><summary>Ответ</summary>

Если в имени меньше пяти точек, резолвер сначала подставит суффиксы
из `search`. Это порождает лишние запросы и задержки для внешних доменов.

</details>

**A19.** Как уменьшить `ndots` для конкретного пода?

<details><summary>Ответ</summary>

Через `spec.dnsConfig.options` с `name: ndots, value: "2"`.

</details>

**A20.** Что такое `dnsPolicy` и какие значения бывают?

<details><summary>Ответ</summary>

Политика DNS для пода: `ClusterFirst` (по умолчанию), `Default`
(взять настройки ноды), `None` (только `dnsConfig`), `ClusterFirstWithHostNet`
(для подов с `hostNetwork`).

</details>

**A21.** Что произойдёт при падении всех подов CoreDNS?

<details><summary>Ответ</summary>

Перестанут резолвиться имена: приложения будут получать ошибки резолва,
хотя все поды живы и доступны по IP. Внешне выглядит как «упало всё».

</details>

**A22.** Что такое NodeLocal DNSCache и зачем он нужен?

<details><summary>Ответ</summary>

DaemonSet с локальным DNS-кэшем на каждой ноде: уменьшает задержки,
снижает нагрузку на CoreDNS и число запросов через conntrack.

</details>

**A23.** ⭐ Опиши путь пакета от пода к поду на другой ноде.

<details><summary>Ответ</summary>

Под → veth → мост/интерфейс ноды → маршрут к Pod CIDR другой ноды
(с инкапсуляцией в случае оверлея) → физическая сеть → нода-получатель →
veth → под. Без NAT.

</details>

**A24.** Опиши путь пакета от пода к Service.

<details><summary>Ответ</summary>

Под резолвит имя в CoreDNS, получает ClusterIP; пакет к ClusterIP
перехватывается netfilter/IPVS на ноде-источнике и DNAT'ится на IP одного
из подов сервиса, дальше идёт как обычный трафик под-под.

</details>

**A25.** Назови алгоритм разбора «сервис не отвечает» по шагам.

<details><summary>Ответ</summary>

Endpoints/EndpointSlice → прямой запрос по IP пода → запрос по ClusterIP →
проверка DNS → NetworkPolicy → проверка с разных нод (CNI/MTU).

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
kubectl exec -it pod-a -- curl http://10.244.2.4:8080    # работает
kubectl exec -it pod-a -- curl http://10.96.0.42:80      # таймаут
```
Вопрос: что сломано?

<details><summary>Ответ</summary>

Правила Service на ноде-источнике: скорее всего, не работает kube-proxy
(или сервис/endpoints пусты).

</details>

**B2.**
```bash
kubectl exec -it pod-a -- curl http://10.96.0.42:80      # работает
kubectl exec -it pod-a -- curl http://web:80             # not resolved
```
Вопрос: что сломано?

<details><summary>Ответ</summary>

DNS: CoreDNS недоступен или неправильный `resolv.conf`/`dnsPolicy`.

</details>

**B3.**
```bash
kubectl exec -it pod-a -- curl http://web:80             # работает с ноды 1
# тот же запрос из пода на ноде 2 — таймаут
```
Вопрос: где искать проблему?

<details><summary>Ответ</summary>

Межнодовая связность: CNI между нодами, маршруты, MTU, firewall
между машинами или kube-proxy на ноде 2.

</details>

**B4.**
```bash
kubectl get endpointslices -l kubernetes.io/service-name=web
# ENDPOINTS: <none>
```
Вопрос: две наиболее вероятные причины?

<details><summary>Ответ</summary>

Метки в селекторе сервиса не совпадают с метками подов; поды не проходят
readiness-пробу.

</details>

**B5.**
```bash
kubectl exec -it app -- time nslookup api.example.com
# real  0m5.02s
```
Вопрос: что происходит и как починить?

<details><summary>Ответ</summary>

`ndots:5`: сначала перебираются search-суффиксы. Лечение: точка в конце имени,
`ndots: 2` через `dnsConfig`, NodeLocal DNSCache.

</details>

**B6.**
```bash
# внутри пода
cat /etc/resolv.conf
# nameserver 10.96.0.10
# search prod.svc.cluster.local svc.cluster.local cluster.local
# options ndots:5
kubectl exec -it app -- curl http://backend
```
Вопрос: какие DNS-запросы будут отправлены по порядку?

<details><summary>Ответ</summary>

`backend.prod.svc.cluster.local`, затем `backend.svc.cluster.local`,
затем `backend.cluster.local`, и только потом `backend.` (порядок подстановки
суффиксов из `search`, так как точек меньше пяти).

</details>

**B7.**
```text:no-line-numbers
# мелкие HTTP-запросы работают, скачивание большого файла зависает
```
Вопрос: наиболее вероятная причина?

<details><summary>Ответ</summary>

Неверный MTU при оверлейной сети (или фрагментация/блокировка ICMP
в сети между нодами).

</details>

**B8.**
```bash
kubectl -n kube-system delete pod -l k8s-app=kube-dns
kubectl exec -it app -- curl http://10.96.0.42
kubectl exec -it app -- curl http://web
```
Вопрос: какой запрос сработает?

<details><summary>Ответ</summary>

Запрос по ClusterIP сработает (правила ядра на месте), а по имени — нет,
пока CoreDNS не поднимется.

</details>

---

### Блок C. Практика

#### C1. 🔑 Карта сети своего кластера
Выпиши в заметку:
```bash
kubectl get nodes -o wide                                   # IP нод
kubectl get nodes -o jsonpath='{.items[*].spec.podCIDR}'    # Pod CIDR
kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}'  # начало Service CIDR
kubectl get pods -A -o wide | head -20                      # IP подов
kubectl -n kube-system get svc kube-dns                      # адрес DNS
```
Нарисуй схему: три диапазона и их назначение.

#### C2. 🔑 Под → под напрямую
1. Запусти два пода на **разных** нодах.
2. Из первого сделай `curl` на IP второго.
3. Убедись, что IP источника, который видит второй под, — это IP первого (без NAT).
   (Подсказка: поднять `nginx` и посмотреть `access.log`.)

<details><summary>Ответ</summary>

В логах nginx будет реальный IP пода-источника: между подами NAT не применяется.

</details>

#### C3. netshoot — твой основной инструмент
```bash
kubectl run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- bash
```
Внутри выполни: `ip a`, `ip route`, `cat /etc/resolv.conf`, `dig web`,
`curl -v http://web`, `traceroute <IP другого пода>`. Запиши, что показывает каждая команда.

#### C4. DNS-имена
Из пода проверь резолв:
1. `web`
2. `web.default`
3. `web.default.svc`
4. `web.default.svc.cluster.local`
5. `web.other-ns`
Запиши, какие сработали и почему.

<details><summary>Ответ</summary>

Сработают все варианты, кроме обращения к сервису из другого namespace
по короткому имени; для него нужен суффикс namespace.

</details>

#### C5. ndots на практике
1. Замерь `time nslookup api.example.com` из пода.
2. Посмотри в логах CoreDNS, сколько запросов пришло
   (`kubectl -n kube-system logs -l k8s-app=kube-dns | tail -20`; может потребоваться
   включить плагин `log` в Corefile).
3. Повтори с точкой на конце: `api.example.com.`
4. Добавь `dnsConfig` с `ndots: 2` и сравни.

#### C6. Правила iptables
На ноде посмотри цепочки:
```bash
docker exec -it devops-worker bash      # для kind
iptables -t nat -L KUBE-SERVICES -n | head -20
iptables -t nat -L | grep -c KUBE       # сколько всего правил
```
Найди правило для своего сервиса и проследи цепочку до KUBE-SEP.

#### C7. 🔑 Ломаем kube-proxy
1. Удали под kube-proxy на одной ноде (`kubectl -n kube-system delete pod kube-proxy-xxx`)
   — он вернётся, поэтому лучше временно отредактировать DaemonSet
   (`nodeSelector`, которому нода не соответствует).
2. Проверь из пода на этой ноде: запрос по ClusterIP и по IP пода.
3. Верни как было. Запиши симптом «изнутри».

<details><summary>Ответ</summary>

Симптом: из подов на этой ноде не работают обращения по ClusterIP
и DNS-имена сервисов (DNS сам доступен через сервис), при этом прямые обращения
к IP подов работают.

</details>

#### C8. Ломаем CoreDNS
1. `kubectl -n kube-system scale deploy coredns --replicas=0`
2. Проверь из пода: запрос по имени и по ClusterIP.
3. Верни реплики. Сформулируй, как выглядит инцидент «упал DNS» глазами разработчика.

<details><summary>Ответ</summary>

Разработчик увидит ошибки вида `could not resolve host`, при этом
приложения «живы» и доступны по IP: классический инцидент «упал DNS».

</details>

#### C9. EndpointSlice
1. Создай сервис на 3 пода.
2. Посмотри `kubectl get endpointslices -l kubernetes.io/service-name=web -o yaml`.
3. Сломай readiness одного пода и посмотри, как изменился срез.

#### C10. MTU (со звёздочкой)
1. Внутри пода: `ip link show eth0` — запиши MTU.
2. На ноде: `ip link show` — запиши MTU основного интерфейса и vxlan-интерфейса, если есть.
3. Проверь прохождение большого пакета:
   `ping -M do -s 1472 <IP другого пода>` и подбери максимальный размер.

<details><summary>Ответ</summary>

Внутри пода MTU обычно на 50 байт меньше сетевого при VXLAN
(например, 1450 вместо 1500). Максимальный размер `ping -M do -s N` подтверждает это.

</details>

#### C11. tcpdump (со звёздочкой)
Из netshoot с `hostNetwork: true` (или на ноде) поймай трафик к своему сервису:
```bash
tcpdump -i any -n port 8080
```
Сделай запрос через ClusterIP и найди в дампе подмену адреса (DNAT).

#### C12. Corefile
Посмотри `kubectl -n kube-system get cm coredns -o yaml`. Разбери, что делает каждый
плагин (`errors`, `health`, `kubernetes`, `forward`, `cache`, `loop`, `reload`).
Добавь `log` и посмотри запросы в реальном времени.

#### C13. 🔑 Алгоритм диагностики
Попроси кого-нибудь (или себя) «сломать» сервис одним из способов:
неверные метки, сломанная readiness, удалённый kube-proxy, выключенный CoreDNS,
NetworkPolicy. Прогоняй алгоритм из конспекта и засекай, за сколько находишь причину.

---

### Блок D. Инциденты

**D1.** Приложение обращается к внешнему API `payments.example.com`, каждый запрос
выполняется на 4-5 секунд дольше ожидаемого. Разбор.

<details><summary>Ответ</summary>

`ndots:5`: каждый внешний запрос сначала перебирает search-домены.
Лечение — точка в конце, `ndots: 2`, кэш, NodeLocal DNSCache.

</details>

**D2.** Поды на одной ноде видят друг друга, а между нодами — нет. Где искать?

<details><summary>Ответ</summary>

CNI между нодами: маршруты, оверлейные интерфейсы, состояние подов
CNI-плагина, firewall/security groups между машинами, MTU.

</details>

**D3.** Всё «легло»: приложения не работают, но `kubectl get pods` показывает Running
и логи чистые. Первая гипотеза?

<details><summary>Ответ</summary>

CoreDNS: имена не резолвятся, хотя всё запущено. Проверить поды
в `kube-system` и попробовать обращение по ClusterIP.

</details>

**D4.** После обновления ядра на ноде поды на ней не получают сеть
и висят в `ContainerCreating`. Причина?

<details><summary>Ответ</summary>

Нарушен CNI после обновления ядра: не загружены модули (`br_netfilter`,
`overlay`), сброшены sysctl или конфликтует новая версия плагина.
Смотреть логи пода CNI и kubelet.

</details>

**D5.** Запросы внутри кластера иногда получают `connection reset`,
причём только к одному сервису и только с части нод.

<details><summary>Ответ</summary>

Вариант с conntrack и переполнением таблицы, неравномерным набором правил
на нодах или подом, не прошедшим readiness, но оставшимся в части правил.
Проверить kube-proxy и EndpointSlice, счётчики conntrack на нодах.

</details>

**D6.** Скачивание файлов больше 1 МБ из пода в под зависает, мелкие запросы работают.

<details><summary>Ответ</summary>

MTU оверлея: правильный ответ почти всегда именно этот.

</details>

**D7.** После добавления новой ноды поды на ней не могут достучаться ни до одного
сервиса, но видят поды напрямую.

<details><summary>Ответ</summary>

На новой ноде не поднялся kube-proxy (или его правила не применились);
прямые обращения к подам работают через CNI.

</details>

**D8.** Разработчик прописал в конфиге IP CoreDNS вместо имени сервиса.
Что случится при переустановке кластера?

<details><summary>Ответ</summary>

При переустановке кластера адрес CoreDNS может измениться, конфигурация
сломается. Нужно использовать DNS-имена, а не IP.

</details>

**D9.** В логах CoreDNS видно тысячи запросов к `search`-суффиксам.
Что это и как снизить нагрузку?

<details><summary>Ответ</summary>

Это эффект `ndots:5`. Снизить нагрузку: `ndots: 2`, полные имена с точкой,
кэширование (`cache` в Corefile, NodeLocal DNSCache).

</details>

**D10.** Сервис отвечает, но приложение видит IP клиента как IP ноды, а не реальный.
Что происходит (подсказка: SNAT и `externalTrafficPolicy`, тема 11)?

<details><summary>Ответ</summary>

Трафик прошёл через SNAT (например, через NodePort с
`externalTrafficPolicy: Cluster`). Сохранить реальный IP помогает
`externalTrafficPolicy: Local` или проксирование через Ingress с заголовками
`X-Forwarded-For` (тема 11 и 12).

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Как устроена сеть в Kubernetes? Расскажи правила модели.

<details><summary>Ответ</summary>

Плоская сеть: у каждого пода свой IP, поды общаются без NAT, реализацию
обеспечивает CNI-плагин, кубер задаёт лишь требования.

</details>

**2.** Что такое CNI и какие плагины знаешь?

<details><summary>Ответ</summary>

Стандарт подключения сети к подам; плагины: Calico, Cilium, Flannel, Weave.

</details>

**3.** Чем оверлей отличается от маршрутизации?

<details><summary>Ответ</summary>

Оверлей инкапсулирует трафик (работает везде, но режет MTU),
маршрутизация использует обычные маршруты (быстрее, требует поддержки сети).

</details>

**4.** ⭐ Как работает Service на уровне ноды? Что делает kube-proxy?

<details><summary>Ответ</summary>

Через правила ядра (iptables/IPVS), которые пишет kube-proxy на каждой ноде
по данным Service и EndpointSlice; ClusterIP перехватывается и DNAT'ится на под.

</details>

**5.** Проходит ли трафик через kube-proxy?

<details><summary>Ответ</summary>

Нет, kube-proxy только программирует ядро.

</details>

**6.** Что такое EndpointSlice?

<details><summary>Ответ</summary>

Объект со списком адресов за сервисом, разбитый на срезы ради масштабируемости.

</details>

**7.** Как работает DNS в кластере? Как выглядит полное имя сервиса?

<details><summary>Ответ</summary>

CoreDNS резолвит `service.namespace.svc.cluster.local`; адрес DNS прописан
в `/etc/resolv.conf` подов.

</details>

**8.** Что такое ndots и почему из-за него бывает медленный DNS?

<details><summary>Ответ</summary>

Порог числа точек, при котором имя считается полным; при меньшем количестве
резолвер перебирает search-суффиксы, что даёт лишние запросы и задержки.

</details>

**9.** Что произойдёт при падении CoreDNS?

<details><summary>Ответ</summary>

Перестанут резолвиться имена — внешне это выглядит как полный отказ,
хотя поды работают и доступны по IP.

</details>

**10.** Как ты будешь искать причину, если сервис не отвечает?

<details><summary>Ответ</summary>

По алгоритму: endpoints → прямой IP пода → ClusterIP → DNS → NetworkPolicy →
межнодовая связность.

</details>

---

### 🎯 Чек-лист

- [ ] Могу объяснить четыре правила сетевой модели
- [ ] Понимаю разницу Pod CIDR / Service CIDR / сеть нод
- [ ] Знаю, что делает CNI и чем отличаются оверлей и маршрутизация
- [ ] ⭐ Объясняю, что kube-proxy не пропускает трафик через себя
- [ ] Видел правила `KUBE-SERVICES` своими глазами
- [ ] Проверял DNS из пода и понимаю формат имён
- [ ] Разобрался с `ndots:5` и умею его чинить
- [ ] Ломал kube-proxy и CoreDNS и знаю, как выглядят симптомы
- [ ] Использую netshoot как основной инструмент диагностики
- [ ] Прогнал алгоритм «сервис не отвечает» хотя бы на трёх поломках
