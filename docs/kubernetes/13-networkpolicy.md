---
title: "13. NetworkPolicy"
description: "Встроенный firewall уровня пода: default deny, селекторы, разрешение DNS, зависимость от CNI"
---

# 13. NetworkPolicy

> Роадмап → 6. Kubernetes → Сеть → Настройка через манифесты → **NetworkPolicy**, **CNI-конфиг**.
> **После темы ты умеешь:** закрыть сеть по умолчанию и разрешить только нужные связи,
> а также понимать, почему политика может «не работать вообще».

---

## 🗺️ Карта темы

```text:no-line-numbers
  БЕЗ ПОЛИТИК: любой под может обратиться к любому поду в ЛЮБОМ namespace
  ┌─────────┐   ┌─────────┐   ┌──────────┐
  │ frontend│──►│ backend │──►│ postgres │     и frontend ──► postgres напрямую тоже
  └─────────┘   └─────────┘   └──────────┘     и под из dev ──► prod тоже

  С ПОЛИТИКАМИ (default deny + точечные разрешения):
  ┌─────────┐   ┌─────────┐   ┌──────────┐
  │ frontend│──►│ backend │──►│ postgres │
  └─────────┘   └─────────┘   └──────────┘
        ╳ запрещено всё, что не разрешено явно ╳

  ⚠️ Политики применяет CNI-плагин. Flannel их НЕ поддерживает — правила будут
     лежать в API и не работать.
```

---

## 1. Зачем это нужно

По умолчанию сеть кубера **полностью плоская и открытая**: namespace не изолирует
трафик. Любой скомпрометированный под может стучаться в базу, в системные сервисы,
в соседнее окружение.

NetworkPolicy — это встроенный firewall уровня пода: правила, описывающие, кому
разрешено обращаться к выбранным подам (ingress) и куда этим подам можно ходить (egress).

| Требование | Как закрывается |
|------------|-----------------|
| Изоляция окружений (dev не должен видеть prod) | Политика по namespace |
| Доступ к БД только у бэкенда | Политика по меткам подов |
| Микросегментация (PCI DSS и подобные требования) | Default deny + явные разрешения |
| Ограничение исходящего трафика | Egress-политики |

---

## 2. Ключевые правила ⭐

1. **Если под не попадает ни под одну политику — ему разрешено всё.**
2. **Как только под попал хотя бы под одну политику для данного направления
   (ingress/egress) — разрешено только то, что явно описано.**
3. Политики **аддитивны**: правила складываются (логическое ИЛИ), запрещающих
   правил не существует.
4. Политика действует в пределах своего namespace (`podSelector` выбирает поды
   этого namespace).
5. Правила применяются на **уровне соединения**: разрешив ingress, обратный трафик
   ответов разрешать не нужно.

---

## 3. Default deny — с чего начинают

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: prod
spec:
  podSelector: {}              # ⭐ пустой селектор = ВСЕ поды namespace
  policyTypes: [Ingress, Egress]
  # правил нет → запрещено всё
```

> ⚠️ Закрыв egress целиком, ты ломаешь **DNS**: под не сможет резолвить имена.
> Поэтому сразу добавляют разрешение к CoreDNS:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: prod
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
```

---

## 4. Разрешения

### Только от бэкенда к базе

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow-backend
  namespace: prod
spec:
  podSelector:
    matchLabels: { app: postgres }        # к кому применяется
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels: { app: backend } # кому разрешено
      ports:
        - { protocol: TCP, port: 5432 }
```

### Из другого namespace

```yaml
  ingress:
    - from:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: monitoring }
          podSelector:
            matchLabels: { app: prometheus }
      ports:
        - { protocol: TCP, port: 9090 }
