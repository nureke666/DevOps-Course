---
title: "06. cgroups v2 и контейнеры"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 06. Опирается на"
---

# 06. cgroups v2 и контейнеры

> Блок → Deep Linux Troubleshooting & Performance → тема 06. Опирается на
> [../Docker/01_containers_intro.md](/docker/01-containers-intro) (namespaces и cgroups на пальцах),
> [../Docker/11_troubleshooting.md](/docker/11-troubleshooting) (§5 «Тормозит»),
> [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources) (requests/limits, QoS),
> [../Kubernetes/20_troubleshooting.md](/kubernetes/20-troubleshooting) (OOMKilled, `kubectl debug`)
> и [02_cpu_memory.md](/performance/02-cpu-memory) (как OOM killer выбирает жертву).
>
> **После темы ты умеешь:** найти cgroup любого процесса и прочитать его файлы; по
> `memory.events` доказать OOM в контейнере, по `cpu.stat` — CFS throttling; объяснить, почему
> контейнер тормозит при 30% среднего CPU; читать PSI; разложить requests/limits Docker и
> Kubernetes по файлам cgroup; отличить OOMKilled от node OOM и Evicted; отладить контейнер
> без shell через `nsenter`, `kubectl debug` и `crictl`.

---

## 🗺️ Карта темы

```text
 docker run --cpus/--memory          Pod: requests / limits
          │                                  │ kubelet (QoS, oom_score_adj)
          └──────────────┬───────────────────┘
                         ▼
          containerd / runc  ──► пишет файлы в /sys/fs/cgroup/&lt;путь контейнера&gt;/
                         │
       ┌─────────────────┼───────────────────────┬─────────────────────────┐
       ▼                 ▼                       ▼                         ▼
  memory.max        cpu.max               cpu.weight                pids.max
  memory.high       «квота период»        доля при конкуренции      лимит процессов
       │                 │
       ▼                 ▼
  memory.events     cpu.stat               *.pressure (PSI)  ◄── сколько времени задачи
  oom / oom_kill    nr_throttled           some / full           ждали ресурс
       │                 │                       │
       └─────────────────┴───────────┬───────────┘
                                     ▼
                ДОКАЗАТЕЛЬСТВО: «убило лимитом» · «душит квота» · «ждёт памяти»
```text
---

## 1. Иерархия cgroups v2 и systemd

```bash
stat -fc %T /sys/fs/cgroup                   # cgroup2fs → v2 (tmpfs → v1/hybrid)
cat /sys/fs/cgroup/cgroup.controllers        # cpuset cpu io memory hugetlb pids rdma misc
cat /proc/4242/cgroup                        # 0::/system.slice/nginx.service — где процесс
```text
В v2 одна иерархия: каждый процесс ровно в одном cgroup, лимиты родителя ограничивают детей.
systemd — хозяин дерева:

```text
/sys/fs/cgroup   (-.slice)
├── init.scope                       PID 1
├── system.slice                     сервисы: nginx.service, ssh.service …
│   └── docker-&lt;id&gt;.scope            контейнеры Docker (cgroup driver systemd)
├── user.slice
│   └── user-1000.slice/…            SSH-сессии, пользовательские процессы
├── machine.slice                    VM libvirt, systemd-nspawn
└── kubepods.slice                   поды Kubernetes (kubelet, driver systemd)
    ├── kubepods-pod&lt;uid&gt;.slice                    Guaranteed
    ├── kubepods-burstable.slice/kubepods-burstable-pod&lt;uid&gt;.slice/cri-containerd-&lt;id&gt;.scope
    └── kubepods-besteffort.slice/…
```text
> ⚠️ В kind у kubelet `cgroupRoot: /kubelet`, поэтому внутри ноды путь другой:
> `kubelet.slice/kubelet-kubepods.slice/kubelet-kubepods-burstable.slice/…`.
> Надёжнее не угадывать путь, а брать его из `/proc/&lt;PID&gt;/cgroup`.

```bash
systemd-cgls --no-pager | head -30          # дерево cgroup с процессами
systemd-cgtop                               # «top» по cgroup: Tasks, %CPU, Memory, Input/s, Output/s
systemctl show nginx -p ControlGroup -p MemoryCurrent -p MemoryMax -p CPUQuotaPerSecUSec
sudo systemctl set-property nginx.service CPUQuota=50% MemoryMax=512M   # сразу + сохраняется
sudo systemctl set-property --runtime nginx.service CPUQuota=50%        # только до ребута
sudo systemd-run --scope -p CPUQuota=20% -p MemoryMax=300M stress-ng --cpu 1 --timeout 30s
```text
`systemd-run --scope` — лучший способ поэкспериментировать с лимитами без Docker.

---

## 2. Файлы, которые надо уметь читать

Внутри контейнера cgroup namespace показывает **его** cgroup как `/sys/fs/cgroup` — поэтому
`docker exec app cat /sys/fs/cgroup/cpu.stat` и `kubectl exec … cat /sys/fs/cgroup/cpu.stat`
читают именно лимиты контейнера.

| Файл | Что | Когда смотреть |
|------|-----|----------------|
| `cgroup.procs` | PID-ы в этом cgroup | Кто внутри |
| `memory.current` / `memory.peak` | Текущее / пиковое потребление (включая page cache!) | «Сколько ест» |
| `memory.max` | Жёсткий лимит → reclaim, затем OOM kill внутри cgroup | OOMKilled |
| `memory.high` | Мягкий лимит → замедление и принудительный reclaim, без kill | «Тормозит, но не падает» |
| `memory.low` / `memory.min` | Защита от reclaim (best effort / гарантированно) | Соседи вытесняют кэш |
| `memory.events` | Счётчики `low high max oom oom_kill oom_group_kill` | ⭐ Доказательство OOM |
| `memory.stat` | `anon`, `file`, `active_file`, `inactive_file`, `shmem`, … | Из чего состоит память |
| `memory.swap.max` | Лимит swap | Контейнер ушёл в swap |
| `cpu.max` | `квота период` в мкс, `max 100000` = без лимита | CPU limit |
| `cpu.weight` | Доля CPU при конкуренции (1–10000, по умолчанию 100) | CPU request |
| `cpu.stat` | `usage_usec`, `nr_periods`, `nr_throttled`, `throttled_usec`, … | ⭐ Доказательство throttling |
| `cpu.max.burst` | Разрешённый «перерасход» квоты | Сглаживание всплесков |
| `io.max` / `io.stat` | Лимиты / статистика I/O по устройствам | Медленный диск в контейнере |
| `pids.max` / `pids.current` / `pids.events` | Лимит процессов | `fork: Resource temporarily unavailable` |
| `cpu.pressure`, `memory.pressure`, `io.pressure` | PSI этого cgroup | Сколько задачи **ждали** |

---

## 3. Память: memory.max, memory.high, memory.events

```text
usage ──────────────────────────────────────────────►
        memory.low       memory.high            memory.max
   ─────────┼─────────────────┼──────────────────────┼──────
   защищено от      обычная зона   тормозим аллокации,    reclaim не помог →
   reclaim                         гоним в reclaim        OOM kill В ЭТОМ cgroup
                                   (события high++)       (max++, oom++, oom_kill++)
```text
```text
# пример вывода: процесс в контейнере с --memory=64m попытался взять 200 МБ
$ cat /sys/fs/cgroup/memory.events
low 0
high 0
max 52              ← 52 раза упирались в лимит (reclaim спасал)
oom 1               ← один раз reclaim не помог — OOM внутри cgroup
oom_kill 1          ← убит один процесс
oom_group_kill 0
sock_throttled 0
```text
| Счётчик | Значит |
|---------|--------|
| `high` | Сколько раз задачи тормозили и шли в reclaim из-за `memory.high` |
| `max` | Сколько раз usage упирался в `memory.max` |
| `oom` | Сколько раз лимит достигнут и аллокация вот-вот упадёт (OOM в этом cgroup) |
| `oom_kill` | Сколько процессов этого cgroup убил **любой** OOM killer (в том числе глобальный!) |
| `oom_group_kill` | Сколько раз убили группу целиком (`memory.oom.group=1`) |

В `dmesg` OOM лимита cgroup выглядит так (разбор полей OOM-отчёта — в [02](/performance/02-cpu-memory)):
```text
# фрагмент реального отчёта
oom-kill:constraint=CONSTRAINT_MEMCG,…,oom_memcg=/system.slice/docker-6844….scope,task_memcg=/system.slice/docker-6844….scope,task=python,pid=239168,uid=0
Memory cgroup out of memory: Killed process 239168 (python) total-vm:206560kB, anon-rss:64624kB, file-rss:5468kB, …
```text
`CONSTRAINT_MEMCG` + `oom_memcg=` — убил лимит cgroup. Глобальный OOM — `CONSTRAINT_NONE` и
строка `Out of memory: Killed process …`.

**Page cache внутри лимита.** `memory.current` включает кэш файлов, который ядро вытеснит
при нужде. Поэтому «контейнер съел 95% лимита» ещё не авария. Kubelet и `kubectl top`
считают **working set** = `memory.current − inactive_file`:

