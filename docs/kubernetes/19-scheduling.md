---
title: "19. Планирование подов"
description: "affinity/anti-affinity, taints и tolerations, topologySpreadConstraints, PriorityClass, PodDisruptionBudget"
---

# 19. Планирование подов: affinity, taints, topology spread

> Роадмап → Собесы → *«Что такое Affinity и Anti-Affinity?»* — один из семи
> самых популярных вопросов.
> **После темы ты умеешь:** управлять размещением подов по нодам и зонам,
> разносить реплики для отказоустойчивости и выделять ноды под особые нагрузки.

---

## 🗺️ Карта темы

```text:no-line-numbers
  КАК ПОД ПОПАДАЕТ НА НУЖНУЮ НОДУ
  ─────────────────────────────────────────────────────────────────
  nodeSelector          простое «только на ноды с такой меткой»
  nodeAffinity          то же, но с ИЛИ, оператором In/NotIn и «мягким» вариантом
  podAffinity           «рядом с такими-то подами»
  podAntiAffinity  ⭐   «НЕ рядом с такими-то подами» (разнести реплики)
  topologySpread   ⭐   «распределить равномерно по зонам/нодам»
  taints + tolerations  ⭐ нода ОТТАЛКИВАЕТ поды, если у них нет «пропуска»
  nodeName              жёсткое назначение, минуя scheduler (для отладки)

  ОТДЕЛЬНО: PodDisruptionBudget — сколько реплик можно потерять при обслуживании
```

**Главная логическая разница:**
*affinity* — это **притяжение со стороны пода** («я хочу туда»),
*taint* — это **отталкивание со стороны ноды** («сюда нельзя без пропуска»).

---

## 1. nodeSelector — самое простое

```bash
kubectl label node worker-2 disktype=ssd
kubectl get nodes --show-labels
```
```yaml
spec:
  nodeSelector:
    disktype: ssd
```
Только точное совпадение и только «И». Если подходящих нод нет — под `Pending`.

---

## 2. nodeAffinity

```yaml
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:     # ЖЁСТКОЕ условие
        nodeSelectorTerms:
          - matchExpressions:
              - key: disktype
                operator: In
                values: [ssd, nvme]
              - key: topology.kubernetes.io/zone
                operator: NotIn
                values: [zone-c]
      preferredDuringSchedulingIgnoredDuringExecution:    # ПОЖЕЛАНИЕ
        - weight: 80
          preference:
            matchExpressions:
              - { key: node-type, operator: In, values: [compute] }
```

| Вариант | Смысл |
|---------|-------|
| `requiredDuringScheduling...` | Обязательно; иначе под `Pending` |
| `preferredDuringScheduling...` | Желательно; вес 1-100 влияет на скоринг |
| `...IgnoredDuringExecution` | ⭐ Проверяется **только при планировании**: если метки ноды изменились, работающий под не выселяется |

Операторы: `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt`.

**Полезные встроенные метки нод:**
```text:no-line-numbers
kubernetes.io/hostname
kubernetes.io/os, kubernetes.io/arch
topology.kubernetes.io/zone, topology.kubernetes.io/region
node.kubernetes.io/instance-type
node-role.kubernetes.io/control-plane
```

---

## 3. ⭐ podAffinity и podAntiAffinity (вопрос собеса)

> **Ответ на собес:** «Affinity — правила притяжения: разместить под рядом
> с определёнными подами (например, кэш рядом с приложением для меньшей задержки).
> Anti-affinity — правила отталкивания: не размещать поды вместе. Чаще всего
> anti-affinity используют, чтобы развести реплики одного приложения по разным
> нодам или зонам — тогда падение ноды не уносит всё приложение.
> Область "вместе" задаётся `topologyKey`: нода, зона, регион».

### Разнести реплики по нодам (самый частый рецепт)

```yaml
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels: { app: web }
          topologyKey: kubernetes.io/hostname     # ⭐ «одна нода = одна зона совместности»
```
Жёстко: больше одного пода `app: web` на ноду не поставить.
Если нод меньше, чем реплик, лишние останутся `Pending`.

### Мягкий вариант (чаще правильный)

```yaml
      podAntiAffinity:
        preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels: { app: web }
              topologyKey: kubernetes.io/hostname
```
Планировщик постарается развести, но при нехватке нод поды всё равно запустятся.