```

> ⭐ **Тонкость, которую любят на собесе.** Разница между:
> ```yaml
> from:
>   - namespaceSelector: {...}
>     podSelector: {...}      # ОДИН элемент списка → И (namespace И под)
> ```
> и
> ```yaml
> from:
>   - namespaceSelector: {...}
>   - podSelector: {...}      # ДВА элемента → ИЛИ (любой под из ns ИЛИ под с меткой)
> ```
> Дефис решает всё.

### Внешние адреса (egress)

```yaml
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8            # всё, кроме внутренних сетей
      ports:
        - { protocol: TCP, port: 443 }
```

### Разрешить ingress-контроллеру

```yaml
spec:
  podSelector: { matchLabels: { app: web } }
  ingress:
    - from:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: ingress-nginx }
      ports: [{ protocol: TCP, port: 8080 }]
```

---

## 5. Что NetworkPolicy НЕ умеет

| Не умеет | Комментарий |
|----------|-------------|
| Запрещающие правила | Только разрешения; «запретить одному» = разрешить всем остальным |
| L7-фильтрацию (URL, методы, заголовки) | Это Cilium с L7-политиками или service mesh |
| Логировать отброшенные пакеты | Зависит от CNI: у Calico и Cilium есть свои средства |
| Работать без поддержки CNI | Flannel (в базовой конфигурации) политики игнорирует |
| Фильтровать по DNS-именам | В стандарте нет; у Cilium и Calico есть расширения |
| Ограничивать доступ к API-серверу | Это RBAC, а не сеть |

**Проверить поддержку:**
```bash
kubectl get pods -n kube-system | grep -E 'calico|cilium|weave|flannel'
```
Если стоит Flannel — политики создадутся, но применяться не будут.
Это самый коварный случай: «правила есть, а не работают».

---

## 6. Пример: трёхзвенное приложение

```yaml
# 1. всё запрещено
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny, namespace: shop }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# 2. DNS для всех
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-dns, namespace: shop }
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: kube-system } }
          podSelector: { matchLabels: { k8s-app: kube-dns } }
      ports: [{ protocol: UDP, port: 53 }, { protocol: TCP, port: 53 }]
---
# 3. фронт принимает трафик от ingress-контроллера
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: frontend-ingress, namespace: shop }
spec:
  podSelector: { matchLabels: { app: frontend } }
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: ingress-nginx } }
      ports: [{ protocol: TCP, port: 80 }]
---
# 4. фронт ходит только в бэкенд
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: frontend-egress, namespace: shop }
spec:
  podSelector: { matchLabels: { app: frontend } }
  policyTypes: [Egress]
  egress:
    - to: [{ podSelector: { matchLabels: { app: backend } } }]
      ports: [{ protocol: TCP, port: 8080 }]
---
# 5. бэкенд принимает только от фронта
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: backend-ingress, namespace: shop }
spec:
  podSelector: { matchLabels: { app: backend } }
  policyTypes: [Ingress]
  ingress:
    - from: [{ podSelector: { matchLabels: { app: frontend } } }]
      ports: [{ protocol: TCP, port: 8080 }]
---
# 6. база принимает только от бэкенда
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: db-ingress, namespace: shop }
spec:
  podSelector: { matchLabels: { app: postgres } }
  policyTypes: [Ingress]
  ingress:
    - from: [{ podSelector: { matchLabels: { app: backend } } }]
      ports: [{ protocol: TCP, port: 5432 }]
```

---

## 7. Отладка

```bash
kubectl get netpol -A
kubectl describe netpol default-deny -n shop

# проверка доступности из пода
kubectl run test --rm -it --image=nicolaka/netshoot -n shop --restart=Never -- bash
  nc -zv postgres 5432
  curl -m 3 http://backend:8080
  nslookup backend