```bash
C=/sys/fs/cgroup
echo $(( ($(cat $C/memory.current) - $(awk '/^inactive_file/{print $2}' $C/memory.stat)) / 1048576 )) MiB
grep -E '^(anon|file|active_file|inactive_file|shmem) ' $C/memory.stat
```text
Растёт `anon` — память процесса (кандидат в утечку). Растёт `file` — кэш, обычно не страшно.
`shmem` (tmpfs, `/dev/shm`, `emptyDir: medium: Memory`) — **не вытесняется** и тоже считается в лимит.

---

## 4. CPU: cpu.max и CFS throttling

```bash
cat /sys/fs/cgroup/cpu.max        # 50000 100000 → 50 мс CPU на каждые 100 мс = 0,5 ядра
cat /sys/fs/cgroup/cpu.stat
```text
```text
# реальный вывод: docker run --cpus=0.5 alpine, busy loop 5 секунд
usage_usec 2531374
user_usec 2523482
system_usec 7892
nice_usec 0
core_sched.force_idle_usec 0
nr_periods 51            ← периодов по 100 мс, в которых были runnable-задачи
nr_throttled 50          ← в 50 из них квота кончилась и cgroup ЗАМОРОЗИЛИ до конца периода
throttled_usec 2487548   ← суммарно 2,49 с в заморозке
nr_bursts 0
burst_usec 0
```text
Доля throttling = `nr_throttled / nr_periods` (здесь 98%). `throttled_usec` копится по каждому
CPU отдельно, поэтому у многопоточных может превышать реальное время.

### Почему тормозит при 30% «среднего» CPU

```text
limit 1 CPU = cpu.max "100000 100000": 100 мс CPU-времени на период 100 мс, на ВСЕ потоки

период 100 мс:  0 ──12,5 мс─────────────────────────────────────── 100 мс
8 потоков:      ████████  ← за 12,5 мс вместе сожгли 100 мс квоты
                         ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  THROTTLED 87,5 мс
запрос:         пришёл на 13-й мс → ждёт до начала следующего периода → +87 мс к латентности

в среднем за минуту: всплески редкие → «CPU 30% от лимита», а p99 +90 мс
```text
Средняя загрузка скрывает всплески: GC, JIT, пачка параллельных запросов на N потоках
выедают квоту за миллисекунды. Графики CPU usage в Grafana это не покажут — нужен throttling:

```promql
sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{container!=""}[5m]))
  / sum by (pod) (rate(container_cpu_cfs_periods_total{container!=""}[5m]))
```text
| Лечение | Когда |
|---------|-------|
| Поднять `limits.cpu` или убрать CPU limit, оставив `requests` | Latency-чувствительные сервисы; CPU сжимаемый, request гарантирует долю |
| Уменьшить параллелизм: `GOMAXPROCS` (Go 1.25+ учитывает cgroup-лимит сам, раньше — automaxprocs), `-XX:ActiveProcessorCount` для JVM, число воркеров | Приложение видит все ядра хоста и плодит потоки |
| `cpu.max.burst` — копить неиспользованную квоту на всплески | Ядро 5.14+; в Docker/Kubernetes штатного параметра нет |
| Меньше параллельных GC-потоков, прогрев JIT | JVM-сервисы с пиками на старте |

> ⚠️ `nproc` внутри контейнера с `--cpus=0.5` показывает **все** ядра хоста: квота не меняет
> CPU affinity. Меняет только `--cpuset-cpus`. Смотри `cat /sys/fs/cgroup/cpu.max`.

`cpu.weight` работает только при конкуренции: если ядро свободно, контейнер с weight 10
получит его целиком. Weight — про справедливость, max — про потолок.

---

## 5. PSI: сколько времени задачи ждут ресурс

Pressure Stall Information — прямой ответ на вопрос saturation из USE ([01](/performance/01-methodology)):
какую долю времени задачи **простаивали**, ожидая CPU, память или I/O.

```bash
cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io   # вся система
cat /sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/cpu.pressure    # конкретный cgroup
```text
```text
# реальный вывод cpu.pressure того же контейнера с --cpus=0.5 сразу после нагрузки
some avg10=4.56 avg60=0.87 avg300=0.18 total=1030523
full avg10=4.56 avg60=0.87 avg300=0.18 total=1030476
```text
| Поле | Смысл |
|------|-------|
| `some` | Доля времени (%), когда **хотя бы одна** задача ждала ресурс |
| `full` | Доля времени, когда **все** не-idle задачи ждали одновременно (работа стоит) |
| `avg10/60/300` | Скользящие средние за 10 с, 1 мин, 5 мин |
| `total` | Накопленное время ожидания, мкс — для `rate()` в мониторинге |

- `cpu` `full` на уровне всей системы не определён и с ядра 5.13 всегда 0; в cgroup —
  осмысленный (throttling контейнера виден именно там).
- `memory some` устойчиво выше ~10% — задачи регулярно ждут reclaim/swap-in, близко к трэшингу;
  `io full` в единицах процентов — диск держит всю работу. Это ориентиры, а не стандарт:
  сравнивай с нормой своего сервиса.
- PSI используют: systemd-oomd (`ManagedOOMMemoryPressure=kill` в юните/слайсе), kubelet —
  метрики `container_pressure_cpu_waiting_seconds_total` (some),
  `container_pressure_memory_stalled_seconds_total` (full) и др. на `/metrics/cadvisor`
  (GA в Kubernetes 1.36).
- Триггеры: запись `some 150000 1000000` в pressure-файл + `poll()` — уведомление, если за
  1 с набралось 150 мс ожидания (так работают userspace OOM-демоны).

---

## 6. Как Docker и Kubernetes раскладывают лимиты по cgroup

**Docker** (cgroup driver systemd → `/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope`):

| Флаг | Файл | Проверено на Docker 29 |
|------|------|------------------------|
| `--memory=256m` | `memory.max` | `268435456` |
| (без `--memory-swap`) | `memory.swap.max` | `268435456` — swap ещё столько же |
| `--memory-reservation=128m` | `memory.low` | `134217728` |
| `--cpus=0.5` | `cpu.max` | `50000 100000` |
| `--cpu-shares=512` | `cpu.weight` | `59` (через конвертацию shares → weight) |
| `--pids-limit=100` | `pids.max` | `100` |
| `--cpuset-cpus=0,1` | `cpuset.cpus` | меняет и `nproc` |

**Kubernetes** (kubelet + containerd/runc):

| Поле пода | Файл cgroup контейнера | Нюанс |
|-----------|------------------------|-------|
| `limits.cpu: 500m` | `cpu.max` = `50000 100000` | Период 100 мс, квота = limit × 100 мс |
| `requests.cpu` | `cpu.weight` | millicores → shares (`m × 1024/1000`) → weight |
| `limits.memory` | `memory.max` | Превышение → OOM kill, код 137 |
| `requests.memory` | по умолчанию **не пишется** в cgroup | Только планировщик и eviction; `memory.min`/`memory.high` — лишь с alpha-фичей MemoryQoS |
| QoS-класс | `oom_score_adj` процессов | Guaranteed −997, BestEffort 1000, Burstable 2…999 по доле request от памяти ноды |
| (cgroup v2, k8s 1.28+) | `memory.oom.group = 1` | OOM убивает **все** процессы контейнера; `singleProcessOOMKill` в kubelet (1.32+) возвращает старое поведение |

Конвертация `requests.cpu` → `cpu.weight` менялась:

| request | shares | weight (старая линейная формула KEP-2254) | weight (новая, runc 1.3.2+ / crun 1.23+) |
|---------|--------|-------------------------------------------|------------------------------------------|
| 100m | 102 | 4 | 17 |
| 500m | 512 | 20 | 59 |
| 1 CPU | 1024 | 39 | ≈100 |

Со старой формулой под с `requests: 1` получал weight 39 — меньше дефолтных 100 у системных
сервисов, и под конкуренцией проигрывал им CPU. Новая формула (Kubernetes blog, январь 2026)
возвращает «1 CPU ≈ 100». Какая у тебя — видно по `cat cpu.weight` в поде.

```bash
# найти cgroup контейнера пода на ноде
PID=$(sudo crictl inspect $(sudo crictl ps -q --name app) | jq .info.pid)
cat /proc/$PID/cgroup                                  # 0::/kubepods.slice/…/cri-containerd-&lt;id&gt;.scope
cat /sys/fs/cgroup$(cut -d: -f3 /proc/$PID/cgroup)/cpu.stat
kubectl exec app-7d9f -- cat /sys/fs/cgroup/memory.events   # или изнутри пода
```text
---

## 7. OOMKilled vs node OOM vs Evicted

| | OOMKilled (лимит контейнера) | Node OOM (глобальный) | Evicted (kubelet) |
|---|------------------------------|-----------------------|-------------------|
| Кто убил | Ядро, OOM внутри cgroup | Ядро, на ноде кончилась память | Kubelet, заранее |
| Почему | usage > `limits.memory` | Сумма всего > RAM ноды (limits > allocatable, не-k8s процессы) | `memory.available` ниже порога eviction (по умолчанию 100Mi) |
| Кого | Процесс(ы) этого контейнера | Макс. badness с учётом `oom_score_adj`: BestEffort первыми | По QoS и превышению requests |
| `dmesg` | `CONSTRAINT_MEMCG`, `Memory cgroup out of memory` | `CONSTRAINT_NONE`, `Out of memory: Killed process` | ничего |
| В поде | `lastState.terminated.reason: OOMKilled`, 137 | Тоже может быть `OOMKilled`/137 | `status.reason: Evicted` |
| `memory.events` контейнера | `oom` и `oom_kill` растут | растёт только `oom_kill` | без изменений |
| События | — | нода: `SystemOOM` | под: `Evicted` |