### Притяжение

```yaml
      podAffinity:
        preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 50
            podAffinityTerm:
              labelSelector:
                matchLabels: { app: redis }
              topologyKey: kubernetes.io/hostname
```
Полезно, когда важна сетевая близость (кэш, sidecar-сервис).

| topologyKey | Что означает «вместе» |
|-------------|------------------------|
| `kubernetes.io/hostname` | одна нода |
| `topology.kubernetes.io/zone` | одна зона доступности |
| `topology.kubernetes.io/region` | один регион |

> ⚠️ podAffinity/antiAffinity — дорогие правила: планировщику приходится сравнивать
> поды между собой. На кластерах в сотни нод жёсткие правила заметно замедляют
> планирование; поэтому чаще берут `topologySpreadConstraints`.

---

## 4. ⭐ topologySpreadConstraints — современный способ распределения

```yaml
spec:
  topologySpreadConstraints:
    - maxSkew: 1                                    # допустимая разница между зонами
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule              # или ScheduleAnyway
      labelSelector:
        matchLabels: { app: web }
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels: { app: web }
```

| Поле | Смысл |
|------|-------|
| `maxSkew` | Максимальная разница числа подов между «доменами» |
| `topologyKey` | Что считать доменом: нода, зона, регион |
| `whenUnsatisfiable` | `DoNotSchedule` (жёстко) или `ScheduleAnyway` (мягко) |
| `labelSelector` | Какие поды считаем |

Разница с anti-affinity: anti-affinity говорит «не вместе», spread говорит
«распределить равномерно, с допустимым перекосом». Второе гибче и дешевле.

---

## 5. ⭐ Taints и tolerations

**Taint** ставится на ноду и отталкивает поды; **toleration** в поде — «пропуск».

```bash
kubectl taint nodes gpu-1 gpu=true:NoSchedule
kubectl taint nodes gpu-1 gpu=true:NoSchedule-        # снять (минус в конце)
kubectl describe node gpu-1 | grep -i taint
```
```yaml
spec:
  tolerations:
    - key: gpu
      operator: Equal
      value: "true"
      effect: NoSchedule
```

| Effect | Что делает |
|--------|------------|
| `NoSchedule` | Новые поды без toleration не планируются |
| `PreferNoSchedule` | Планировщик старается избегать, но может поставить |
| `NoExecute` | Не планируются **и уже работающие вытесняются** |

```yaml
  tolerations:
    - key: node.kubernetes.io/not-ready
      operator: Exists
      effect: NoExecute
      tolerationSeconds: 300      # ⭐ сколько ждать до вытеснения при NotReady
```

**Системные taint'ы**, которые полезно знать:

| Taint | Когда ставится |
|-------|----------------|
| `node-role.kubernetes.io/control-plane:NoSchedule` | на control-plane ноды |
| `node.kubernetes.io/not-ready:NoExecute` | нода не готова |
| `node.kubernetes.io/unreachable:NoExecute` | потеряна связь с нодой |
| `node.kubernetes.io/memory-pressure`, `disk-pressure`, `pid-pressure` | нехватка ресурсов |
| `node.kubernetes.io/unschedulable` | после `kubectl cordon` |

> ⭐ Именно `not-ready`/`unreachable` с `tolerationSeconds: 300` объясняют,
> почему поды переезжают с упавшей ноды примерно через 5 минут, — тот самый
> тайминг из темы про архитектуру кластера.

**Типичное применение:** выделенные ноды (GPU, память, лицензии, отдельная команда):
taint на ноду + toleration у нужных подов + nodeSelector/affinity, чтобы они
туда действительно попали (toleration разрешает, но не притягивает).

---

## 6. PriorityClass и вытеснение

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: high-priority }
value: 1000000
globalDefault: false
description: "Критичные сервисы"
---
spec:
  priorityClassName: high-priority
```

Если для важного пода нет места, планировщик может **вытеснить** поды с меньшим
приоритетом (preemption). Встроенные классы: `system-cluster-critical`,
`system-node-critical`.

---

## 7. PodDisruptionBudget — защита при обслуживании

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: web }
spec:
  minAvailable: 2            # или maxUnavailable: 1
  selector:
    matchLabels: { app: web }
```