# для Calico
calicoctl get networkpolicy -A
# для Cilium
cilium connectivity test
kubectl -n kube-system exec ds/cilium -- cilium monitor --type drop
```

| Симптом | Причина |
|---------|---------|
| Политика создана, ничего не изменилось | CNI не поддерживает NetworkPolicy |
| После default-deny «отвалилось всё» | Не разрешён DNS (порт 53 в kube-system) |
| Не работает доступ из другого namespace | Нужен `namespaceSelector`; у namespace должна быть метка |
| Разрешение не сработало | Перепутано И/ИЛИ (дефис в списке `from`) |
| Ingress-контроллер получает таймаут | Не разрешён трафик из его namespace |
| Мониторинг перестал собирать метрики | Не разрешён Prometheus |
| Таймаут вместо отказа | Пакеты просто отбрасываются — типичный признак блокировки политикой |

---

## 8. CNI-конфиг (упоминается в роадмапе)

Конфигурация плагина лежит на ноде в `/etc/cni/net.d/`:

```bash
ls /etc/cni/net.d/
cat /etc/cni/net.d/10-calico.conflist
```

Что там задаётся: тип плагина, IPAM (откуда брать адреса), MTU, маршруты,
дополнительные плагины (`portmap`, `bandwidth`).

Настройки самого CNI обычно правят не в файлах на нодах, а через его объекты:
```bash
kubectl get installation -o yaml          # Calico (operator)
kubectl -n kube-system get cm cilium-config -o yaml
kubectl get ippools.crd.projectcalico.org -o yaml     # пул адресов подов
```

Важные параметры: Pod CIDR и размер блока на ноду, MTU, режим инкапсуляции
(VXLAN/IPIP/None), включение eBPF и замена kube-proxy.

---

## 💼 Как это в DevOps

- В зрелых кластерах политика «default deny в каждом namespace плюс явные разрешения» —
  стандарт; включают её поэтапно, начиная с новых namespace.
- Первое, что ломается при включении, — DNS и мониторинг. Разрешения для них
  кладут в базовый набор политик (часто в общий Helm-чарт для namespace).
- Политики удобно держать рядом с приложением: они часть его контракта
  («кто ко мне ходит и куда хожу я»).
- Для L7-правил и наблюдаемости («кто кому звонил») берут Cilium (Hubble)
  или service mesh — обычный NetworkPolicy этого не даёт.
- На собеседовании достаточно уверенно знать: default deny, селекторы,
  проблему DNS и зависимость от CNI.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Запретить всё в namespace | `podSelector: {}` + `policyTypes: [Ingress, Egress]` без правил |
| Разрешить DNS | egress к `kube-dns` в `kube-system`, порты 53 UDP/TCP |
| Разрешить от конкретного приложения | `from: [{podSelector: {matchLabels: {app: backend}}}]` |
| Разрешить из другого namespace | `namespaceSelector` (метка `kubernetes.io/metadata.name`) |
| И namespace, И под | Один элемент списка с двумя селекторами |
| ИЛИ namespace, ИЛИ под | Два отдельных элемента списка |
| Разрешить во внешнюю сеть | `ipBlock.cidr` с `except` |
| Проверить поддержку CNI | `kubectl get pods -n kube-system \| grep -E 'calico\|cilium'` |
| Проверить доступ | `nc -zv host port` из netshoot |
| Посмотреть политики | `kubectl get netpol -A` |

---

## 🧠 Что запомнить

1. По умолчанию в кубере разрешено **всё**; namespace сеть не изолирует.
2. Под без политик — открыт; как только политика применилась к направлению,
   разрешено только описанное.
3. Политики только **разрешают**; запрещающих правил не существует.
4. Правила складываются логическим ИЛИ.
5. ⭐ Default deny — база; сразу после него разрешай **DNS**, иначе сломается всё.
6. Дефис в списке `from` меняет И на ИЛИ — самая частая ошибка.
7. Для `namespaceSelector` у namespace должна быть метка
   (`kubernetes.io/metadata.name` проставляется автоматически).
8. NetworkPolicy работает на L3/L4; L7 — это Cilium или service mesh.
9. ⭐ Политики исполняет CNI: Flannel их игнорирует, Calico и Cilium — поддерживают.
10. Симптом блокировки — таймаут, а не отказ соединения.
11. Разрешения нужны и инфраструктуре: ingress-контроллеру, Prometheus, probe'ам kubelet.
12. Политики — часть манифестов приложения, а не отдельная «сетевая» работа.

---

## Задачи

> ⚠️ Перед практикой проверь CNI: в kind по умолчанию стоит kindnet,
> который политики **не применяет**. Для лаб пересоздай кластер с Calico
> (`kind create cluster --config` с `disableDefaultCNI: true` + установка Calico)
> или используй minikube с `--cni=calico`.

---

### Блок A. Теория

**A1.** Что разрешено по умолчанию между подами в кубере?

<details><summary>Ответ</summary>

Всё: любой под может обратиться к любому поду в любом namespace.

</details>

**A2.** Изолирует ли namespace сетевой трафик?

<details><summary>Ответ</summary>

Нет. Namespace разделяет имена, права и квоты, но не сеть.

</details>

**A3.** ⭐ Что произойдёт с подом, на который не действует ни одна политика?

<details><summary>Ответ</summary>

Ему разрешён весь трафик — политики работают по принципу «не выбран, значит открыт».

</details>

**A4.** ⭐ Что произойдёт, как только под попал под действие хотя бы одной политики?

<details><summary>Ответ</summary>

Для этого направления (ingress и/или egress) начинает действовать
белый список: разрешено только то, что описано в политиках, применимых к поду.

</details>

**A5.** Могут ли политики запрещать трафик?

<details><summary>Ответ</summary>

Нет, только разрешать. «Запрет» достигается тем, что трафик не попал
ни в одно разрешающее правило.

</details>

**A6.** Как складываются несколько политик, действующих на один под?

<details><summary>Ответ</summary>

Объединяются логическим ИЛИ: разрешено всё, что разрешено хотя бы одной
из применимых политик.

</details>

**A7.** Что означает `podSelector: {}`?

<details><summary>Ответ</summary>

Все поды текущего namespace.

</details>

**A8.** Что задаёт `policyTypes` и что будет, если его не указать?

<details><summary>Ответ</summary>

Направления, к которым применяется политика. Если не указан, он выводится
из наличия секций `ingress`/`egress`; для default-deny его указывают явно.

</details>

**A9.** ⭐ Почему после default-deny «ломается всё» и что нужно разрешить первым?

<details><summary>Ответ</summary>

Потому что закрывается egress, включая обращения к CoreDNS: имена перестают
резолвиться. Первым разрешают DNS (порт 53 UDP и TCP к `kube-dns` в `kube-system`).

</details>

**A10.** ⭐ В чём разница между одним элементом `from` с двумя селекторами
и двумя элементами списка?

<details><summary>Ответ</summary>

Один элемент с двумя селекторами — логическое И (под с такой меткой
**в** таком namespace). Два элемента — ИЛИ (любой под из namespace **или**
любой под с меткой).

</details>

**A11.** Как разрешить трафик из другого namespace?

<details><summary>Ответ</summary>

Через `namespaceSelector` (при необходимости в паре с `podSelector`).

</details>

**A12.** Какая метка есть у каждого namespace автоматически?

<details><summary>Ответ</summary>

`kubernetes.io/metadata.name` со значением, равным имени namespace.

</details>

**A13.** Что такое `ipBlock` и `except`?

<details><summary>Ответ</summary>

Разрешение по диапазону IP; `except` исключает подсети из разрешённого
диапазона. Применяется для egress во внешние сети.

</details>

**A14.** Нужно ли отдельно разрешать обратный трафик ответов?

<details><summary>Ответ</summary>

Нет: правила работают на уровне соединений, ответный трафик разрешён
автоматически.

</details>

**A15.** На каком уровне работает NetworkPolicy? Что она не умеет фильтровать?

<details><summary>Ответ</summary>

На L3/L4 (адреса, протоколы, порты). Не умеет фильтровать по URL,
методам, заголовкам и DNS-именам.

</details>

**A16.** ⭐ Какие CNI поддерживают NetworkPolicy, а какие нет?

<details><summary>Ответ</summary>

Поддерживают Calico, Cilium, Weave, Antrea, облачные CNI.
Flannel в базовой конфигурации — нет.

</details>

**A17.** Как выглядит инцидент «политики не работают вообще»?

<details><summary>Ответ</summary>

Политики применяются без ошибок, отображаются в `kubectl get netpol`,
но трафик ходит как прежде: CNI их просто игнорирует.

</details>

**A18.** Как отличить блокировку политикой от других сетевых проблем по симптому?

<details><summary>Ответ</summary>

Блокировка политикой выглядит как **таймаут** (пакеты отбрасываются),
а не как `connection refused` (порт закрыт) и не как ошибка DNS.

</details>

**A19.** Кому ещё, кроме приложений, нужны разрешения при default-deny?

<details><summary>Ответ</summary>

Ingress-контроллеру, Prometheus и другим сборщикам метрик, sidecar'ам mesh,
иногда системным агентам; плюс egress к внешним зависимостям.

</details>

**A20.** Может ли NetworkPolicy ограничить доступ к API-серверу?

<details><summary>Ответ</summary>

Нет: доступ к API регулируется RBAC (и сетевой доступностью endpoint'а
`kubernetes`), а не политиками подов.

</details>

**A21.** Что такое L7-политики и где они есть?

<details><summary>Ответ</summary>

Правила по HTTP-методам, путям, заголовкам; есть у Cilium
и у service mesh (Istio/Linkerd) — в стандартной NetworkPolicy их нет.

</details>

**A22.** Где лежит конфигурация CNI на ноде?

<details><summary>Ответ</summary>

В `/etc/cni/net.d/` на каждой ноде; сама конфигурация плагина обычно
управляется его объектами в кластере.

</details>

**A23.** Какие параметры CNI важны при проектировании кластера?

<details><summary>Ответ</summary>

Pod CIDR и размер блока на ноду (сколько подов поместится),
режим инкапсуляции, MTU, поддержка политик, замена kube-proxy на eBPF,
интеграция с сетью дата-центра.

</details>

**A24.** Как политика взаимодействует с probe'ами kubelet?

<details><summary>Ответ</summary>

Probe'ы выполняет kubelet с ноды, а трафик от ноды к поду политиками
обычно не блокируется (зависит от реализации CNI); поэтому пробы, как правило,
продолжают работать.

</details>

**A25.** Почему политики удобно хранить вместе с манифестами приложения?

<details><summary>Ответ</summary>

Политика описывает контракт приложения «кто ко мне ходит и куда хожу я»;
её удобно версионировать вместе с кодом и деплоить одним чартом.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
spec:
  podSelector: {}
  policyTypes: [Ingress]
```
Вопрос: что станет с входящим трафиком? А с исходящим?