```bash
kubectl get pod app -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'; echo
kubectl get events -A --field-selector reason=SystemOOM
kubectl get events -A --field-selector reason=Evicted
kubectl exec app -- cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.peak
# на ноде: journalctl -k | grep -E 'CONSTRAINT_(MEMCG|NONE)|Killed process'
```text
Главное различие — `oom`: он растёт, только когда упёрлись в **свой** лимит. Если `oom_kill`
вырос, а `oom` нет — контейнер стал жертвой нехватки памяти на ноде, и поднимать ему limit
бесполезно: чинить надо ноду (requests ≈ реальному потреблению, резерв `kube-reserved`/
`system-reserved`, меньше overcommit по limits).

---

## 8. Отладка контейнера без инструментов

Образ distroless/scratch: нет shell, `ps`, `ss`, `curl`. Варианты по возрастанию мощности:

**`docker exec` против `nsenter`:**

| | `docker exec` | `nsenter -t PID …` с хоста |
|---|---------------|---------------------------|
| Бинари | Только из образа | С хоста (если не входить в mount ns) |
| Namespaces | Все сразу | Выборочно: `-n` сеть, `-p` PID, `-m` ФС, `-u`, `-i`, `-a` все |
| Ограничения | seccomp, capabilities, AppArmor, cgroup контейнера | Полный root хоста, вне cgroup контейнера |
| Зависший runtime | Не работает | Работает — нужен только PID |

```bash
PID=$(docker inspect -f '&#123;&#123;.State.Pid&#125;&#125;' app)            # в k8s: crictl inspect … | jq .info.pid
sudo nsenter -t $PID -n ss -tanp                         # сеть контейнера, ss с хоста
sudo nsenter -t $PID -n tcpdump -i eth0 -nn port 5432    # tcpdump в netns контейнера
sudo nsenter -t $PID -m -u -i -n -p sh                   # как exec (если в образе есть sh)
sudo ls /proc/$PID/root/etc/                             # ФС контейнера без входа в mount ns
```text
⚠️ `nsenter -t PID -p ps` без `-m` покажет процессы **хоста**: `ps` читает `/proc`, а `/proc`
остался хостовым. Для PID namespace входи вместе с `-m` (или читай `/proc/&lt;PID&gt;/…` снаружи).

**Отладочный контейнер рядом (Docker):**
```bash
docker run --rm -it --pid=container:app --network=container:app nicolaka/netshoot
# внутри: ps aux (процессы app), ss -tanp, tcpdump, ls /proc/1/root/ — ФС app
```text
**`kubectl debug` (Kubernetes):**
```bash
kubectl debug -it app-7d9f --image=nicolaka/netshoot --target=app   # ephemeral container
#   --target → общий PID namespace с контейнером app: его процесс = PID 1,
#   ФС — через /proc/1/root; профиль general добавляет SYS_PTRACE (strace, py-spy работают)
kubectl debug app-7d9f -it --copy-to=app-debug --share-processes --image=busybox   # копия пода
kubectl debug node/perf-worker -it --image=ubuntu --profile=sysadmin
#   поды на ноде: хостовые namespaces, корень ноды в /host → chroot /host для хостовых бинарей
```text
| Профиль (kubectl 1.37, по умолчанию `general`) | Pod / ephemeral | Node |
|------------------------------------------------|-----------------|------|
| `general` | `SYS_PTRACE` | хостовые namespaces, корень в `/host` |
| `baseline` / `restricted` | без привилегий (PSS-совместимо) | изолированные namespaces |
| `netadmin` | `NET_ADMIN`, `NET_RAW` | + хостовые namespaces |
| `sysadmin` | `privileged` | `privileged` + хостовые namespaces |

> ⚠️ `kubectl debug node/…` создаёт под `node-debugger-&lt;нода&gt;-&lt;хеш&gt;`, который остаётся после
> выхода — удаляй: `kubectl get pods | grep node-debugger` → `kubectl delete pod …`.
> Ephemeral-контейнер удалить из пода нельзя — он исчезнет только вместе с подом.

**crictl на ноде** (в kind: `docker exec -it perf-control-plane bash`):
```bash
sudo crictl ps --name app                 # контейнеры (есть и остановленные: -a)
sudo crictl inspect &lt;id&gt; | jq .info.pid   # PID на ноде → nsenter, /proc/PID/cgroup
sudo crictl stats                         # CPU %, MEM по контейнерам
sudo crictl logs --tail 50 &lt;id&gt;           # логи, даже если kubectl недоступен
sudo crictl pods --name app               # sandbox-поды
```text
---

## 9. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| «CPU контейнера 30% от лимита — CPU ни при чём» | Среднее прячет throttling | `cpu.stat`: `nr_throttled/nr_periods`, метрика throttled periods |
| OOMKilled → limit ×2 | Может быть node OOM или утечка | `memory.events` (`oom` vs `oom_kill`), `memory.peak`, рост `anon` |
| «Контейнер у лимита памяти — авария» | Лимит забит page cache | Working set = current − inactive_file |
| `nproc`/`os.cpu_count()` для размера пулов | Видят все ядра хоста | Читать `cpu.max`; Go 1.25+ и JVM (container support) делают это сами |
| Путь cgroup «угадан» из статьи | Driver systemd/cgroupfs, kind, QoS меняют путь | `/proc/&lt;PID&gt;/cgroup` |
| `tmpfs`/`emptyDir: Memory` без учёта | shmem считается в лимит и не вытесняется | Учитывать в `limits.memory`, `sizeLimit` |
| `nsenter -p` без `-m` | `ps` показывает хост | `-m -p` или `/proc/&lt;PID&gt;` снаружи |
| `docker exec` в distroless | Нет shell | `nsenter -n`, `--pid=container:`, `kubectl debug --target` |
| Забытый `node-debugger-*` под | Привилегированный под висит на ноде | Удалять сразу после отладки |
| CPU limit = request на всём подряд | Throttling у latency-сервисов | Для них — без CPU limit или с запасом |

---

## 💼 Как это в DevOps

- «Сервис тормозит в k8s, а ноды свободны» — первым делом throttling: дашборд
  `container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total` по подам.
  Многие команды убирают CPU limits у latency-чувствительных сервисов, оставляя requests.
- OOMKilled разбирают по фактам: `memory.peak`, рост `anon`, `oom` vs `oom_kill`,
  события `SystemOOM` на ноде. Только потом решают — чинить утечку, поднимать limit или ноду.
- PSI в 2026 — стандартная метрика: kubelet отдаёт её на `/metrics/cadvisor`, и алерт
  «memory pressure some > X%» ловит проблему раньше OOM.
- Distroless-образы — норма безопасности, поэтому `kubectl debug` с профилями и
  `nsenter` с ноды должны быть в runbook, а права на ephemeral containers — в RBAC дежурных.
- Лимиты сервисов вне Kubernetes задают systemd-юнитами (`MemoryMax=`, `CPUQuota=`) и
  раскатывают Ansible'ом — это те же cgroups.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| cgroup v2? | `stat -fc %T /sys/fs/cgroup` → `cgroup2fs` |
| В каком cgroup процесс | `cat /proc/PID/cgroup` |
| Дерево / top по cgroup | `systemd-cgls`, `systemd-cgtop` |
| Лимит на сервис | `systemctl set-property svc MemoryMax=512M CPUQuota=50%` |
| Эксперимент с лимитом | `systemd-run --scope -p MemoryMax=300M -p CPUQuota=20% cmd` |
| Доказать OOM лимита | `cat memory.events` → `oom`, `oom_kill`; `memory.peak` |
| Working set | `memory.current − inactive_file` из `memory.stat` |
| Доказать throttling | `cat cpu.stat` → `nr_throttled / nr_periods`, `throttled_usec` |
| Лимит CPU | `cat cpu.max` → `квота период` |
| PSI | `cat /proc/pressure/{cpu,memory,io}`, `cat &lt;cgroup&gt;/cpu.pressure` |
| PID контейнера | `docker inspect -f '&#123;&#123;.State.Pid&#125;&#125;' c` / `crictl inspect id \| jq .info.pid` |
| Сеть контейнера с хост-утилитами | `sudo nsenter -t PID -n ss -tanp` |
| ФС контейнера | `sudo ls /proc/PID/root/` |
| Отладочный сосед (Docker) | `docker run -it --pid=container:c --network=container:c nicolaka/netshoot` |
| Ephemeral container | `kubectl debug -it pod --image=… --target=ctr` |
| Отладка ноды | `kubectl debug node/N -it --image=ubuntu --profile=sysadmin` → `chroot /host` |
| Node OOM | `kubectl get events -A --field-selector reason=SystemOOM` |

---

## 🧠 Что запомнить