| Что делает | Подробности |
|------------|-------------|
| Ограничивает **добровольные** нарушения | `kubectl drain`, обновление нод, вытеснение автоскейлером |
| **Не** защищает от недобровольных | Падение ноды, OOM, аппаратный сбой |
| Работает вместе с anti-affinity | Иначе все реплики могут оказаться на одной ноде и PDB не спасёт |

> ⚠️ Слишком строгий PDB (`minAvailable` равен числу реплик) блокирует `drain`
> навсегда — нода не сможет уйти на обслуживание.

---

## 8. Готовый рецепт «отказоустойчивое приложение»

```yaml
spec:
  replicas: 3
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector: { matchLabels: { app: web } }
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector: { matchLabels: { app: web } }
                topologyKey: kubernetes.io/hostname
      tolerations:
        - key: node.kubernetes.io/not-ready
          operator: Exists
          effect: NoExecute
          tolerationSeconds: 30       # быстрее переезжать при падении ноды
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: web }
spec:
  maxUnavailable: 1
  selector: { matchLabels: { app: web } }
```

---

## 9. Отладка размещения

```bash
kubectl get pods -o wide                       # кто где
kubectl describe pod web-xxx | tail -20        # FailedScheduling и причина
kubectl describe node worker-1 | grep -A5 Taints
kubectl get nodes --show-labels
kubectl get pdb -A
```

Типичные сообщения:

| Сообщение | Причина |
|-----------|---------|
| `0/3 nodes are available: 3 Insufficient cpu` | Не хватает ресурсов по requests |
| `... 3 node(s) didn't match Pod's node affinity/selector` | Нет нод с нужными метками |
| `... 3 node(s) had untolerated taint {gpu: true}` | Нет toleration |
| `... 2 node(s) didn't match pod anti-affinity rules` | Жёсткий anti-affinity и мало нод |
| `... 3 node(s) didn't find available persistent volumes to bind` | Проблема с PVC/зоной |
| `Cannot evict pod as it would violate the pod's disruption budget` | Сработал PDB при drain |

---

## 💼 Как это в DevOps

- Минимальный набор для любого важного сервиса: 2+ реплики, anti-affinity
  (или topology spread) и PDB. Без этого «три реплики» могут оказаться
  на одной ноде и уйти вместе с ней.
- Taint'ы используют для выделенных пулов: GPU, ноды с быстрыми дисками,
  ноды под инфраструктуру (ingress, мониторинг).
- `IgnoredDuringExecution` — частый источник удивления: поменял метки ноды,
  а поды остались на месте. Перераспределение делает только пересоздание
  (или отдельный инструмент — descheduler).
- Слишком жёсткие правила — частая причина `Pending` и заблокированных обновлений
  кластера. Начинай с мягких вариантов.
- При обслуживании кластера именно PDB решает, пройдёт ли `drain`
  без простоя.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Только на ноды с меткой | `nodeSelector` |
| Гибкое условие по меткам нод | `nodeAffinity` с `In`/`NotIn`/`Exists` |
| Разнести реплики по нодам | `podAntiAffinity` + `topologyKey: kubernetes.io/hostname` |
| Разнести по зонам равномерно | `topologySpreadConstraints` с `topology.kubernetes.io/zone` |
| Поставить рядом с другим приложением | `podAffinity` |
| Выделить ноды под нагрузку | `kubectl taint` + `tolerations` (+ nodeSelector) |
| Пустить под на control-plane | `tolerations: [{operator: Exists}]` |
| Ускорить переезд при падении ноды | `tolerationSeconds` у `not-ready`/`unreachable` |
| Дать поду приоритет | `PriorityClass` + `priorityClassName` |
| Защитить от drain | `PodDisruptionBudget` |
| Понять, почему `Pending` | `kubectl describe pod` → `FailedScheduling` |
| Снять taint | `kubectl taint nodes NODE key=value:Effect-` |

---

## 🧠 Что запомнить

1. ⭐ **Affinity — притяжение (со стороны пода), taint — отталкивание (со стороны ноды).**
2. `podAntiAffinity` разносит реплики; `topologyKey` задаёт, что считать «вместе».
3. `required...` — обязательное условие (иначе `Pending`), `preferred...` — пожелание.
4. `IgnoredDuringExecution`: правила проверяются только при планировании.
5. `topologySpreadConstraints` с `maxSkew` — современный и более дешёвый способ
   равномерного распределения.