<details><summary>Ответ</summary>

Входящий трафик ко всем подам namespace запрещён; исходящий не ограничен,
так как `Egress` не указан в `policyTypes`.

</details>

**B2.**
```yaml
spec:
  podSelector: { matchLabels: { app: db } }
  policyTypes: [Ingress]
  ingress:
    - from: [{ podSelector: { matchLabels: { app: backend } } }]
```
Вопрос: сможет ли фронтенд обратиться к базе? А бэкенд из соседнего namespace?

<details><summary>Ответ</summary>

Фронтенд не сможет; бэкенд из соседнего namespace — тоже нет:
`podSelector` без `namespaceSelector` означает поды **этого же** namespace.

</details>

**B3.**
```yaml
  ingress:
    - from:
        - namespaceSelector: { matchLabels: { env: prod } }
          podSelector: { matchLabels: { app: backend } }
```
Вопрос: кому разрешено?

<details><summary>Ответ</summary>

Подам с меткой `app: backend`, находящимся в namespace с меткой `env: prod`.

</details>

**B4.**
```yaml
  ingress:
    - from:
        - namespaceSelector: { matchLabels: { env: prod } }
        - podSelector: { matchLabels: { app: backend } }
```
Вопрос: чем отличается от B3?

<details><summary>Ответ</summary>