1. cgroup процесса — всегда из `/proc/PID/cgroup`; внутри контейнера свой cgroup виден как `/sys/fs/cgroup`.
2. `memory.max` убивает, `memory.high` тормозит, `memory.low/min` защищают.
3. `memory.events`: `oom` — упёрлись в свой лимит; `oom_kill` — убиты любым OOM killer.
4. `memory.current` включает page cache; решения принимают по working set и `anon`.
5. `cpu.max` = квота на период 100 мс на все потоки; `nr_throttled/nr_periods` — доказательство throttling.
6. Контейнер тормозит при низком среднем CPU, потому что всплески сжигают квоту за миллисекунды.
7. `cpu.weight` (requests) работает только при конкуренции; `nproc` не видит квоту.
8. PSI `some`/`full` отвечают на «сколько ждали» — это saturation в чистом виде.
9. OOMKilled, node OOM и Evicted — три разные причины с разными доказательствами и лечением.
10. Без shell в образе: `nsenter -n` с хоста, `--pid=container:`, `kubectl debug --target`, `crictl`.

➡️ Дальше: [07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace) · задачи: 06_cgroups_containers_tasks.md


---

### Блок A. Теория


**A1.** Как убедиться, что система на cgroup v2, и найти cgroup конкретного процесса?
Почему путь к cgroup контейнера не стоит «угадывать»?

<details><summary>Ответ</summary>

`stat -fc %T /sys/fs/cgroup` → `cgroup2fs` (v2); `cat /sys/fs/cgroup/cgroup.controllers`
покажет контроллеры. cgroup процесса — `cat /proc/PID/cgroup` → строка `0::/путь`. Путь зависит
от cgroup driver (systemd/cgroupfs), рантайма, QoS-класса пода и настроек kubelet (в kind —
`cgroupRoot: /kubelet`), поэтому его берут из `/proc/PID/cgroup`, а не из статьи.

</details>

**A2.** Чем отличаются `memory.max`, `memory.high` и `memory.low`/`memory.min`?

<details><summary>Ответ</summary>

`memory.max` — жёсткий потолок: при достижении reclaim, а если не помог — OOM kill внутри
cgroup. `memory.high` — мягкий: превышение тормозит аллокации и гонит в принудительный reclaim,
но не убивает. `memory.low` — best-effort защита от reclaim (память ниже порога отбирают в последнюю
очередь), `memory.min` — гарантированная защита.

</details>

**A3.** ⭐ Что означают счётчики `memory.events`? Чем `oom` отличается от `oom_kill`?

<details><summary>Ответ</summary>

`low`/`high` — сколько раз срабатывали соответствующие пороги (reclaim ниже low, торможение
из-за high); `max` — сколько раз упирались в `memory.max`; `oom` — сколько раз reclaim не помог
и аллокация в этом cgroup должна была упасть (OOM из-за своего лимита); `oom_kill` — сколько
процессов этого cgroup убил любой OOM killer, включая глобальный; `oom_group_kill` — сколько раз
убили группу целиком. `oom` растёт только от своего лимита, `oom_kill` — от любого OOM.

</details>

**A4.** Почему «контейнер занял 95% лимита памяти» — ещё не авария? Что такое working set
и как его посчитать?

<details><summary>Ответ</summary>

`memory.current` включает page cache файлов, который ядро вытеснит при нужде; 95%
может быть в основном кэшем. Working set = `memory.current − inactive_file` (из `memory.stat`) —
его используют kubelet и `kubectl top`. Для решения смотреть working set, `anon` и его рост.

</details>

**A5.** Что такое `shmem` в `memory.stat` и почему tmpfs и `emptyDir: medium: Memory` опасны для лимита?

<details><summary>Ответ</summary>

`shmem` — память tmpfs, `/dev/shm`, разделяемой памяти. Она считается в лимит cgroup
и не вытесняется как обычный кэш (без swap её некуда деть). `emptyDir: medium: Memory` — это
tmpfs: записанные туда файлы съедают лимит контейнера и могут привести к OOM; нужен `sizeLimit`
и учёт в `limits.memory`.

</details>

**A6.** ⭐ Как устроен `cpu.max`? Что значат `nr_periods`, `nr_throttled`, `throttled_usec`?
Как посчитать долю throttling?

<details><summary>Ответ</summary>

`cpu.max` = «квота период» в мкс: `50000 100000` — 50 мс CPU на каждые 100 мс для всех
потоков cgroup вместе; `max 100000` — без лимита. `nr_periods` — периоды, в которых были
runnable-задачи; `nr_throttled` — периоды, где квота кончилась и cgroup заморозили до конца
периода; `throttled_usec` — суммарное время заморозки. Доля = `nr_throttled / nr_periods`
(считать по приростам за интервал).

</details>

**A7.** ⭐ Почему контейнер тормозит при 30% среднего CPU? Объясни на периоде 100 мс.

<details><summary>Ответ</summary>

Квота считается на весь период и на все потоки. Если приложение на 8 потоках делает
всплеск, лимит 1 CPU (100 мс квоты) сгорает за 12,5 мс, и оставшиеся 87,5 мс cgroup заморожен:
запрос, пришедший в это окно, ждёт до следующего периода. Всплески (GC, JIT, пачка параллельных
запросов) короткие и редкие, поэтому средняя загрузка за минуту — 30%, а p99 вырос на десятки мс.

</details>

**A8.** Чем `cpu.weight` отличается от `cpu.max`? Когда weight вообще на что-то влияет?

<details><summary>Ответ</summary>

`cpu.max` — жёсткий потолок, работает всегда. `cpu.weight` — относительная доля при
конкуренции за CPU (1–10000, по умолчанию 100): если CPU свободен, cgroup с маленьким weight всё
равно получит сколько нужно. Weight влияет, только когда желающих больше, чем ядер.

</details>

**A9.** Почему `nproc` в контейнере с `--cpus=0.5` показывает все ядра хоста и чем это опасно?
Что с этим делают Go и JVM?

<details><summary>Ответ</summary>