6. Toleration только **разрешает** попасть на ноду с taint, но не притягивает туда.
7. Три эффекта taint: `NoSchedule`, `PreferNoSchedule`, `NoExecute`.
8. Системные taint'ы `not-ready`/`unreachable` с `tolerationSeconds: 300` объясняют
   пятиминутный переезд подов с упавшей ноды.
9. `PriorityClass` позволяет вытеснять менее важные поды ради более важных.
10. PDB ограничивает только **добровольные** нарушения (drain, обновления).
11. Слишком строгий PDB блокирует обслуживание нод.
12. Комплект отказоустойчивости: несколько реплик + anti-affinity/spread + PDB.

---

## Задачи

> ⭐ Вопрос собеса: *«Что такое Affinity и Anti-Affinity?»*
> Практическая цель: сделать приложение, которое переживает падение ноды.

---

### Блок A. Теория

**A1.** ⭐ Что такое affinity и anti-affinity? Ответь как на собесе за 30 секунд.

<details><summary>Ответ</summary>

Affinity — правила притяжения пода к нодам (nodeAffinity) или к другим подам
(podAffinity); anti-affinity — правила отталкивания от других подов.
Чаще всего anti-affinity используют, чтобы разнести реплики по разным нодам и зонам
ради отказоустойчивости. Область «вместе» задаётся `topologyKey`.

</details>

**A2.** ⭐ В чём принципиальная разница между affinity и taint?

<details><summary>Ответ</summary>

Affinity описывается **в поде** и притягивает («я хочу туда»);
taint ставится **на ноду** и отталкивает («сюда нельзя без пропуска»).

</details>

**A3.** Что делает `nodeSelector` и чем он ограничен?

<details><summary>Ответ</summary>

Разрешает планировать под только на ноды с указанными метками;
поддерживает лишь точное совпадение и логическое И.

</details>

**A4.** Чем `nodeAffinity` мощнее `nodeSelector`?

<details><summary>Ответ</summary>

Поддерживает операторы (`In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt`),
логическое ИЛИ через несколько `nodeSelectorTerms` и «мягкие» правила с весами.

</details>

**A5.** Что означают `requiredDuringScheduling` и `preferredDuringScheduling`?

<details><summary>Ответ</summary>

`required` — обязательное условие планирования (иначе `Pending`);
`preferred` — пожелание с весом, влияющее на выбор ноды.

</details>

**A6.** ⭐ Что означает `IgnoredDuringExecution` и какое следствие из этого?

<details><summary>Ответ</summary>

Правило проверяется только при планировании: если после запуска метки
ноды изменились, работающий под не выселяется.

</details>

**A7.** Какие операторы доступны в `matchExpressions`?

<details><summary>Ответ</summary>

`In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt`.

</details>

**A8.** Назови пять встроенных меток нод.

<details><summary>Ответ</summary>

`kubernetes.io/hostname`, `kubernetes.io/os`, `kubernetes.io/arch`,
`topology.kubernetes.io/zone`, `topology.kubernetes.io/region`,
`node.kubernetes.io/instance-type`.

</details>

**A9.** ⭐ Что такое `topologyKey` и какие значения используют чаще всего?

<details><summary>Ответ</summary>

Метка ноды, по значению которой определяется «домен совместности»:
`kubernetes.io/hostname` (одна нода), `topology.kubernetes.io/zone` (зона),
`.../region` (регион).

</details>

**A10.** Как разнести три реплики по трём нодам жёстко? А мягко?

<details><summary>Ответ</summary>

Жёстко — `podAntiAffinity.requiredDuringScheduling...` с
`topologyKey: kubernetes.io/hostname`; мягко — то же в `preferredDuringScheduling...`
с весом.

</details>

**A11.** Что произойдёт при жёстком anti-affinity, если нод меньше, чем реплик?

<details><summary>Ответ</summary>

Лишние поды останутся в `Pending` с сообщением о несоблюдении
правил anti-affinity.

</details>

**A12.** Почему anti-affinity считается «дорогим» правилом?

<details><summary>Ответ</summary>

Планировщику нужно сравнивать кандидата со всеми подами в соответствующих
доменах топологии — вычислительно это дороже, чем проверка меток ноды.