Здесь ИЛИ: любым подам из namespace с `env: prod`, а также подам
с меткой `app: backend` из текущего namespace.

</details>

**B5.**
```yaml
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress: []
```
Вопрос: что сломается в первую очередь?

<details><summary>Ответ</summary>

DNS: резолв имён перестанет работать, и приложения начнут падать
с ошибками разрешения имён.

</details>

**B6.**
```bash
kubectl apply -f deny-all.yaml      # кластер на Flannel
kubectl exec -it app -- curl http://db:5432
# запрос проходит
```
Вопрос: почему?

<details><summary>Ответ</summary>

Flannel не реализует NetworkPolicy: объект есть, применения нет.

</details>

**B7.**
```bash
kubectl exec -it frontend -- curl -m 3 http://backend:8080
# curl: (28) Operation timed out
```
Вопрос: это похоже на политику или на что-то другое? Почему?

<details><summary>Ответ</summary>

Похоже на политику (или на сетевую блокировку): пакеты отбрасываются
молча. Отказ соединения указывал бы на закрытый порт или отсутствие endpoints.

</details>

**B8.**
```yaml
# в namespace shop есть default-deny; ingress-контроллер в ingress-nginx
```
Вопрос: будет ли работать публикация приложения через Ingress?

<details><summary>Ответ</summary>