Квота CFS не меняет CPU affinity: процесс может выполняться на любом ядре, просто
суммарно не больше квоты. `nproc` и `os.cpu_count()` смотрят на affinity/ядра хоста; меняет их
только `--cpuset-cpus`. Опасность — пулы потоков и GC-потоки по числу ядер хоста (64 потока при

</details>

**A10.** Что такое PSI? Чем `some` отличается от `full`? Где PSI используют?

<details><summary>Ответ</summary>

Pressure Stall Information — доля времени, когда задачи простаивали в ожидании CPU,
памяти или I/O (`/proc/pressure/*` и `*.pressure` в каждом cgroup). `some` — хотя бы одна задача
ждала; `full` — ждали все не-idle задачи одновременно (работа стоит). Используют: алерты
saturation, systemd-oomd (`ManagedOOMMemoryPressure=`), userspace OOM-демоны через триггеры
с `poll()`, kubelet отдаёт PSI-метрики на `/metrics/cadvisor` (GA в Kubernetes 1.36).

</details>

**A11.** Как Docker раскладывает `--memory`, `--memory-reservation`, `--cpus`, `--cpu-shares`,
`--pids-limit` по файлам cgroup?

<details><summary>Ответ</summary>

`--memory=256m` → `memory.max` 268435456 (и `memory.swap.max` столько же, если не задан
`--memory-swap`); `--memory-reservation=128m` → `memory.low`; `--cpus=0.5` → `cpu.max` `50000 100000`;
`--cpu-shares=512` → `cpu.weight` через конвертацию shares→weight (59 на свежем runc);
`--pids-limit=100` → `pids.max` 100; `--cpuset-cpus` → `cpuset.cpus`.

</details>

**A12.** ⭐ Как Kubernetes раскладывает requests и limits по cgroup? Что происходит с
`requests.memory`? Что такое `memory.oom.group` и какой `oom_score_adj` у QoS-классов?

<details><summary>Ответ</summary>

`limits.cpu` → `cpu.max` (квота = limit × 100 мс при периоде 100 мс); `requests.cpu` →
`cpu.weight` (millicores → shares → weight); `limits.memory` → `memory.max`; `requests.memory` по
умолчанию в cgroup не пишется — используется планировщиком и при eviction (`memory.min`/`memory.high`
ставит только alpha-фича MemoryQoS). На cgroup v2 с Kubernetes 1.28+ kubelet ставит
`memory.oom.group=1` — OOM убивает все процессы контейнера (опция kubelet `singleProcessOOMKill`
с 1.32 возвращает старое поведение). `oom_score_adj`: Guaranteed −997, BestEffort 1000,
Burstable 2…999 по доле request от памяти ноды.

</details>

**A13.** Как менялась конвертация `requests.cpu` → `cpu.weight` и почему это важно?

<details><summary>Ответ</summary>

Старая линейная формула KEP-2254 давала 1 CPU ≈ weight 39, 100m ≈ 4 — меньше дефолтных

</details>

**A14.** ⭐ Чем отличаются OOMKilled, node OOM и Evicted? Какими фактами доказывается каждый?

<details><summary>Ответ</summary>

OOMKilled — ядро убило процесс по лимиту контейнера: в `dmesg` `CONSTRAINT_MEMCG`
и `Memory cgroup out of memory`, в `memory.events` растут `oom` и `oom_kill`, `memory.peak` ≈
`memory.max`, в поде reason OOMKilled, 137. Node OOM — на ноде кончилась память: `CONSTRAINT_NONE`,
`Out of memory: Killed process`, событие `SystemOOM` на ноде, у контейнера растёт только
`oom_kill`, пик ниже лимита (в поде тоже может быть OOMKilled/137). Evicted — kubelet заранее
выселил под при `memory.available` ниже порога: в `dmesg` ничего, `status.reason: Evicted`,
событие Evicted с текстом о ресурсе.

</details>

**A15.** Чем `docker exec` отличается от `nsenter`? Почему `nsenter -t PID -p ps` без `-m`
показывает процессы хоста? Что даёт `kubectl debug --target`?

<details><summary>Ответ</summary>

`docker exec` запускает процесс внутри всех namespaces и cgroup контейнера, с его
seccomp/capabilities и только с бинарями образа, и требует живого рантайма. `nsenter` с хоста
входит в выбранные namespaces по PID: можно взять только сеть (`-n`) и пользоваться утилитами
хоста; процесс остаётся с правами root хоста и вне cgroup контейнера. `ps` читает `/proc`, а без
`-m` смонтирован хостовой `/proc` — отсюда процессы хоста. `kubectl debug --target=ctr` добавляет
ephemeral-контейнер в общий PID namespace с целевым: видны его процессы, ФС — через
`/proc/&lt;PID&gt;/root`, профиль general даёт `SYS_PTRACE` для strace/py-spy.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ kubectl exec api-6f9c -- cat /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.max
```text
<details><summary>Ответ</summary>

Контейнер 12 раз упёрся в свой лимит 512Mi, и каждый раз убивали весь контейнер
(`oom_group_kill` 12 — это `memory.oom.group=1`); пик = лимит. Это OOMKilled по своему лимиту.
Дальше: растёт ли `anon` со временем (утечка) или нагрузке просто нужно больше (профиль памяти,
heap-дамп); решать — чинить утечку или обоснованно поднимать limit.

</details>

```text:no-line-numbers
     low 0
```text
```text:no-line-numbers
     high 0
```text
```text:no-line-numbers
     max 1840
```text
```text:no-line-numbers
     oom 12
```text
```text:no-line-numbers
     oom_kill 12
```text
```text:no-line-numbers
     oom_group_kill 12
```text
```text:no-line-numbers
     536870912
```text
```text:no-line-numbers
     536870912
```text
```text:no-line-numbers
B2.  # под перезапустился: Reason OOMKilled, Exit Code 137; в новом контейнере
```text
<details><summary>Ответ</summary>

`CONSTRAINT_NONE` и `Out of memory: Killed process` — глобальный OOM на ноде, а не лимит
контейнера. Поднимать limit поду бесполезно. Смотреть ноду: сумма реального потребления против
RAM, overcommit по limits, поды без limits, процессы вне Kubernetes, `kube-reserved`/
`system-reserved`; `kubectl get events --field-selector reason=SystemOOM`.

</details>

```text:no-line-numbers
     # (прошлое событие на ноде — в dmesg):
```text
```text:no-line-numbers
     [..] oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=…,task=java,pid=88121,uid=1000
```text
```text:no-line-numbers
     [..] Out of memory: Killed process 88121 (java) total-vm:6123400kB, anon-rss:1480220kB, …
```text
```text:no-line-numbers
B3.  # за 100 минут, сервис на Go, limits.cpu: 2; график CPU usage — ~0,6 ядра
```text
<details><summary>Ответ</summary>

21000 / 60000 = 35% периодов с throttling, 9800 с заморозки за 100 минут (копится по
каждому CPU, поэтому для многопоточного бывает больше реального времени). Средние 0,6 ядра
скрывают всплески, которые упираются в 2 CPU. Доказательство есть; лечение — GOMAXPROCS по лимиту
(Go 1.25+ сам), поднять или убрать CPU limit, оставив requests.

</details>

```text:no-line-numbers
     nr_periods 60000
```text
```text:no-line-numbers
     nr_throttled 21000
```text
```text:no-line-numbers
     throttled_usec 9800000000
```text
```text:no-line-numbers
B4.  # «под медленный, наверное throttling»
```text
<details><summary>Ответ</summary>

Лимита нет (`max`), throttling 0 — дело не в квоте. Но `cpu.pressure` высокий: задачи
пода ~40% времени ждут CPU — нода перегружена, под проигрывает конкуренцию (маленький
`cpu.weight` от небольшого request или соседи). Смотреть загрузку ноды (`kubectl top node`,
`mpstat` на ноде), `cpu.weight` пода, поднять `requests.cpu` или развести соседей.

</details>

```text:no-line-numbers
     $ cat /sys/fs/cgroup/cpu.max
```text
```text:no-line-numbers
     max 100000
```text
```text:no-line-numbers
     $ grep throttled /sys/fs/cgroup/cpu.stat
```text
```text:no-line-numbers
     nr_throttled 0
```text
```text:no-line-numbers
     throttled_usec 0
```text
```text:no-line-numbers
     $ cat /sys/fs/cgroup/cpu.pressure
```text
```text:no-line-numbers
     some avg10=41.20 avg60=38.75 avg300=30.02 total=912345678
```text
```text:no-line-numbers
     full avg10=12.10 avg60=10.44 avg300=8.91 total=301234567
```text
```text:no-line-numbers
B5.  # «памяти 480Mi из 512Mi — скоро OOM!»
```text
<details><summary>Ответ</summary>

Паники нет: из 480Mi только ~90Mi — `anon`, остальное page cache, причём ~350Mi —
`inactive_file`, который вытесняется первым. Working set ≈ 480 − 350 = 130Mi. OOM не близко.

</details>

```text:no-line-numbers
     memory.current  503316480
```text
```text:no-line-numbers
     anon            94371840
```text
```text:no-line-numbers
     file            398458880
```text
```text:no-line-numbers
     inactive_file   367001600
```text
```text:no-line-numbers
B6.  # Java-сервис в контейнере --cpus=0.5 на 64-ядерном хосте
```text
<details><summary>Ответ</summary>

Квота 0,5 ядра, а JVM видит 64 ядра и строит пул из 64 воркеров (плюс GC-потоки) →
жёсткий throttling и переключения контекста. Задать `-XX:ActiveProcessorCount=1` (или
соответствующий лимиту), размер пула из конфига, проверить, что JVM действительно
container-aware; либо `--cpuset-cpus`, если нужно ограничить именно ядра.

</details>

```text:no-line-numbers
     $ docker exec app cat /sys/fs/cgroup/cpu.max
```text
```text:no-line-numbers
     50000 100000
```text
```text:no-line-numbers
     $ docker exec app nproc
```text
```text:no-line-numbers
     64
```text
```text:no-line-numbers
     # в конфиге: пул воркеров = число ядер
```text
```text:no-line-numbers
B7.  $ cat /proc/pressure/memory
```text
<details><summary>Ответ</summary>

Система под сильным давлением памяти: ~35–38% времени хотя бы одна задача ждёт
reclaim/swap-in, ~11–12% времени стоят все задачи. Это предтрэшинг: latency растёт, скоро OOM.
Найти потребителей (`systemd-cgtop`, `ps --sort=-rss`), проверить утечки, лимиты и своп;
systemd-oomd с порогом `ManagedOOMMemoryPressure` начал бы убивать здесь.

</details>

```text:no-line-numbers
     some avg10=38.12 avg60=35.40 avg300=28.90 total=8123456789
```text
```text:no-line-numbers
     full avg10=12.50 avg60=11.02 avg300=8.44 total=2912345678
```text
```text:no-line-numbers
B8.  $ sudo nsenter -t 4242 -p ps aux | wc -l
```text
<details><summary>Ответ</summary>

`-p` переключил только PID namespace, но `ps` читает `/proc`, а смонтирован хостовой
`/proc` (mount namespace не менялся). Нужно `nsenter -t 4242 -m -p ps aux` (если в образе есть
`ps`) или смотреть `/proc/4242/…` и `pgrep --ns 4242` снаружи.

</details>

```text:no-line-numbers
     312               # а в контейнере 3 процесса
```text
```text:no-line-numbers
B9.  resources:
```text
<details><summary>Ответ</summary>

Requests ≠ limits по памяти → QoS Burstable (для Guaranteed нужно равенство и по CPU,
и по памяти у всех контейнеров). `oom_score_adj` — от 2 до 999 по формуле от доли request
(256Mi) от памяти ноды: на ноде 16 ГБ ≈ 1000 − 1000×256/16384 ≈ 984. cgroup: `cpu.max`
`100000 100000`, `cpu.weight` из request 1 CPU (≈100 или 39 в зависимости от формулы),
`memory.max` 2Gi, `requests.memory` в cgroup не пишется. Разрыв 256Mi/2Gi — риск: планировщик
считает 256Mi, а контейнер может съесть 2Gi и спровоцировать node OOM.

</details>

```text:no-line-numbers
       requests: { cpu: "1", memory: 256Mi }
```text
```text:no-line-numbers
       limits:   { cpu: "1", memory: 2Gi }
```text
```text:no-line-numbers
B10.  $ kubectl describe pod report-7c5d | grep -A4 'Last State'
```text
<details><summary>Ответ</summary>

OOMKilled при пике ~1,1Gi из 4Gi — лимит не достигнут, а на ноде событие `SystemOOM`:
контейнер убит глобальным OOM killer как самый «жирный» кандидат с учётом `oom_score_adj`.
Причина — нехватка памяти на ноде, лечить ноду: requests ≈ реальному потреблению, меньше
overcommit, резервы kubelet.

</details>

```text:no-line-numbers
         Last State:     Terminated
```text
```text:no-line-numbers
           Reason:       OOMKilled
```text
```text:no-line-numbers
           Exit Code:    137
```text
```text:no-line-numbers
     # limits.memory: 4Gi, по метрикам пик контейнера ~1,1Gi;
```text
```text:no-line-numbers
     $ kubectl get events -A --field-selector reason=SystemOOM
```text
```text:no-line-numbers
     default   2m   Warning   SystemOOM   node/worker-3   System OOM encountered, victim process: java, pid: 88121
```text
```text:no-line-numbers
B11.  Warning  Evicted  pod/cache-5d8f  The node was low on resource: memory. Threshold quantity: 100Mi,
```text
<details><summary>Ответ</summary>

Kubelet выселил под: на ноде осталось 91Mi при пороге 100Mi; под использовал 1,2Gi при
request 256Mi — сильнее всех превысил request, поэтому выбран первым (Burstable). Поднять
`requests.memory` до реального потребления (или limit = request), проверить утечку, дать ноде
резерв памяти.

</details>

```text:no-line-numbers
     available: 91Mi. Container cache was using 1.2Gi, request is 256Mi, has larger consumption of memory.
```text
```text:no-line-numbers
B12.  $ cat /sys/fs/cgroup/pids.events /sys/fs/cgroup/pids.max
```text
<details><summary>Ответ</summary>

Контейнер 350 раз упёрся в `pids.max` 512 (потоки считаются как задачи): новые потоки
и процессы не создаются → `can't start new thread` / `fork: Resource temporarily unavailable`.
Причина — утечка потоков или неограниченный пул. Чинить в приложении; поднимать `pids.max`
(`--pids-limit`, `podPidsLimit` kubelet) — только осознанно.

</details>

```text:no-line-numbers
     max 350
```text
```text:no-line-numbers
     512
```text
```text:no-line-numbers
     # в логе приложения: RuntimeError: can't start new thread
```text
---

### Блок C. Практика


### C1. 🔑 Где живёт процесс
**1.** `cat /proc/self/cgroup`, `systemctl show ssh -p ControlGroup`, `systemd-cgls --no-pager | head -40`.

<details><summary>Ответ</summary>

SSH-шелл — в `user.slice/user-1000.slice/session-N.scope`, `ssh.service` — в
`system.slice/ssh.service`. `systemd-cgtop` показывает `system.slice`/`user.slice` с памятью и CPU.
Для контейнера `/proc/PID/cgroup` → `0::/system.slice/docker-&lt;id&gt;.scope`; файлы
`/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/memory.current` снаружи и
`/sys/fs/cgroup/memory.current` изнутри совпадают — cgroup namespace показывает контейнеру его cgroup
как корень.

</details>

**2.** `systemd-cgtop` на 30 секунд: какой slice ест больше всего памяти?

<details><summary>Ответ</summary>

До 150 MiB строки идут раз в 0,5 с; после — печать заметно замедляется (торможение
`memory.high`), в `memory.events` растёт `high`, `memory.pressure` `some`/`full` поднимается.
У ~200 MiB растут `max`, затем `oom` и `oom_kill` — процесс убит, в `dmesg`
`constraint=CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/memtest.scope`.

</details>

**3.** Запусти `docker run -d --name c1 nginx:alpine`, найди его cgroup через
   `/proc/$(docker inspect -f '&#123;&#123;.State.Pid&#125;&#125;' c1)/cgroup` и прочитай оттуда `memory.current`
   и `cpu.max`. Сравни с тем, что видно через `docker exec c1 cat /sys/fs/cgroup/…`.

<details><summary>Ответ</summary>

За 10 с: `nr_periods` +~100, `nr_throttled` +~100 (≈100%), `throttled_usec` +~5 000 000,
`usage_usec` +~5 000 000 — ровно квота 0,5 ядра. После `--cpus=1.5` однопоточный цикл может
съесть максимум 1 ядро < 1,5 квоты, квота не кончается — `nr_throttled` не растёт, `usage_usec`
+~10 000 000 за 10 с. `docker stats`: ~50% → ~100%.

</details>

### C2. 🔑 memory.high против memory.max
```text:no-line-numbers
sudo systemd-run --scope --unit=memtest -p MemoryHigh=150M -p MemoryMax=200M \
```text
```text:no-line-numbers
  python3 -c "import time; x=[]; [(x.append(b'x' * (10 << 20)), print(len(x)*10, 'MiB', flush=True), time.sleep(0.5)) for _ in range(40)]"
```text
**1.** В соседнем окне: `watch -n1 'cat /sys/fs/cgroup/system.slice/memtest.scope/memory.events /sys/fs/cgroup/system.slice/memtest.scope/memory.pressure'`.

<details><summary>Ответ</summary>

SSH-шелл — в `user.slice/user-1000.slice/session-N.scope`, `ssh.service` — в
`system.slice/ssh.service`. `systemd-cgtop` показывает `system.slice`/`user.slice` с памятью и CPU.
Для контейнера `/proc/PID/cgroup` → `0::/system.slice/docker-&lt;id&gt;.scope`; файлы
`/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/memory.current` снаружи и
`/sys/fs/cgroup/memory.current` изнутри совпадают — cgroup namespace показывает контейнеру его cgroup
как корень.

</details>

**2.** Что происходит со скоростью печати после 150 MiB? Какие счётчики растут и когда процесс убит?

<details><summary>Ответ</summary>

До 150 MiB строки идут раз в 0,5 с; после — печать заметно замедляется (торможение
`memory.high`), в `memory.events` растёт `high`, `memory.pressure` `some`/`full` поднимается.
У ~200 MiB растут `max`, затем `oom` и `oom_kill` — процесс убит, в `dmesg`
`constraint=CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/memtest.scope`.

</details>

**3.** Найди запись в `sudo dmesg -T` и определи `constraint`.

<details><summary>Ответ</summary>

За 10 с: `nr_periods` +~100, `nr_throttled` +~100 (≈100%), `throttled_usec` +~5 000 000,
`usage_usec` +~5 000 000 — ровно квота 0,5 ядра. После `--cpus=1.5` однопоточный цикл может
съесть максимум 1 ядро < 1,5 квоты, квота не кончается — `nr_throttled` не растёт, `usage_usec`
+~10 000 000 за 10 с. `docker stats`: ~50% → ~100%.

</details>

### C3. 🔑 Throttling своими руками
```text:no-line-numbers
docker run -d --name thr --cpus=0.5 alpine sh -c 'while :; do :; done'
```text
```text:no-line-numbers
docker exec thr cat /sys/fs/cgroup/cpu.stat; sleep 10; docker exec thr cat /sys/fs/cgroup/cpu.stat
```text
**1.** Посчитай за 10 секунд прирост `nr_periods`, `nr_throttled`, `throttled_usec`, `usage_usec`
   и долю throttling. Сходится ли `usage_usec` с квотой?

<details><summary>Ответ</summary>

SSH-шелл — в `user.slice/user-1000.slice/session-N.scope`, `ssh.service` — в
`system.slice/ssh.service`. `systemd-cgtop` показывает `system.slice`/`user.slice` с памятью и CPU.
Для контейнера `/proc/PID/cgroup` → `0::/system.slice/docker-&lt;id&gt;.scope`; файлы
`/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/memory.current` снаружи и
`/sys/fs/cgroup/memory.current` изнутри совпадают — cgroup namespace показывает контейнеру его cgroup
как корень.

</details>

**2.** `docker update --cpus=1.5 thr`, повтори замер. Почему `nr_throttled` перестал расти?

<details><summary>Ответ</summary>

До 150 MiB строки идут раз в 0,5 с; после — печать заметно замедляется (торможение
`memory.high`), в `memory.events` растёт `high`, `memory.pressure` `some`/`full` поднимается.
У ~200 MiB растут `max`, затем `oom` и `oom_kill` — процесс убит, в `dmesg`
`constraint=CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/memtest.scope`.

</details>

**3.** `docker stats --no-stream thr` в обоих случаях. Уборка: `docker rm -f thr`.

<details><summary>Ответ</summary>

За 10 с: `nr_periods` +~100, `nr_throttled` +~100 (≈100%), `throttled_usec` +~5 000 000,
`usage_usec` +~5 000 000 — ровно квота 0,5 ядра. После `--cpus=1.5` однопоточный цикл может
съесть максимум 1 ядро < 1,5 квоты, квота не кончается — `nr_throttled` не растёт, `usage_usec`
+~10 000 000 за 10 с. `docker stats`: ~50% → ~100%.

</details>

### C4. PSI на трёх уровнях
**1.** Система: `stress-ng --cpu 4 --timeout 60s &` на 2 vCPU, затем `cat /proc/pressure/cpu`.

<details><summary>Ответ</summary>

SSH-шелл — в `user.slice/user-1000.slice/session-N.scope`, `ssh.service` — в
`system.slice/ssh.service`. `systemd-cgtop` показывает `system.slice`/`user.slice` с памятью и CPU.
Для контейнера `/proc/PID/cgroup` → `0::/system.slice/docker-&lt;id&gt;.scope`; файлы
`/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/memory.current` снаружи и
`/sys/fs/cgroup/memory.current` изнутри совпадают — cgroup namespace показывает контейнеру его cgroup
как корень.

</details>

**2.** Контейнер: повтори C3 с `--cpus=0.5` и прочитай `cpu.pressure` контейнера.

<details><summary>Ответ</summary>

До 150 MiB строки идут раз в 0,5 с; после — печать заметно замедляется (торможение
`memory.high`), в `memory.events` растёт `high`, `memory.pressure` `some`/`full` поднимается.
У ~200 MiB растут `max`, затем `oom` и `oom_kill` — процесс убит, в `dmesg`
`constraint=CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/memtest.scope`.

</details>

**3.** Память: во время C2 смотри `memory.pressure` scope. Какие значения `some`/`full` в каждом случае
   и почему у системной `cpu` строка `full` нулевая?

<details><summary>Ответ</summary>

За 10 с: `nr_periods` +~100, `nr_throttled` +~100 (≈100%), `throttled_usec` +~5 000 000,
`usage_usec` +~5 000 000 — ровно квота 0,5 ядра. После `--cpus=1.5` однопоточный цикл может
съесть максимум 1 ядро < 1,5 квоты, квота не кончается — `nr_throttled` не растёт, `usage_usec`
+~10 000 000 за 10 с. `docker stats`: ~50% → ~100%.

</details>

### C5. 🔑 Флаги Docker → файлы cgroup
```text:no-line-numbers
docker run -d --name lim --memory=256m --memory-reservation=128m --cpus=0.5 \
```text
```text:no-line-numbers
  --cpu-shares=512 --pids-limit=100 nginx:alpine
```text
```text:no-line-numbers
for f in memory.max memory.swap.max memory.low cpu.max cpu.weight pids.max; do
```text
```text:no-line-numbers
  printf '%-16s %s\n' $f "$(docker exec lim cat /sys/fs/cgroup/$f)"; done
```text
```text:no-line-numbers
docker exec lim nproc
```text
```text:no-line-numbers
docker run --rm --cpuset-cpus=0 alpine nproc
```text
Заполни таблицу «флаг → файл → значение» и объясни, почему `nproc` меняется только от `--cpuset-cpus`.

### C6. 🔑 OOMKilled в kind и memory.oom.group
```text:no-line-numbers
# ~/perf/t06/oom-demo.yaml
```text
```text:no-line-numbers
apiVersion: v1
```text
```text:no-line-numbers
kind: Pod
```text
```text:no-line-numbers
metadata: { name: oom-demo }
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  restartPolicy: Never
```text
```text:no-line-numbers
  containers:
```text
```text:no-line-numbers
    - name: app
```text
```text:no-line-numbers
      image: python:3.12-alpine
```text
```text:no-line-numbers
      command: ["python", "-c", "import time; x=[]; [(x.append(b'x' * (10 << 20)), time.sleep(0.2)) for _ in range(30)]; time.sleep(3600)"]
```text
```text:no-line-numbers
      resources:
```text
```text:no-line-numbers
        requests: { memory: 32Mi, cpu: 100m }
```text
```text:no-line-numbers
        limits:   { memory: 64Mi, cpu: 500m }
```text
**1.** До применения запусти рядом долгий под и прочитай у него `memory.oom.group`:
   `kubectl run probe --image=python:3.12-alpine --restart=Never -- sleep 3600`,
   `kubectl exec probe -- cat /sys/fs/cgroup/memory.oom.group`.

<details><summary>Ответ</summary>

SSH-шелл — в `user.slice/user-1000.slice/session-N.scope`, `ssh.service` — в
`system.slice/ssh.service`. `systemd-cgtop` показывает `system.slice`/`user.slice` с памятью и CPU.
Для контейнера `/proc/PID/cgroup` → `0::/system.slice/docker-&lt;id&gt;.scope`; файлы
`/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/memory.current` снаружи и
`/sys/fs/cgroup/memory.current` изнутри совпадают — cgroup namespace показывает контейнеру его cgroup
как корень.

</details>

**2.** `kubectl apply -f oom-demo.yaml`; через полминуты `kubectl get pod oom-demo -o jsonpath='{.status.containerStatuses[0].state.terminated}'`.

<details><summary>Ответ</summary>

До 150 MiB строки идут раз в 0,5 с; после — печать заметно замедляется (торможение
`memory.high`), в `memory.events` растёт `high`, `memory.pressure` `some`/`full` поднимается.
У ~200 MiB растут `max`, затем `oom` и `oom_kill` — процесс убит, в `dmesg`
`constraint=CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/memtest.scope`.

</details>

**3.** На VM: `sudo dmesg -T | grep -E 'CONSTRAINT_MEMCG|Memory cgroup out of memory' | tail -2` — найди путь
   cgroup пода в `oom_memcg=`.

<details><summary>Ответ</summary>

За 10 с: `nr_periods` +~100, `nr_throttled` +~100 (≈100%), `throttled_usec` +~5 000 000,
`usage_usec` +~5 000 000 — ровно квота 0,5 ядра. После `--cpus=1.5` однопоточный цикл может
съесть максимум 1 ядро < 1,5 квоты, квота не кончается — `nr_throttled` не растёт, `usage_usec`
+~10 000 000 за 10 с. `docker stats`: ~50% → ~100%.

</details>

### C7. 🔑 Отладка контейнера без shell
```text:no-line-numbers
docker run -d --name nosh registry.k8s.io/pause:3.10       # внутри только /pause, shell нет
```text
```text:no-line-numbers
docker exec nosh sh                                         # ошибка: исполняемого файла нет
```text
```text:no-line-numbers
PID=$(docker inspect -f '&#123;&#123;.State.Pid&#125;&#125;' nosh)
```text
```text:no-line-numbers
sudo nsenter -t $PID -n ip -br addr; sudo nsenter -t $PID -n ss -tanp
```text
```text:no-line-numbers
docker run --rm -it --pid=container:nosh --network=container:nosh nicolaka/netshoot ps aux
```text
Затем в kind: `kubectl run nosh --image=registry.k8s.io/pause:3.10` и
`kubectl debug -it nosh --image=busybox --target=nosh -- sh` — посмотри `ps` и `ls /proc/1/root`.

### C8. Отладка ноды kind
**1.** `kubectl debug node/perf-control-plane -it --image=ubuntu --profile=sysadmin`.

<details><summary>Ответ</summary>

SSH-шелл — в `user.slice/user-1000.slice/session-N.scope`, `ssh.service` — в
`system.slice/ssh.service`. `systemd-cgtop` показывает `system.slice`/`user.slice` с памятью и CPU.
Для контейнера `/proc/PID/cgroup` → `0::/system.slice/docker-&lt;id&gt;.scope`; файлы
`/sys/fs/cgroup/system.slice/docker-&lt;id&gt;.scope/memory.current` снаружи и
`/sys/fs/cgroup/memory.current` изнутри совпадают — cgroup namespace показывает контейнеру его cgroup
как корень.

</details>

**2.** Внутри: `chroot /host`, затем `crictl ps`, `crictl stats`, `cat /proc/pressure/memory`.

<details><summary>Ответ</summary>

До 150 MiB строки идут раз в 0,5 с; после — печать заметно замедляется (торможение
`memory.high`), в `memory.events` растёт `high`, `memory.pressure` `some`/`full` поднимается.
У ~200 MiB растут `max`, затем `oom` и `oom_kill` — процесс убит, в `dmesg`
`constraint=CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/memtest.scope`.

</details>

**3.** После выхода найди и удали под `node-debugger-…`.

<details><summary>Ответ</summary>

За 10 с: `nr_periods` +~100, `nr_throttled` +~100 (≈100%), `throttled_usec` +~5 000 000,
`usage_usec` +~5 000 000 — ровно квота 0,5 ядра. После `--cpus=1.5` однопоточный цикл может
съесть максимум 1 ядро < 1,5 квоты, квота не кончается — `nr_throttled` не растёт, `usage_usec`
+~10 000 000 за 10 с. `docker stats`: ~50% → ~100%.

</details>

### C9. Какая у тебя формула cpu.weight
Создай под с `requests.cpu: 100m` (без лимитов) и прочитай `cpu.weight` изнутри
(`kubectl exec … -- cat /sys/fs/cgroup/cpu.weight`). По таблице из конспекта определи,
старая (4) или новая (17) конвертация у runtime твоего kind. Сверь с
`docker exec perf-control-plane runc --version` (или `crun --version`).

---

### Блок D. Инциденты


**D1.** Java-сервис в k8s, `limits.cpu: 2`. Раз в минуту p99 подскакивает до 800 мс, в это же
время в логах GC-паузы. График CPU usage — в среднем 0,6 ядра. Что происходит и что делать?

<details><summary>Ответ</summary>

GC-всплеск на многих потоках за миллисекунды выедает квоту 2 CPU, и под замораживается
до конца периода — классический throttling, невидимый в среднем. Доказать: `cpu.stat` (прирост
`nr_throttled` в минуты всплесков), метрика `container_cpu_cfs_throttled_periods_total`. Лечение:
поднять/убрать CPU limit (оставить requests), ограничить GC-потоки
(`-XX:ParallelGCThreads`, `-XX:ActiveProcessorCount`), настроить GC на меньшие паузы.

</details>

**D2.** После каждого деплоя под 5 минут подряд получает OOMKilled, потом стабилен.
`limits.memory: 1Gi`, JVM запущена с `-Xmx900m`.

<details><summary>Ответ</summary>

Heap 900m + metaspace, code cache, потоки, direct buffers, JIT при прогреве превышают

</details>

**D3.** На одной ноде одновременно OOMKilled несколько несвязанных подов. У их контейнеров
`oom` в `memory.events` = 0, а на ноде есть событие `SystemOOM`.

<details><summary>Ответ</summary>

Это node OOM: `oom` у контейнеров 0, растёт только `oom_kill`, есть `SystemOOM` —
на ноде кончилась память, ядро убивало самых «жирных» с учётом `oom_score_adj`. Искать, кто
съел ноду: поды с limits ≫ requests, BestEffort, процессы вне k8s; выравнивать requests
с реальностью, резервы `kube-reserved`/`system-reserved`, пороги eviction.

</details>

**D4.** Под без requests и limits регулярно получает Evicted на загруженной ноде.

<details><summary>Ответ</summary>

BestEffort-под выселяется первым при нехватке памяти на ноде. Задать requests (и limits)
по реальному потреблению — под станет Burstable/Guaranteed, а планировщик перестанет класть его
на ноды без места.

</details>

**D5.** Графики памяти контейнера неделями на 98% лимита, OOM ни разу не было.
Команда хочет удвоить лимит «на всякий случай».

<details><summary>Ответ</summary>

Скорее всего, это page cache: смотреть `memory.stat` (`anon` против `file`,
`inactive_file`) и working set. Если `anon` стабилен, OOM не было, `memory.events` `oom` = 0 —
лимит в порядке, удвоение лишь отнимет память у ноды. Решать по working set, `memory.peak`
и PSI памяти контейнера.

</details>

**D6.** Distroless-под «не видит базу». Shell и curl в образе нет. Как проверить DNS и TCP до базы?

<details><summary>Ответ</summary>

`kubectl debug -it pod --image=nicolaka/netshoot --target=app` → внутри `dig db.ns.svc`,
`cat /etc/resolv.conf`, `nc -zv db 5432`, `ss -tanp`. Или с ноды: PID через `crictl inspect`,
`nsenter -t PID -n` + утилиты хоста (`ss`, `tcpdump port 53 or port 5432`), DNS проверять,
передав резолверу адрес CoreDNS из resolv.conf контейнера.

</details>

**D7.** После переезда на ноды с cgroup v2 (Kubernetes ≥ 1.28) контейнер с супервизором и
несколькими воркерами стал перезапускаться целиком, хотя раньше при OOM супервизор просто
поднимал одного воркера.

<details><summary>Ответ</summary>

В cgroup v2 с Kubernetes 1.28+ kubelet ставит `memory.oom.group=1`, и OOM убивает все
процессы контейнера, а не одного воркера. Варианты: kubelet `singleProcessOOMKill: true`
(1.32+) для узлов с такими нагрузками; лучше — разнести воркеры по контейнерам/подам
или ограничить память воркеров внутри (лимиты рантайма).

</details>

**D8.** Ночной batch-сервис на обычной VM (systemd, без Docker) при запуске «душит» всё остальное
по CPU и диску. Как ограничить его, не переписывая?

<details><summary>Ответ</summary>

Через systemd-ресурсы юнита: `systemctl set-property batch.service CPUQuota=50%
CPUWeight=20 IOWeight=10 MemoryHigh=2G` или в юните `Nice=19`, `IOSchedulingClass=idle`,
`CPUQuota=`, `IOReadBandwidthMax=`/`IOWriteBandwidthMax=`. Разовый запуск —
`systemd-run -p CPUQuota=50% -p IOWeight=10 …`. Это те же cgroups v2, без Docker.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое cgroups и чем v2 отличается от v1?

<details><summary>Ответ</summary>

Механизм ядра, который группирует процессы и ограничивает/учитывает ресурсы: CPU, память,
   I/O, число процессов. v2 — одна иерархия, процесс в одном cgroup, единый интерфейс файлов,
   PSI в каждом cgroup, `memory.high`, корректный учёт writeback-I/O; v1 — отдельное дерево на
   каждый контроллер и разнобой интерфейсов.

</details>

**2.** Как Kubernetes реализует requests и limits на уровне ядра?

<details><summary>Ответ</summary>

kubelet и runc пишут в cgroup контейнера: `limits.cpu` → `cpu.max` (квота на 100 мс),
   `requests.cpu` → `cpu.weight`, `limits.memory` → `memory.max`; `requests.memory` — только для
   планировщика и eviction. QoS задаёт `oom_score_adj`, на v2 — `memory.oom.group=1`.

</details>

**3.** Почему CPU limits могут вредить и как это доказать?

<details><summary>Ответ</summary>

Квота считается на период 100 мс для всех потоков: многопоточные всплески выедают её за
   миллисекунды, и контейнер замораживается — p99 растёт при низком среднем CPU. Доказательство —
   рост `nr_throttled/nr_periods` в `cpu.stat` или `container_cpu_cfs_throttled_periods_total`.
   Для latency-сервисов CPU limit часто убирают, оставляя requests.

</details>

**4.** Под получил OOMKilled. Как расследуешь?

<details><summary>Ответ</summary>

`lastState.terminated` (reason, exitCode 137), `memory.events` (`oom` против `oom_kill`),
   `memory.peak`, `dmesg` на ноде (`CONSTRAINT_MEMCG` или `CONSTRAINT_NONE`), события `SystemOOM`.
   Затем — утечка (рост `anon`) или недостаточный лимит (профиль памяти), либо проблема ноды.

</details>

**5.** Чем OOMKilled отличается от Evicted?

<details><summary>Ответ</summary>

OOMKilled — ядро убило процесс (по лимиту контейнера или при OOM ноды), контейнер
   перезапускается в том же поде. Evicted — kubelet заранее выселил под целиком из-за нехватки
   ресурса на ноде (память, диск), под пересоздаётся контроллером на другой ноде.

</details>

**6.** Что такое PSI и зачем она нужна?

<details><summary>Ответ</summary>

Pressure Stall Information: доля времени, когда задачи ждали CPU, память или I/O (`some` —
   хоть одна, `full` — все). Это прямая метрика saturation для системы и каждого cgroup;
   раньше OOM и лучше загрузки показывает, что ресурса не хватает; на ней работают systemd-oomd
   и алерты.

</details>

**7.** Как отладить контейнер, в образе которого нет shell?

<details><summary>Ответ</summary>

`nsenter -t PID -n` с хоста и утилиты хоста; отладочный контейнер-сосед
   (`--pid=container:`, `--network=container:`); в Kubernetes — `kubectl debug --target` с
   ephemeral-контейнером или `--copy-to`, для ноды — `kubectl debug node/… --profile=sysadmin`
   и `crictl` на ноде. ФС контейнера — через `/proc/PID/root`.

</details>

**8.** Что делает `memory.high` и чем он отличается от `memory.max`?

<details><summary>Ответ</summary>

`memory.high` — мягкий лимит: при превышении аллокации тормозятся и идёт принудительный
   reclaim, процесс живёт, но медленнее. `memory.max` — жёсткий: если reclaim не помог, OOM kill
   в cgroup. `high` ставят чуть ниже `max`, чтобы получить торможение и сигнал до убийства.

</details>

**9.** Почему приложение в контейнере может видеть все ядра хоста и чем это грозит?

<details><summary>Ответ</summary>

CPU-квота не меняет affinity, а `nproc`/`os.cpu_count()` видят ядра хоста; рантайм или
   приложение создаёт пулы и GC-потоки по числу ядер хоста → throttling, переключения контекста,
   память на лишние потоки. Лечится параметрами рантайма (Go 1.25+ сам, JVM container support,
   `ActiveProcessorCount`) или `--cpuset-cpus`.

</details>

**10.** Чем `docker exec` отличается от `nsenter`?

<details><summary>Ответ</summary>

`docker exec` — процесс внутри всех namespaces и cgroup контейнера, с его ограничениями
    безопасности и бинарями образа, нужен живой рантайм. `nsenter` — выборочный вход в
    namespaces по PID с хоста: можно войти только в сеть и пользоваться утилитами хоста, работает
    при зависшем рантайме, но с полными правами root.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Нахожу cgroup любого процесса через `/proc/PID/cgroup` и читаю его файлы
- [ ] Объясняю `memory.max`/`high`/`low`/`min` и воспроизвёл `high` против `max` через systemd-run
- [ ] ⭐ По `memory.events` отличаю «свой лимит» (`oom`) от «убит OOM ноды» (`oom_kill` без `oom`)
- [ ] Считаю working set и не паникую от page cache в лимите
- [ ] ⭐ Доказываю throttling через `cpu.stat` и объясняю «тормозит при 30% CPU»
- [ ] Читаю PSI системы и cgroup, знаю смысл `some`/`full`
- [ ] Раскладываю флаги Docker и requests/limits Kubernetes по файлам cgroup
- [ ] Знаю про `memory.oom.group=1` в k8s 1.28+ и `singleProcessOOMKill`
- [ ] ⭐ Отличаю OOMKilled, node OOM и Evicted по фактам
- [ ] Отлаживаю контейнер без shell: `nsenter -n`, `--pid=container:`, `kubectl debug --target`
- [ ] Отлаживаю ноду через `kubectl debug node/… --profile=sysadmin` и убираю за собой под