</details>

**A13.** ⭐ Что такое `topologySpreadConstraints` и чем лучше anti-affinity?

<details><summary>Ответ</summary>

Ограничения равномерного распределения подов по доменам топологии
с допустимым перекосом `maxSkew`. Дешевле для планировщика и гибче:
задаёт «насколько неравномерно можно», а не «нельзя вместе».

</details>

**A14.** Что означает `maxSkew: 1`?

<details><summary>Ответ</summary>

Разница в числе подов между любыми двумя доменами не должна превышать 1.

</details>

**A15.** В чём разница `DoNotSchedule` и `ScheduleAnyway`?

<details><summary>Ответ</summary>

`DoNotSchedule` — при невозможности соблюсти ограничение под не планируется;
`ScheduleAnyway` — ограничение учитывается как пожелание.

</details>

**A16.** ⭐ Что такое taint и toleration?

<details><summary>Ответ</summary>

Taint — пометка на ноде, отталкивающая поды; toleration — объявление в поде,
что он терпит такой taint.

</details>

**A17.** Назови три эффекта taint и что каждый делает.

<details><summary>Ответ</summary>

`NoSchedule` — не планировать новые поды; `PreferNoSchedule` — стараться
не планировать; `NoExecute` — не планировать и вытеснить уже работающие.

</details>

**A18.** Притягивает ли toleration под к ноде?

<details><summary>Ответ</summary>

Нет: toleration только снимает запрет. Чтобы под попал именно на эти ноды,
нужны `nodeSelector` или `nodeAffinity`.

</details>

**A19.** Как выделить ноды под GPU-нагрузку так, чтобы туда попадали только нужные поды?

<details><summary>Ответ</summary>

Taint на GPU-ноды (`gpu=true:NoSchedule`), toleration у GPU-подов,
плюс `nodeSelector`/affinity по метке GPU, чтобы они туда попадали.

</details>

**A20.** Какие системные taint'ы ты знаешь?

<details><summary>Ответ</summary>

`node-role.kubernetes.io/control-plane`, `node.kubernetes.io/not-ready`,
`node.kubernetes.io/unreachable`, `memory-pressure`, `disk-pressure`,
`pid-pressure`, `unschedulable`.

</details>

**A21.** ⭐ Как `tolerationSeconds` связан с пятиминутным переездом подов
при падении ноды?

<details><summary>Ответ</summary>

Кубер автоматически добавляет подам tolerations на `not-ready`
и `unreachable` с `tolerationSeconds: 300`: поды выдерживают недоступность ноды
пять минут, после чего вытесняются и пересоздаются.

</details>

**A22.** Что такое PriorityClass и что такое preemption?

<details><summary>Ответ</summary>

PriorityClass задаёт приоритет пода; preemption — вытеснение подов
с меньшим приоритетом, когда для более важного пода нет места.

</details>

**A23.** ⭐ Что такое PodDisruptionBudget и от чего он защищает?

<details><summary>Ответ</summary>

Объект, ограничивающий число одновременно недоступных подов приложения
при **добровольных** нарушениях: drain, обновление нод, вытеснение автоскейлером.

</details>

**A24.** От чего PDB **не** защищает?

<details><summary>Ответ</summary>

От недобровольных: падение ноды, OOM, аппаратный сбой, удаление пода вручную.

</details>

**A25.** Чем опасен слишком строгий PDB?

<details><summary>Ответ</summary>

При `minAvailable`, равном числу реплик, вытеснить нельзя ни один под —
`drain` зависает, обслуживание и обновление кластера блокируются.

</details>

**A26.** Почему anti-affinity и PDB нужно использовать вместе?

<details><summary>Ответ</summary>

PDB считает реплики, но не знает об их размещении: если все они
на одной ноде, её падение унесёт приложение целиком, несмотря на PDB.

</details>

**A27.** Что делает `nodeName` в спеке пода?

<details><summary>Ответ</summary>

Жёстко закрепляет под за нодой в обход планировщика; применяется
для отладки и в особых случаях.

</details>

**A28.** Перераспределятся ли работающие поды, если изменить метки нод?

<details><summary>Ответ</summary>

Нет: правила `IgnoredDuringExecution` не приводят к перемещению
работающих подов. Перераспределение произойдёт только при пересоздании
(или с помощью descheduler).