Нет, пока не разрешён входящий трафик из namespace ingress-контроллера.

</details>

---

### Блок C. Практика

#### C0. Подготовка
Убедись, что CNI поддерживает политики:
```bash
kubectl get pods -n kube-system | grep -E 'calico|cilium|weave'
```
Если нет — подними кластер с Calico (см. примечание вверху).

#### C1. 🔑 Проверяем открытость по умолчанию
1. Создай два namespace: `shop` и `other`.
2. Запусти nginx в `shop` и под-клиент в `other`.
3. Обратись из `other` к сервису в `shop` по полному имени.
4. Убедись, что работает. Запиши вывод — это отправная точка темы.

#### C2. 🔑 Default deny
1. Примени `default-deny-all` в `shop`.
2. Повтори запрос из `other` — должен быть таймаут.
3. Проверь запрос **внутри** `shop` между подами — тоже не работает.
4. Проверь резолв DNS изнутри `shop` — сломался?

<details><summary>Ответ</summary>

Ожидаемо: таймауты и при межнамespace-доступе, и внутри namespace,
и поломка DNS.

</details>

#### C3. 🔑 Разрешаем DNS
Примени политику `allow-dns` и убедись, что резолв заработал,
а обращения к подам по-прежнему запрещены.

#### C4. Разрешение от конкретного приложения
1. Разреши `app: backend` → `app: postgres` по порту 5432.
2. Проверь: из backend работает, из frontend нет.
3. Проверь, работает ли доступ по другому порту (например, 5433).

#### C5. И vs ИЛИ
Сделай две версии политики (с одним элементом `from` и с двумя) и проверь
доступ из четырёх источников: нужный namespace + нужная метка; нужный namespace +
другая метка; другой namespace + нужная метка; другой namespace + другая метка.
Заполни таблицу истинности.

<details><summary>Ответ</summary>

Таблица: при одном элементе (И) доступ есть только у «нужный ns + нужная метка»;
при двух элементах (ИЛИ) — у трёх комбинаций из четырёх.

</details>

#### C6. Из другого namespace
1. Навесь метку на namespace `monitoring`.
2. Разреши доступ из него к своему приложению.
3. Проверь из пода в `monitoring` и из пода в третьем namespace.

#### C7. Egress наружу
1. Запрети egress по умолчанию.
2. Разреши только HTTPS наружу (порт 443) и DNS.
3. Проверь: `curl https://example.com` работает, `curl http://example.com` нет.

<details><summary>Ответ</summary>

`curl https://example.com` работает, `http://` — нет: разрешён только порт 443.

</details>

#### C8. 🔑 Трёхзвенное приложение
Собери полный набор политик из конспекта (§6) для `frontend`, `backend`, `postgres`.
Проверь матрицу доступов:

| Откуда \ Куда | frontend | backend | postgres | внешний мир |
|---|---|---|---|---|
| ingress-nginx | ✅ | ❌ | ❌ | — |
| frontend | — | ✅ | ❌ | ❌ |
| backend | ❌ | — | ✅ | ? |
| postgres | ❌ | ❌ | — | ❌ |

#### C9. Ingress и политики
1. Опубликуй приложение через Ingress (тема 12) в namespace с default-deny.
2. Убедись, что снаружи получаешь таймаут/502.
3. Добавь разрешение из namespace ingress-контроллера.
4. Проверь снова.