</details>

---

### Блок B. «Что произойдёт»

```yaml
# B1
spec:
  replicas: 5
  template:
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector: { matchLabels: { app: web } }
              topologyKey: kubernetes.io/hostname
# в кластере 3 ноды
```
Вопрос: сколько подов запустится?

<details><summary>Ответ</summary>

Три: по одному на ноду, остальные два останутся `Pending`.

</details>

```yaml
# B2
# то же самое, но preferredDuringScheduling
```
Вопрос: что изменится?

<details><summary>Ответ</summary>

Все пять запустятся; планировщик постарается разложить их равномерно,
но при нехватке нод разместит несколько на одной.

</details>

```bash
# B3
kubectl taint nodes worker-1 team=data:NoExecute
# на worker-1 работают поды без соответствующего toleration
```
Вопрос: что с ними произойдёт?

<details><summary>Ответ</summary>

Поды без соответствующего toleration будут вытеснены с ноды
и пересозданы в другом месте.

</details>

```yaml
# B4
spec:
  tolerations:
    - key: gpu
      operator: Exists
      effect: NoSchedule
# нод с GPU три, обычных нод пять
```
Вопрос: где окажется под?

<details><summary>Ответ</summary>

Где угодно: toleration лишь разрешает попадание на ноды с taint,
но не притягивает. Нужен `nodeSelector`/affinity.

</details>

```yaml
# B5
spec:
  nodeSelector: { disktype: nvme }
# нод с такой меткой нет
```
Вопрос: статус пода и текст события?

<details><summary>Ответ</summary>

`Pending`, событие вида `0/N nodes are available: N node(s) didn't match
Pod's node affinity/selector`.

</details>

```yaml
# B6
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule
# 3 зоны, 7 реплик
```
Вопрос: как распределятся поды?

<details><summary>Ответ</summary>

Примерно 3/2/2 (разница между зонами не больше 1); если соблюсти нельзя,
часть подов останется `Pending`.

</details>

```yaml
# B7
kind: PodDisruptionBudget
spec:
  minAvailable: 3
# реплик всего 3
```
Вопрос: что произойдёт при `kubectl drain`?

<details><summary>Ответ</summary>

Drain не сможет вытеснить ни одного пода: бюджет не позволяет
опуститься ниже трёх доступных.

</details>

```bash
# B8
kubectl label node worker-1 disktype=hdd --overwrite
# на ноде работают поды с nodeAffinity на disktype=ssd
```
Вопрос: что с ними произойдёт?

<details><summary>Ответ</summary>

Ничего: правило `IgnoredDuringExecution` действует только при планировании.
Новые поды на эту ноду уже не попадут.

</details>

---

### Блок C. Практика

#### C1. Метки нод
```bash
kubectl get nodes --show-labels
kubectl label node <worker> disktype=ssd
kubectl label node <worker> team=platform
```
Запусти под с `nodeSelector` и убедись, что он попал куда надо.
Потом сними метку и посмотри, что произойдёт с работающим подом и с новым.

#### C2. nodeAffinity
Напиши правило: «только ноды с `disktype in (ssd, nvme)`, желательно с `team=platform`».
Проверь размещение. Сломай жёсткое условие и найди текст `FailedScheduling`.

#### C3. 🔑 Anti-affinity жёсткий
1. Deployment на 3 реплики с жёстким anti-affinity по `hostname`.
2. Проверь `kubectl get pods -o wide` — по одному на ноду?
3. Увеличь до 5 реплик и посмотри, что стало с лишними.
4. Прочитай событие планировщика.

<details><summary>Ответ</summary>

При пяти репликах и трёх нодах два пода останутся `Pending`
с сообщением о правилах anti-affinity.

</details>

#### C4. 🔑 Anti-affinity мягкий
Повтори C3 с `preferred` и сравни поведение при 5 репликах на 3 нодах.
Сформулируй, когда какой вариант выбирать.

#### C5. podAffinity
Запусти redis и приложение с `podAffinity` к нему. Убедись, что они на одной ноде.
Объясни, в каких случаях это оправдано.

#### C6. 🔑 topologySpreadConstraints
1. Разметь ноды «зонами»: `kubectl label node worker-1 topology.kubernetes.io/zone=a` и т. д.
2. Сделай Deployment на 6 реплик с `maxSkew: 1` по зонам.
3. Проверь распределение.
4. Поставь `maxSkew: 2` и сравни.