#### C10. Probe'ы и политики
Проверь, продолжают ли работать liveness/readiness пробы при default-deny.
Объясни результат (подсказка: probe'ы выполняет kubelet с ноды).

<details><summary>Ответ</summary>

Пробы обычно продолжают работать: их выполняет kubelet с ноды,
а не под из кластера.

</details>

#### C11. Мониторинг
Если стоит Prometheus — убедись, что после default-deny метрики перестали
собираться, и добавь разрешение. Если нет — опиши, какую политику написал бы.

#### C12. Отладка (со звёздочкой)
Для Calico: посмотри отброшенные пакеты (`calicoctl` или логи `calico-node`).
Для Cilium: `cilium monitor --type drop`. Опиши, как это ускоряет разбор.

#### C13. Документируй матрицу (со звёздочкой)
Нарисуй схему разрешённых связей своего приложения и положи её в README.
На собеседовании такая схема — сильный аргумент.

---

### Блок D. Инциденты

**D1.** Применили default-deny в проде — «легло всё», хотя политики разрешают
нужные связи. Что забыли?

<details><summary>Ответ</summary>

Разрешение DNS. Без него имена не резолвятся и «ломается всё»,
даже если остальные правила верны.

</details>

**D2.** Политики созданы, но ничего не меняется: трафик ходит как раньше. Причина?

<details><summary>Ответ</summary>

CNI не поддерживает NetworkPolicy (Flannel) либо политики применены
в другом namespace.

</details>

**D3.** После включения политик мониторинг перестал собирать метрики приложения.

<details><summary>Ответ</summary>

Не разрешён входящий трафик от Prometheus: нужна политика
с `namespaceSelector` его namespace и портом метрик.

</details>

**D4.** Приложение в namespace с политиками получает таймаут при обращении
к внешнему API. Что проверить?

<details><summary>Ответ</summary>

Egress: разрешены ли порт и диапазон адресов, разрешён ли DNS,
не блокирует ли внешний firewall.

</details>

**D5.** Разработчик написал политику «запретить доступ из dev в prod»,
но она не работает. Объясни ошибку в самой постановке.

<details><summary>Ответ</summary>

NetworkPolicy не умеет запрещать. Правильная постановка — включить
default-deny в prod и явно разрешить только нужные источники.

</details>

**D6.** Доступ из другого namespace не работает, хотя `namespaceSelector` указан.
Что проверить?

<details><summary>Ответ</summary>

Метку у namespace (в том числе автоматическую
`kubernetes.io/metadata.name`), правильность написания селектора,
а также то, что `podSelector` в том же элементе списка относится к удалённому
namespace, а не к своему.

</details>

**D7.** После добавления политики упали readiness-пробы. Возможно ли это
и от чего зависит?

<details><summary>Ответ</summary>

В большинстве реализаций пробы не блокируются, так как идут от kubelet.
Но при жёстких egress-правилах может сломаться проверка, выполняемая
из самого приложения к зависимостям, — и readiness начнёт падать.

</details>

**D8.** Половина связей работает, половина нет, политика одна и та же.
Что могло пойти не так с селекторами?

<details><summary>Ответ</summary>

Опечатки в метках, разные наборы меток у части подов, пересечение
нескольких политик, а также разница между `podSelector` в `spec`
и в `from`/`to`.

</details>

**D9.** Служба безопасности требует логировать заблокированные соединения.
Что ответишь про возможности NetworkPolicy?

<details><summary>Ответ</summary>

Стандарт логирования не предусматривает; возможности зависят от CNI:
у Calico есть действие Log в своих политиках, у Cilium — Hubble
и `cilium monitor --type drop`.

</details>

**D10.** Нужно разрешить доступ только к `api.payments.com` по имени.
Возможно ли это стандартной NetworkPolicy?

<details><summary>Ответ</summary>

Стандартной — нет (только по IP-диапазонам). Нужны расширения CNI
(Cilium FQDN-политики, Calico DNS policy) или egress-прокси.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое NetworkPolicy и зачем она нужна?

<details><summary>Ответ</summary>

Встроенный firewall уровня пода: описывает, кому разрешено обращаться к подам
и куда им можно ходить.

</details>

**2.** Что разрешено между подами по умолчанию?

<details><summary>Ответ</summary>

Всё: сеть плоская и открытая, namespace её не изолирует.

</details>

**3.** ⭐ Что происходит с подом, попавшим под политику?

<details><summary>Ответ</summary>

Для выбранного направления начинает действовать белый список: разрешено
только явно описанное.

</details>

**4.** Как сделать default deny и что важно разрешить сразу?

<details><summary>Ответ</summary>

`podSelector: {}` с `policyTypes: [Ingress, Egress]` без правил; сразу после —
разрешение DNS, затем ingress-контроллера и мониторинга.

</details>

**5.** Как разрешить трафик из другого namespace?

<details><summary>Ответ</summary>

Через `namespaceSelector`, при необходимости вместе с `podSelector`
в одном элементе списка.

</details>

**6.** Можно ли запретить трафик политикой?

<details><summary>Ответ</summary>

Нет, политики только разрешают.

</details>

**7.** На каком уровне работает NetworkPolicy?

<details><summary>Ответ</summary>

На L3/L4; L7 — задача Cilium или service mesh.

</details>

**8.** От чего зависит, будет ли политика работать вообще?

<details><summary>Ответ</summary>

От CNI: политики исполняет плагин, и без поддержки они не работают.

</details>

**9.** Изолирует ли namespace сеть?

<details><summary>Ответ</summary>

Нет.

</details>

**10.** Как отлаживать проблемы, вызванные политиками?

<details><summary>Ответ</summary>

Проверять доступность из netshoot (таймаут против отказа), смотреть применимые
политики и их селекторы, использовать средства CNI для просмотра отброшенных
пакетов.

</details>

---

### 🎯 Чек-лист

- [ ] Проверил, поддерживает ли мой CNI политики
- [ ] Убедился, что по умолчанию разрешено всё, в том числе между namespace
- [ ] Применил default-deny и увидел, как ломается DNS
- [ ] Разрешил DNS и восстановил работу
- [ ] Понимаю разницу И/ИЛИ в списке `from`
- [ ] Собрал политики для трёхзвенного приложения и проверил матрицу доступов
- [ ] Разрешил трафик от Ingress Controller
- [ ] Знаю, что политики только разрешают и работают на L3/L4
- [ ] Отличаю блокировку политикой (таймаут) от других проблем