#### C7. 🔑 Taints и tolerations
1. `kubectl taint nodes worker-2 special=true:NoSchedule`
2. Запусти обычный под — попадёт ли он на worker-2?
3. Добавь toleration и повтори.
4. Добавь `nodeSelector`/affinity, чтобы под гарантированно попал именно туда.
5. Сформулируй, почему toleration недостаточно.

<details><summary>Ответ</summary>

Toleration разрешает планирование на ноду с taint, но не гарантирует
попадание именно туда; для гарантии нужен селектор по метке ноды.

</details>

#### C8. NoExecute
1. Запусти поды на ноде.
2. Навесь taint с эффектом `NoExecute`.
3. Наблюдай, что произойдёт с работающими подами.
4. Сними taint.

#### C9. tolerationSeconds
Посмотри у любого пода:
```bash
kubectl get pod <pod> -o yaml | grep -A12 tolerations
```
Найди `not-ready` и `unreachable` с `tolerationSeconds: 300`.
Поставь своему приложению 30 секунд, останови ноду (kind: `docker stop`)
и замерь, насколько быстрее переехали поды.

<details><summary>Ответ</summary>

Со `tolerationSeconds: 30` поды пересоздаются примерно через полминуты
после перехода ноды в `NotReady` вместо пяти минут.

</details>

#### C10. PriorityClass
1. Создай два PriorityClass: `low` и `high`.
2. Забей ноду подами с `low`.
3. Запусти под с `high` и посмотри, вытеснит ли он кого-нибудь.
4. Найди событие `Preempted`.

#### C11. 🔑 PodDisruptionBudget
1. Deployment на 3 реплики, PDB с `minAvailable: 2`.
2. `kubectl drain` ноды с двумя репликами.
3. Наблюдай, как drain ждёт.
4. Поставь `minAvailable: 3` и убедись, что drain блокируется полностью.

<details><summary>Ответ</summary>

При `minAvailable: 2` drain вытесняет поды по одному, дожидаясь
готовности замены; при `minAvailable: 3` drain не может вытеснить ничего.

</details>

#### C12. 🔑 Отказоустойчивое приложение
Собери манифест по рецепту из конспекта (§8): реплики + spread + anti-affinity +
tolerationSeconds + PDB. Останови ноду и замерь, сколько запросов потерялось
(гоняя curl в цикле).

#### C13. Разбор Pending (со звёздочкой)
Создай четыре пода, каждый из которых `Pending` по своей причине:
ресурсы, nodeSelector, taint, anti-affinity. Для каждого выпиши точное
сообщение планировщика. Это готовая шпаргалка для темы про troubleshooting.

#### C14. Descheduler (со звёздочкой)
Прочитай, что делает descheduler, и опиши, какую проблему он решает
(подсказка: `IgnoredDuringExecution` и перекос после добавления нод).

---

### Блок D. Инциденты

**D1.** Упала одна нода — приложение легло полностью, хотя было 3 реплики. Почему?

<details><summary>Ответ</summary>

Все реплики были на одной ноде: не настроены anti-affinity
или topology spread.

</details>

**D2.** После добавления двух новых нод старые остались перегружены,
а новые пустуют. Объясни.

<details><summary>Ответ</summary>

Кубер не перемещает работающие поды: распределение изменится
только при пересоздании подов (деплой, рестарт) или с помощью descheduler.

</details>

**D3.** `kubectl drain` висит и не может вытеснить поды. Две причины.

<details><summary>Ответ</summary>

PodDisruptionBudget не позволяет вытеснить поды; на ноде есть поды
без контроллера (нужен `--force`) или поды DaemonSet
(нужен `--ignore-daemonsets`); поды не завершаются из-за долгого grace period.

</details>

**D4.** Поды не планируются на новые ноды, хотя ресурсы свободны. Что проверить?

<details><summary>Ответ</summary>

Taint'ы на новых нодах, отсутствие нужных меток для nodeSelector/affinity,
статус ноды (`Ready`, `SchedulingDisabled`), правила anti-affinity/spread,
доступность томов.

</details>

**D5.** GPU-ноды заняты обычными приложениями. Что настроить?

<details><summary>Ответ</summary>

Taint на GPU-ноды и tolerations только у GPU-нагрузок; дополнительно
метки и nodeAffinity, чтобы GPU-поды туда попадали.

</details>

**D6.** После установки taint на ноду часть подов внезапно исчезла с неё.
Какой эффект был использован?

<details><summary>Ответ</summary>

`NoExecute`.

</details>

**D7.** Приложение с жёстким anti-affinity нельзя отмасштабировать
выше числа нод. Как правильно?

<details><summary>Ответ</summary>

Использовать мягкий anti-affinity или `topologySpreadConstraints`
с `ScheduleAnyway` — тогда масштабирование не упирается в число нод.

</details>

**D8.** Обновление кластера остановилось: одна нода не может уйти на обслуживание.
Диагностика и решение.

<details><summary>Ответ</summary>

Смотреть `kubectl get pdb -A` и события drain: скорее всего,
слишком строгий бюджет или недостаток реплик. Временно ослабить PDB,
увеличить число реплик и продолжить.

</details>

**D9.** Критичный сервис не запускается из-за нехватки ресурсов,
хотя на нодах полно второстепенных подов. Что настроить?

<details><summary>Ответ</summary>

PriorityClass для критичного сервиса, чтобы сработало вытеснение
менее важных подов; заодно проверить requests и квоты.

</details>

**D10.** Реплики оказались в одной зоне доступности, зона упала.
Что нужно было настроить заранее?

<details><summary>Ответ</summary>

`topologySpreadConstraints` по `topology.kubernetes.io/zone`
(или anti-affinity с зональным topologyKey) плюс PDB.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое Affinity и Anti-Affinity? *(вопрос роадмапа)*

<details><summary>Ответ</summary>

Правила притяжения и отталкивания при планировании: nodeAffinity (к нодам),
podAffinity (к подам), podAntiAffinity (от подов); главное применение —
разнести реплики по нодам и зонам.

</details>

**2.** Чем nodeAffinity отличается от nodeSelector?

<details><summary>Ответ</summary>

Поддержкой операторов, логического ИЛИ и мягких правил с весами.

</details>

**3.** Что означает required и preferred?

<details><summary>Ответ</summary>

`required` — обязательное условие, `preferred` — пожелание с весом.

</details>

**4.** Что такое topologyKey?

<details><summary>Ответ</summary>

Метка ноды, определяющая домен «вместе»: нода, зона, регион.

</details>

**5.** ⭐ Что такое taints и tolerations?

<details><summary>Ответ</summary>

Taint — отталкивающая пометка на ноде; toleration — разрешение у пода
игнорировать её.

</details>

**6.** Чем affinity отличается от taint по логике?

<details><summary>Ответ</summary>

Affinity описывает под и притягивает; taint описывает ноду и отталкивает.

</details>

**7.** Что такое topologySpreadConstraints?

<details><summary>Ответ</summary>

Ограничения равномерного распределения подов по доменам топологии
с параметром `maxSkew`.

</details>

**8.** Как обеспечить, чтобы реплики не оказались на одной ноде?

<details><summary>Ответ</summary>

`podAntiAffinity` по `kubernetes.io/hostname` или topology spread,
плюс PDB для защиты при обслуживании.

</details>

**9.** Что такое PodDisruptionBudget?

<details><summary>Ответ</summary>

Бюджет доступности: сколько подов приложения может быть недоступно
при добровольных нарушениях.

</details>

**10.** Почему поды переезжают с упавшей ноды не сразу, а через пять минут?

<details><summary>Ответ</summary>

Из-за автоматических tolerations на `not-ready`/`unreachable`
с `tolerationSeconds: 300`.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю affinity и anti-affinity за 30 секунд
- [ ] Понимаю разницу «под притягивается» и «нода отталкивает»
- [ ] Разносил реплики по нодам жёстко и мягко
- [ ] Пробовал `topologySpreadConstraints` с `maxSkew`
- [ ] Ставил taint и подбирал toleration + селектор
- [ ] Видел эффект `NoExecute` на работающих подах
- [ ] Знаю, откуда берётся пятиминутный переезд подов
- [ ] Настраивал PDB и видел, как он блокирует drain
- [ ] Собрал «отказоустойчивый» манифест и проверил его падением ноды
