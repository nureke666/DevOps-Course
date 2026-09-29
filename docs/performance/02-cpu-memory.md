---
title: "02. CPU и память: perf, flame graphs, OOM killer"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 02. Опирается на"
---

# 02. CPU и память: perf, flame graphs, OOM killer

> Блок → Deep Linux Troubleshooting & Performance → тема 02. Опирается на
> [01_methodology.md](/performance/01-methodology) (USE и «60 секунд»),
> [../Linux/14_process_utilization.md](/linux/14-process-utilization) (top, free, vmstat)
> и [../Linux/07_processes.md](/linux/07-processes) (RSS/VSZ, /proc).
>
> **После темы ты умеешь:** разложить CPU-время на user/sys/softirq/steal и понять, что
> каждое значит; найти горячую функцию через `perf` и построить flame graph; отличить
> «кэш» от «занятой» памяти; посчитать реальную память процесса (RSS/PSS/USS); поймать
> утечку по росту RSS; прочитать OOM-отчёт в `dmesg` и объяснить, почему убили именно его.

---

## 🗺️ Карта темы

```text
                  ┌──────────── CPU ────────────┐          ┌──────────── ПАМЯТЬ ───────────┐
 USE (тема 01)    │ U: us/sy/si/st по ядрам      │          │ U: available, RSS/PSS          │
      │           │ S: run queue, nvcswch, PSI   │          │ S: si/so, majflt, direct reclaim│
      ▼           │ E: throttling (частота/cgroup)│          │ E: OOM kill, ENOMEM            │
 какой ресурс? ──►└──────────────┬──────────────┘          └───────────────┬────────────────┘
                                 ▼                                         ▼
                 кто? pidstat -u -w / top        кто? pidstat -r, smem -s pss, ps --sort=-rss
                                 ▼                                         ▼
               где в коде? perf top / record     растёт? pidstat -r -p PID 60, pmap -x
                                 ▼                                         ▼
                 flame graph → функция        OOM? journalctl -k: кто вызвал, кого убили, почему
```text
---

## 1. Куда уходит CPU-время

Базовые колонки `top`/`vmstat` разобраны в [../Linux/14_process_utilization.md](/linux/14-process-utilization).
Здесь — что делать, когда одна из них высокая.

| Колонка (`mpstat`) | Что это на самом деле | Высокая → куда смотреть |
|--------------------|------------------------|--------------------------|
| `%usr` | Код приложений в user space | `pidstat -u 1` → `perf top -p PID` → flame graph |
| `%sys` | Ядро по просьбе процессов: syscalls, page faults, копирование | `pidstat -u` (колонка `%system`), `strace -c` (тема 05), `perf top` с `[k]`-символами |
| `%iowait` | **Простой** CPU, пока есть незавершённый I/O. Это не работа CPU | Диск: [03_disk_io.md](/performance/03-disk-io). iowait может упасть, просто когда CPU стал занят другим |
| `%irq` / `%soft` | Аппаратные и программные прерывания: сеть, блочные устройства, таймеры | `mpstat -I SCPU 1`, `/proc/softirqs`, процесс `ksoftirqd/N` в top |
| `%steal` | Гипервизор отдал «твоё» время другой VM | Раздел 5 |
| `%guest` | Время, когда этот хост крутит виртуалки (KVM) | Нормально на гипервизоре |
| `%nice` | `%usr` процессов с nice > 0 | Бэкапы/батчи с `nice` — ок |

```bash
mpstat -P ALL 1          # ⭐ всегда по ядрам: среднее 12% может быть одним ядром в 100%
mpstat -I SCPU 1         # softirq по типам и ядрам: NET_RX, TIMER, BLOCK, SCHED…
watch -d -n1 cat /proc/softirqs      # какие счётчики быстро растут
```text
```text
# пример вывода: mpstat -P ALL 1 (VM 2 vCPU), однопоточный процесс в цикле
CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle
all   50.25    0.00    0.50    0.00    0.00    0.00    0.00    0.00    0.00   49.25
  0    0.99    0.00    0.99    0.00    0.00    0.00    0.00    0.00    0.00   98.02
  1  100.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00
```text
Среднее «50%» выглядит нормально, но ядро 1 в полке: однопоточный процесс упёрся в
потолок и **больше CPU не получит никогда**. Такой сервис масштабируют процессами, а не ядрами.

> ⚠️ Одно ядро с `%soft` 100% при остальных свободных — классика сетевого сервера:
> все прерывания NIC идут на одно ядро. Лечится RSS/RPS и `irqbalance`, а не «добавить CPU».

---

## 2. Run queue и переключения контекста

**Run queue** — задачи в состоянии R, ждущие ядро. Колонка `r` в `vmstat` и `runq-sz`
в `sar -q`. Стабильно `r` > числа ядер = CPU saturation (тема 01).

**Context switch** бывает двух видов — и это разные диагнозы:

| | Voluntary (`cswch/s`) | Involuntary (`nvcswch/s`) |
|---|------------------------|----------------------------|
| Когда | Процесс сам уснул: ждёт I/O, lock, сеть, sleep | Ядро вытеснило: кончился квант, пришла задача важнее |
| Много → | Процесс много ждёт: блокировки, мелкий I/O, частые syscalls | **Процессу не хватает CPU**: конкуренция за ядра, CFS-квота (тема 06) |

```bash
pidstat -w 1                        # по процессам
pidstat -wt -p 4312 1               # по потокам конкретного процесса
grep ctxt_switches /proc/4312/status
```text
```text
# пример вывода: pidstat -w -p 4312 1
UID       PID   cswch/s nvcswch/s  Command
1000     4312      2.00    812.00  python3      ← вытесняют ~800 раз/с: CPU не хватает
```text
Сколько задачи **ждут** в очереди — видно только гистограммой задержки run queue:
`sudo runqlat-bpfcc 10 1` ([07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace)). Интегрально то же
показывает PSI: `/proc/pressure/cpu` (тема 06).

---

## 3. perf: где именно тратится CPU

`perf` читает счётчики процессора (PMU) и сэмплирует стеки: «в какой функции был
процессор 99 раз в секунду». Работает для любого языка, без перезапуска процесса.

```bash
sudo perf list | head              # доступные события (в VM без vPMU — только software)
sudo perf stat -p 4312 -- sleep 10 # счётчики за 10 секунд
sudo perf top                      # ⭐ «top по функциям» на всей системе
sudo perf top -p 4312 -g           # один процесс, со стеками
sudo perf record -F 99 -g -p 4312 -- sleep 30   # ⭐ запись профиля: 99 Гц, 30 с, со стеками
sudo perf record -F 99 -a -g -- sleep 30        # вся система
sudo perf report --stdio --no-children | head -40
```text
> На Ubuntu `kernel.perf_event_paranoid = 4` — без `sudo` perf не работает вовсе.
> 99 Гц, а не 100 — чтобы не совпасть по фазе с таймерами, тикающими 100 раз в секунду.

```text
# пример вывода: sudo perf stat -p 4312 -- sleep 10 (VM с host-passthrough)
 Performance counter stats for process id '4312':

          9,982.41 msec task-clock          #    0.998 CPUs utilized
                37      context-switches    #    3.707 /sec
                 2      cpu-migrations      #    0.200 /sec
                 0      page-faults         #    0.000 /sec
    34,112,905,221      cycles              #    3.417 GHz
    98,443,120,774      instructions        #    2.89  insn per cycle
```text
`0.998 CPUs utilized` — процесс съедает ровно одно ядро. **IPC** (insn per cycle) ≈ 2–3 —
процессор реально считает; IPC < 1 — чаще ждёт память (cache misses), и оптимизировать
нужно доступ к данным, а не «алгоритм».

```text
# пример вывода: sudo perf top (VM, на фоне openssl speed sha256)
Samples: 48K of event 'cycles:P', 4000 Hz, Event count (approx.): 9012250000 lost: 0/0 drop: 0/0
Overhead  Shared Object        Symbol
  71.48%  libcrypto.so.3       [.] sha256_block_data_order_avx2
   6.12%  [kernel]             [k] clear_page_erms
   2.03%  [kernel]             [k] _raw_spin_unlock_irqrestore
```text
`[.]` — user space, `[k]` — ядро. Много `[k]` у процесса = высокий `%sys`: смотри, какие
syscalls его вызывают (тема 05).

### Почему вместо функций — адреса или `[unknown]`

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `0x00007f3a…` вместо имени | Нет символов (stripped бинарник) | Пакет `-dbgsym` / debuginfod; для своего кода — не стрипать |
| Стеки обрываются на 1–2 кадрах | Код собран без frame pointers | `--call-graph dwarf` (тяжелее) или сборка с `-fno-omit-frame-pointer`. В Ubuntu 24.04 пакеты уже собраны с frame pointers |
| Видно только интерпретатор (`_PyEval_EvalFrameDefault`, JVM `Interpreter`) | JIT/интерпретатор: perf не знает имён функций языка | Python 3.12+: `python3 -X perf app.py` (или `PYTHONPERFSUPPORT=1`); Java: `-XX:+PreserveFramePointer` + perf-map-agent; Node: `--perf-basic-prof`; или профайлер языка (py-spy, async-profiler, pprof) |

```bash
python3 -X perf ~/perf/cpu_hog.py &            # Python 3.12: пишет /tmp/perf-PID.map
sudo perf record -F 99 -g -p $! -- sleep 20
sudo perf report --stdio --no-children | grep -m5 'py::'
#   38.10%  python3  perf-4312.map  [.] py::fib:/home/vagrant/perf/cpu_hog.py   ← пример
```text
---

## 4. Flame graph: профиль одной картинкой

```text
            ┌──────────┐
            │  fib     │        ← верхний край = функция, которая была НА CPU
      ┌─────┴──────────┴──┐┌─────────┐
      │      fib          ││ json.dumps│     ширина = доля сэмплов (≈ доля CPU)
   ┌──┴───────────────────┴┴─────────┴──┐    высота = глубина стека
   │           handle_request            │    ось X — НЕ время: кадры отсортированы
 ┌─┴─────────────────────────────────────┴┐        по алфавиту и склеены
 │                  main                   │
 └─────────────────────────────────────────┘
```text
Как читать: ищи **широкие плато сверху** — функции, которые сами жгут CPU. Широкая
«башня» внизу без плато — просто общий предок. Цвет в классическом flame graph случаен.

```bash
# Вариант 1 — скрипты Брендана Грегга (склонированы на стенде в ~/FlameGraph)
sudo perf record -F 99 -a -g -- sleep 30
sudo perf script > out.perf
~/FlameGraph/stackcollapse-perf.pl out.perf > out.folded
~/FlameGraph/flamegraph.pl out.folded > cpu.svg          # открыть в браузере, кликабельно

grep fib out.folded | ~/FlameGraph/flamegraph.pl > fib.svg   # отфильтровать по стекам

# Вариант 2 — inferno (Rust-порт, в ~20 раз быстрее на больших профилях)
cargo install inferno
sudo perf script | inferno-collapse-perf | inferno-flamegraph > cpu.svg

# Вариант 3 — сразу из eBPF, без perf.data на диске (тема 07)
sudo profile-bpfcc -F 99 -f 30 > out.folded && ~/FlameGraph/flamegraph.pl out.folded > cpu.svg
```text
> В upstream perf есть `perf script report flamegraph` (HTML), но в Ubuntu-пакетах
> linux-tools скрипты perf обычно не поставляются — надёжнее FlameGraph или inferno.
> **Off-CPU flame graph** (где процесс *ждёт*, а не считает) строится из `offcputime-bpfcc -f` —
> это ответ на «тормозит, а CPU почти не ест».

---

## 5. Steal: когда CPU отобрал гипервизор

`%steal` — время, когда vCPU был готов работать, но гипервизор выполнял кого-то другого.
Внутри VM это выглядит как «всё медленнее без причины».

```text
# пример вывода: mpstat 1 — облачная VM на burstable-инстансе после исчерпания кредитов
CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle
all   38.12    0.00    2.01    0.00    0.00    0.25   59.62    0.00    0.00    0.00
```text
| Причина | Как отличить | Что делать |
|---------|--------------|------------|
| «Шумный сосед» на хосте | steal скачет без связи с твоей нагрузкой | Миграция/пересоздание VM, dedicated host |
| Burstable-инстанс (AWS T-семейство и аналоги) исчерпал CPU-кредиты | steal растёт ровно до «базовой» доли, в консоли облака кредиты = 0 | Инстанс с постоянной производительностью или unlimited-режим |
| Переподписка своего гипервизора | steal на всех VM хоста, на хосте высокий `%guest` | Меньше vCPU на хост |

> ⭐ Доказательство для тикета в облако: `sar -u -f /var/log/sysstat/saDD` с колонкой
> `%steal` за время инцидента (тема 01). Без steal-метрики в мониторинге это не докажешь.

---

## 6. Частота и тепловой троттлинг CPU

«CPU 50%» — это 50% *времени*, а не 50% *мощности*: ядро на 800 МГц работает втрое
медленнее, чем на 2,4 ГГц, при тех же процентах.

```bash
grep MHz /proc/cpuinfo                                        # текущая частота ядер
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor     # powersave / performance / schedutil
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq     # кГц
sudo turbostat --quiet --interval 5      # Busy%, Bzy_MHz (частота под нагрузкой), CoreTmp, PkgWatt
dmesg -T | grep -i -E 'throttl|temperature'      # тепловой троттлинг ядро пишет в лог
cat /sys/devices/system/cpu/cpu0/thermal_throttle/core_throttle_count   # Intel: счётчик событий
```text
| Где | Что видно |
|-----|-----------|
| Железный сервер | Governor `powersave` на проде, троттлинг от перегрева (пыль, вентиляторы, BIOS power limits) |
| VM в облаке / на стенде | `cpufreq` обычно **нет** — частотой управляет хост; turbostat может не работать |
| Контейнер | «Троттлинг» там — это CFS-квота cgroup, а не частота. Совсем другой механизм → [06_cgroups_containers.md](/performance/06-cgroups-containers) |

---

## 7. Память: page cache против «занятой»

Базовое правило «смотри на `available`» — в [../Linux/14_process_utilization.md](/linux/14-process-utilization).
Глубже — из чего оно складывается.

```text
# пример вывода: free -w -m (VM 4 ГБ, после копирования большого файла)
               total        used        free      shared     buffers       cache   available
Mem:            3915        1227         118         164          52        2833        2688
Swap:              0           0           0
```text
| Колонка | Смысл |
|---------|-------|
| `used` | В procps-ng 4.x (Ubuntu 24.04) это `total − available`, поэтому `used + free + buff/cache` ≠ `total` |
| `buffers` / `cache` | `Buffers` и `Cached + SReclaimable` из `/proc/meminfo`: page cache + освобождаемый slab; `-w` показывает их раздельно |
| `shared` | tmpfs и shared memory (`/dev/shm`, `/run`). **Входит в cache, но не освобождается** при нехватке |
| `available` | Оценка ядра: сколько можно выделить без свопа = free + освобождаемая часть кэша и slab − резерв |

Почему `available` < `free + cache`: tmpfs/shmem нельзя выбросить, dirty-страницы надо
сначала записать, а часть памяти ядро держит под водяные знаки (`vm.min_free_kbytes`).

```bash
grep -E 'MemAvailable|^Cached|Dirty|AnonPages|Shmem:|SReclaimable|SUnreclaim' /proc/meminfo
sudo slabtop -o | head -15        # память ядра: dentry/inode-кэш, сетевые буферы
df -h -t tmpfs                    # не съел ли память файл в /dev/shm или /run
```text
> ⚠️ `echo 3 | sudo tee /proc/sys/vm/drop_caches` сбрасывает кэш — **только для экспериментов**
> (например, «холодный» fio в теме 03). На проде это не «освобождает память», а ломает
> производительность: все читают с диска заново.

---

## 8. RSS, PSS, USS: сколько памяти на самом деле у процесса

```text
 процесс A                процесс B         RSS  = всё, что сейчас в RAM у процесса, включая общее
 ┌──────────────┐        ┌──────────────┐   USS  = только его приватные страницы
 │ приватные 50M│        │ приватные 30M│         (освободятся, если убить процесс)
 ├──────────────┴────────┴──────────────┤   PSS  = приватные + общие / число владельцев
 │   общие: libc, libpython, CoW — 40M  │
 └──────────────────────────────────────┘   A: RSS 90M, USS 50M, PSS 50 + 40/2 = 70M
                                            B: RSS 70M, USS 30M, PSS 30 + 40/2 = 50M
 Сумма RSS = 160M (больше реального!)       Сумма PSS = 120M — честная сумма по системе
```text
Где это важно: 16 воркеров gunicorn или PostgreSQL-бэкенды после `fork()` делят память
через copy-on-write. Сумма RSS покажет «8 ГБ», а реально занято 2 ГБ.

```bash
sudo smem -k -s pss -r | head             # колонки: PID User Command Swap USS PSS RSS
sudo smem -k -s pss -r -P gunicorn -t     # только gunicorn, с итогом
sudo cat /proc/4312/smaps_rollup          # то же для одного процесса, без smem
```text
```text
# пример вывода: /proc/PID/smaps_rollup (сокращено)
Rss:              412340 kB
Pss:              298117 kB
Private_Clean:      1204 kB
Private_Dirty:    280456 kB      ← USS = Private_Clean + Private_Dirty = 281660 kB
Shared_Clean:     118032 kB
Anonymous:        283900 kB
Swap:                  0 kB
```text
| Метрика | Когда смотреть |
|---------|----------------|
| RSS | Быстрая оценка; её же считает cgroup-лимит в контейнере (вместе с page cache — тема 06) |
| PSS | Кто сколько «весит» в сумме по системе; честная сумма по воркерам |
| USS | Сколько освободится, если убить процесс; рост USS = утечка именно в нём |

---

## 9. Swap, swappiness и major faults

`si/so` в `vmstat` — в [../Linux/14_process_utilization.md](/linux/14-process-utilization),
swap-файл — в [../Linux/10_the_filesystem.md](/linux/10-the-filesystem). Глубже:

```bash
sar -W 1          # pswpin/s pswpout/s — страницы свопа в секунду
sar -B 1          # majflt/s — чтение страниц с диска; pgscand/s — direct reclaim
pidstat -r 1      # minflt/s majflt/s VSZ RSS %MEM по процессам
```text
- **Major fault** — страницы нет в RAM, её читают с диска (из свопа или файла). Каждый
  стоит миллисекунды: процесс «тормозит», хотя CPU свободен.
- **`pgscand/s` > 0** — direct reclaim: процесс сам чистит память в момент аллокации.
  Это прямой рост латентности, даже если до OOM далеко.
- **`vm.swappiness`** (по умолчанию 60) — не порог «свопить после N% памяти», а баланс:
  что выгоднее выбрасывать под давлением — анонимную память (в своп) или page cache.
  Меньше — чаще жертвуют кэшем, больше — чаще свопят анонимное.

Для БД и latency-чувствительных сервисов лучше предсказуемый OOM, чем многочасовой
«своп-ад»: маленький swap с низким swappiness или без него. На стенде `perf-lab` свопа
нет — OOM в лабе 2 придёт быстро и честно.

---

## 10. Утечка памяти: как доказать

Утечка = **RSS/USS процесса монотонно растёт** под постоянной нагрузкой и не
возвращается. Рост page cache или буферов ядра — не утечка приложения.

```bash
pidstat -r -p 4312 60                         # RSS раз в минуту — тренд за час
while sleep 60; do echo "$(date +%T) $(ps -o rss= -p 4312)"; done | tee rss.log
```text
```text
# пример вывода: pidstat -r -p 4312 60
          UID       PID  minflt/s  majflt/s     VSZ     RSS   %MEM  Command
14:00:01 1000      4312    812.40      0.00  612340  201544   5.15  python3
14:01:01 1000      4312    797.13      0.00  654120  242968   6.21  python3
14:02:01 1000      4312    803.55      0.00  695900  284312   7.26  python3   ← +41 МБ/мин
```text
Где растёт — по картам памяти:
```bash
sudo pmap -x 4312 | sort -k3 -n | tail -5     # регионы с наибольшим RSS
sudo pmap -x 4312 > t1; sleep 300; sudo pmap -x 4312 > t2; diff t1 t2   # что выросло
```text
```text
# пример вывода: pmap -x (хвост после sort по RSS)
Address           Kbytes     RSS   Dirty Mode  Mapping
00007f1c2c000000  131072  131072  131072 rw---   [ anon ]
000055d5c7a1e000  284412  284300  284300 rw---   [ anon ]    ← heap растёт — утечка в куче
```text
| Растёт | Вероятно |
|--------|----------|
| `[ anon ]` / heap | Утечка объектов в коде: кэш без лимита, глобальный список, незакрытые ресурсы |
| Много регионов `[ anon ]` по 64 МБ | Арены glibc malloc у многопоточного процесса (фрагментация, не всегда утечка) |
| Отображения файлов | mmap без munmap, открытые файлы (проверь `ls /proc/PID/fd \| wc -l`, тема 04) |

Дальше — инструмент языка: Python `tracemalloc`/memray, Go `pprof` heap, Java heap dump
(`jmap`), Node `--heapsnapshot-signal`. Для C/C++ и «чёрного ящика» — `memleak-bpfcc -p PID`
([07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace)). Полный разбор — лаба 2 в [08_practice_labs.md](/softskills/08-practice-labs).

---

## 11. OOM killer: кого и почему

**Когда срабатывает:** аллокации не хватает памяти, reclaim не смог освободить страницы
(своп полон или его нет, кэш выжат). Два вида:
- **глобальный OOM** — кончилась память всей машины;
- **cgroup OOM** — процесс упёрся в `memory.max` своей cgroup (контейнер, systemd-юнит):
  на хосте память может быть свободна. Подробно — [06_cgroups_containers.md](/performance/06-cgroups-containers).

**Как выбирает жертву** (`mm/oom_kill.c`, `oom_badness`):
```text
badness = RSS + swap + page tables (в страницах)  +  oom_score_adj × totalpages / 1000
          └────────── доля памяти ───────────┘      └── поправка −1000…+1000 ──────┘
убивают процесс с максимальным badness; oom_score_adj = −1000 → не убьют никогда

/proc/PID/oom_score = (1000 + badness в ‰ от totalpages) × 2/3
                      у крошечного процесса с adj 0 это ~666, adj −1000 → 0
```text
```bash
for p in $(pgrep -d' ' .); do printf '%s %s %s\n' "$(cat /proc/$p/oom_score 2>/dev/null)" "$p" \
  "$(cat /proc/$p/comm 2>/dev/null)"; done | sort -rn | head      # кандидаты №1
systemctl show postgresql -p OOMScoreAdjust      # systemd: OOMScoreAdjust= в юните
```text
Kubernetes сам ставит `oom_score_adj` по QoS: Guaranteed −997, BestEffort 1000,
Burstable — между ([../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources)).

### Читаем OOM-отчёт построчно

```text
# пример: journalctl -k — глобальный OOM на VM 4 ГБ (сокращено)
python3 invoked oom-killer: gfp_mask=0x140cca(GFP_HIGHUSER_MOVABLE|__GFP_COMP), order=0, oom_score_adj=0
  └─ КТО ПОПРОСИЛ память последним. Это не обязательно виновник!
CPU: 1 PID: 4312 Comm: python3 Not tainted 6.8.0-…-generic
Call Trace: … out_of_memory …                     ← стек аллокации (обычно page fault)
Mem-Info:
active_anon:12 inactive_anon:941203 … active_file:95 inactive_file:103 … free:21538
  └─ почти всё — anon, file-кэша не осталось (≈200 страниц): выжимать больше нечего
Tasks state (memory values in pages):
[  pid  ]   uid  tgid total_vm      rss rss_anon rss_file rss_shmem pgtables_bytes swapents oom_score_adj name
[    612]     0   612    72351     1843      512     1331         0   184320        0          -250 systemd-journal
[   1024]   113  1024   275812    14210    12804     1406         0   548864        0             0 postgres
[   4312]  1000  4312  1012345   940512   939800      712         0  7630848        0             0 python3
  └─ снимок всех процессов: rss в СТРАНИЦАХ (×4 КБ). 940512 × 4 КБ ≈ 3,6 ГБ — вот он
oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,global_oom,task_memcg=/user.slice/user-1000.slice/session-3.scope,task=python3,pid=4312,uid=1000
  └─ CONSTRAINT_NONE + global_oom = кончилась память машины; task_memcg — чья cgroup
Out of memory: Killed process 4312 (python3) total-vm:4049380kB, anon-rss:3759200kB, file-rss:2848kB, shmem-rss:0kB, UID:1000 pgtables:7452kB oom_score_adj:0
  └─ КОГО убили и сколько он держал: anon-rss 3,6 ГБ
```text
| Строка | Глобальный OOM | cgroup OOM (контейнер, юнит) |
|--------|----------------|------------------------------|
| constraint | `CONSTRAINT_NONE`, `global_oom` | `CONSTRAINT_MEMCG`, `oom_memcg=/system.slice/docker-….scope` |
| Итог | `Out of memory: Killed process …` | `Memory cgroup out of memory: Killed process …` |
| Кандидаты | Все процессы машины | Только процессы этой cgroup |

```bash
journalctl -k | grep -E 'invoked oom-killer|Killed process'     # все OOM-события
journalctl -k -b -1 | grep -i 'killed process'                  # до последней перезагрузки
sudo dmesg -T | grep -A40 'invoked oom-killer' | less           # целиком, с человеческим временем
grep oom_kill /proc/vmstat                                      # счётчик OOM-убийств с загрузки
```text
Код выхода убитого процесса — 137 (128 + SIGKILL, см. [../Linux/07_processes.md](/linux/07-processes)).

> ⭐ «Invoked» ≠ «killed». Виновник — тот, у кого большой `rss` в таблице, а вызвать OOM
> мог любой невинный процесс, попросивший 4 КБ в неудачный момент.

**systemd-oomd** — OOM-киллер в user space: убивает cgroup целиком по давлению памяти
(PSI, тема 06) раньше, чем дойдёт до ядерного OOM. Включён по умолчанию на Ubuntu Desktop,
на серверных образах обычно не установлен. Если процессы «пропадают» без ядерного OOM
в логе — `journalctl -u systemd-oomd`, `oomctl`.

---

## 12. Overcommit: почему malloc почти всегда «успешен»

Linux раздаёт виртуальную память с запасом: реальные страницы выделяются при первом
обращении. VSZ в гигабайты — нормально, считать нужно RSS.

| `vm.overcommit_memory` | Поведение | Кто просит |
|------------------------|-----------|------------|
| `0` (по умолчанию) | Эвристика: отказывает только явно невозможным запросам | Почти все |
| `1` | Разрешать всегда; расплата — OOM killer при реальной нехватке | Redis (fork для BGSAVE), некоторые научные задачи |
| `2` | Строгий учёт: лимит `CommitLimit`, сверх — `malloc` получает `ENOMEM` | Где OOM недопустим, а ошибка аллокации обрабатывается |

```bash
sysctl vm.overcommit_memory vm.overcommit_ratio
grep -E 'CommitLimit|Committed_AS' /proc/meminfo
# CommitLimit  = swap + RAM × overcommit_ratio / 100   ← действует только в режиме 2
# Committed_AS = сколько виртуальной памяти уже обещано всем процессам
```text
> ⚠️ Режим 2 с дефолтным `overcommit_ratio=50` и без свопа: половина RAM «недоступна»
> для аллокаций — сервисы падают с ENOMEM при свободной памяти. Меняй вместе с ratio.

---

## 13. Hugepages и THP — кратко

| | Статические HugePages | Transparent Huge Pages (THP) |
|---|------------------------|------------------------------|
| Что | Заранее зарезервированные страницы 2 МБ/1 ГБ | Ядро само склеивает 4 КБ-страницы в 2 МБ |
| Настройка | `vm.nr_hugepages`, `HugePages_Total` в meminfo | `/sys/kernel/mm/transparent_hugepage/enabled`: `always` / `madvise` / `never` |
| Кто использует | PostgreSQL (`huge_pages`), Oracle, DPDK | Всё, что попросило через `madvise` (в Ubuntu 24.04 по умолчанию `madvise`) |
| Грабли | Зарезервированная память недоступна остальным | Всплески латентности (компакция, khugepaged), раздутый RSS |

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled     # always [madvise] never
grep -E 'AnonHugePages|HugePages_' /proc/meminfo
```text
Некоторые СУБД (Redis, старые версии MongoDB) просят `never` — сверяйся с документацией своей версии.

---

## 14. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Смотреть только `%CPU` в среднем | Одно ядро в полке прячется за «50%» | `mpstat -P ALL 1`, потоки через `pidstat -t` |
| `perf` без `-g` | Видна функция, но не кто её вызвал | `perf record -g`, flame graph |
| Flame graph по X как по времени | Ось X отсортирована по алфавиту | Ширина = доля CPU; время — `perf script` / timeline |
| Профилировать Python/Java голым perf | Виден только интерпретатор | `-X perf`, perf-map-agent, py-spy |
| Паника от маленького `free` | Кэш — это хорошо | `available`, `si/so`, PSI |
| Складывать RSS воркеров | Общие страницы посчитаны N раз | PSS (`smem`) |
| «Утечка», потому что вырос cache | Page cache растёт до упора и это норма | RSS/USS конкретного процесса во времени |
| Винить процесс из `invoked oom-killer` | Он мог просить 4 КБ | Таблица Tasks state и строка `Killed process` |
| `oom_score_adj = -1000` «всем важным» | OOM убьёт кого-то ещё хуже или повиснет машина | −1000 — только для sshd/агентов; лимиты памяти важнее |
| `overcommit_memory=2` без расчёта | ENOMEM при свободной RAM | Считать `CommitLimit`, настроить ratio/своп |

---

## 💼 Как это в DevOps

- «Сервис тормозит» на дежурстве: `mpstat -P ALL` и `pidstat -u -w` за минуту показывают,
  CPU это или ожидание; если CPU — `perf top -p` сразу даёт функцию для тикета разработчикам.
- Flame graph — лучший аргумент в споре «это инфраструктура тормозит»: картинка с широким
  плато в `json.dumps` или regex снимает вопрос.
- Continuous profiling (Parca, Pyroscope) — те же flame graphs, но постоянно и по всему
  парку: видно, какой релиз добавил CPU ([07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace)).
- Каждое OOM-событие — повод для алерта (`node_vmstat_oom_kill` из node_exporter) и разбора:
  утечка, неверный лимит или реальный рост нагрузки. Поднять лимит «×2» — не разбор.
- В облаке steal и исчерпанные CPU-кредиты — частая причина «загадочных» тормозов; метрика
  steal должна быть на дашборде ноды.
- Размер пулов и воркеров считают по PSS/USS, а не по RSS — иначе серверы покупают вдвое
  больше нужного.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| CPU по ядрам | `mpstat -P ALL 1` |
| softirq по типам | `mpstat -I SCPU 1`, `/proc/softirqs` |
| Вытеснения процесса | `pidstat -w -p PID 1` (`nvcswch/s`) |
| Счётчики и IPC | `sudo perf stat -p PID -- sleep 10` |
| Горячие функции сейчас | `sudo perf top -p PID -g` |
| Записать профиль | `sudo perf record -F 99 -g -p PID -- sleep 30` |
| Отчёт | `sudo perf report --stdio --no-children` |
| Flame graph | `perf script \| stackcollapse-perf.pl \| flamegraph.pl > cpu.svg` |
| Python в perf | `python3 -X perf app.py` (3.12+) |
| Частота и температура | `sudo turbostat --quiet --interval 5` |
| Честная память | `sudo smem -k -s pss -r`, `/proc/PID/smaps_rollup` |
| Тренд RSS | `pidstat -r -p PID 60` |
| Где растёт память | `sudo pmap -x PID \| sort -k3 -n \| tail` |
| Своп и major faults | `sar -W 1`, `sar -B 1`, `pidstat -r 1` |
| OOM-события | `journalctl -k \| grep -E 'invoked oom-killer\|Killed process'` |
| Кандидат на OOM | `/proc/PID/oom_score`, `oom_score_adj` |
| Overcommit | `sysctl vm.overcommit_memory`, `CommitLimit`/`Committed_AS` |

---

## 🧠 Что запомнить

1. Смотри CPU по ядрам: однопоточный процесс в полке прячется за низким средним.
2. `%iowait` — это простой CPU, а не нагрузка; `%steal` — время, отобранное гипервизором.
3. Много `nvcswch/s` — процессу не хватает CPU; много `cswch/s` — он много ждёт.
4. `perf record -F 99 -g` + flame graph отвечают «в какой функции горит CPU» для любого языка;
   для интерпретаторов нужны perf-map (Python 3.12 `-X perf`) или профайлер языка.
5. Во flame graph важны широкие плато сверху; ось X — не время.
6. `available` — главная цифра памяти; `shared` (tmpfs) сидит в cache, но не освобождается.
7. RSS считает общие страницы у каждого; для суммы — PSS, для «сколько освободится» — USS.
8. Утечка = монотонный рост RSS/USS под постоянной нагрузкой; где — покажет `pmap -x` во времени.
9. OOM killer убивает максимальный badness (RSS + swap + page tables + поправка adj);
   «invoked» — не виновник, смотри таблицу и `Killed process`.
10. `CONSTRAINT_MEMCG` — упёрлись в лимит cgroup, `global_oom` — кончилась память машины.
11. Overcommit 0/1/2: режим 2 превращает OOM в ENOMEM, но требует расчёта `CommitLimit`.

➡️ Дальше: [03_disk_io.md](/performance/03-disk-io) · задачи: 02_cpu_memory_tasks.md


---

### Блок A. Теория


**A1.** Чем `%iowait` отличается от загрузки CPU? Почему iowait может упасть, хотя диск
по-прежнему тормозит?

<details><summary>Ответ</summary>

iowait — время, когда CPU **простаивал**, а в системе был незавершённый I/O. CPU при этом
свободен и может делать другую работу. Если параллельно появится CPU-нагрузка, простоя станет
меньше и iowait упадёт, хотя диск тормозит так же. Поэтому диск проверяют по `iostat -x`
(await, aqu-sz), а не по iowait.

</details>

**A2.** ⭐ Voluntary и involuntary context switches: что означает рост каждого?

<details><summary>Ответ</summary>

Voluntary — процесс сам уснул (I/O, lock, сеть, sleep): много таких = много ожидания,
мелких syscalls или конкуренции за блокировки. Involuntary — ядро вытеснило процесс по кванту
или ради более важной задачи: процессу не хватает CPU (ядер мало или CFS-квота cgroup).

</details>

**A3.** Почему в `perf record` берут `-F 99`, а не 100? Что даёт флаг `-g`?

<details><summary>Ответ</summary>

99 Гц не совпадает по фазе с периодическими событиями на 100 Гц (таймеры, тики),
иначе сэмплы систематически попадали бы в одни и те же места. `-g` записывает стек вызовов —
видно не только функцию, но и путь к ней; без этого нельзя построить flame graph.

</details>

**A4.** Что такое IPC в выводе `perf stat`? О чём говорит IPC 0,4?

<details><summary>Ответ</summary>

Instructions per cycle — сколько инструкций процессор выполняет за такт. 2–4 —
процессор реально считает. 0,4 — большую часть тактов он стоит: ждёт память (cache/TLB misses)
или ветвления. Оптимизировать надо доступ к данным (локальность, размер структур), а не «алгоритм»
в целом; дополнительные ядра такую задачу могут не ускорить.

</details>

**A5.** ⭐ Как читать flame graph: ширина, высота, ось X, «плато» сверху?

<details><summary>Ответ</summary>

Ширина кадра — доля сэмплов (≈ доля CPU) в этой функции и её потомках. Высота — глубина
стека, снизу предки, сверху вызываемые. Ось X — не время: кадры отсортированы по алфавиту
и склеены. Широкое «плато» на вершине — функция, которая сама жжёт CPU: её и оптимизируют.

</details>

**A6.** Почему perf показывает адреса вместо имён функций или только
`_PyEval_EvalFrameDefault`? Назови три причины и лечение каждой.

<details><summary>Ответ</summary>

1) Бинарник без символов (stripped) → пакеты `-dbgsym`/debuginfod, не стрипать свои сборки.

</details>

**A7.** Что такое `%steal`? Три типичные причины высокого steal.

<details><summary>Ответ</summary>

Время, когда vCPU был готов работать, но гипервизор отдал физическое ядро другому.
Причины: шумный сосед на хосте; burstable-инстанс исчерпал CPU-кредиты; переподписка
собственного гипервизора (слишком много vCPU на хост).

</details>

**A8.** Почему «CPU 50%» на железном сервере может означать «вдвое медленнее, чем вчера»?

<details><summary>Ответ</summary>

Проценты — это доля времени, а не мощности. Если ядра сбросили частоту (governor
`powersave`, тепловой троттлинг, power limits), при тех же 50% работы делается вдвое меньше.
Проверка: `turbostat` (Bzy_MHz, CoreTmp), `scaling_cur_freq`, `dmesg | grep -i throttl`.

</details>

**A9.** ⭐ Что показывает `available` в `free` и почему оно меньше `free + cache`?
Как считается `used` в procps-ng 4.x?

<details><summary>Ответ</summary>

`available` — оценка ядра (`MemAvailable`), сколько можно выделить без свопа: free +
освобождаемая часть page cache и slab минус резерв. Меньше `free + cache`, потому что tmpfs/shmem
(колонка `shared`) сидит в cache, но выброшен быть не может, dirty-страницы сначала надо записать,
часть slab занята, и ядро держит резерв `vm.min_free_kbytes`. В procps-ng 4.x `used = total − available`.

</details>

**A10.** ⭐ RSS, PSS и USS: определения и когда какую метрику смотреть.

<details><summary>Ответ</summary>

RSS — все страницы процесса в RAM, включая общие (библиотеки, CoW после fork). PSS —
приватные + общие, делённые на число процессов-владельцев; сумма PSS честная по системе.
USS — только приватные: столько освободится, если убить процесс. RSS — быстрая оценка;
PSS — «сколько весят 20 воркеров вместе»; USS — утечка в конкретном процессе.

</details>

**A11.** Что такое major fault и direct reclaim? Какими командами их увидеть?

<details><summary>Ответ</summary>

Major fault — страницы нет в RAM, ядро читает её с диска (своп или файл): миллисекунды
на каждый. Direct reclaim — процесс при аллокации сам освобождает память, потому что фоновый
kswapd не успевает: прямой рост латентности. Видно: `sar -B 1` (`majflt/s`, `pgscand/s`),
`pidstat -r 1` (`majflt/s` по процессам), `vmstat` (`si/so`).

</details>

**A12.** Что на самом деле регулирует `vm.swappiness`?

<details><summary>Ответ</summary>

Относительную «цену» выселения анонимной памяти (в своп) против page cache при давлении
памяти. Это не порог «свопить после N% RAM». Меньше значение — чаще жертвуют кэшем, больше —
охотнее свопят анонимные страницы. По умолчанию 60.

</details>

**A13.** ⭐ Как OOM killer выбирает жертву? Что такое `oom_score` и `oom_score_adj`, и почему
у обычного маленького процесса `oom_score` около 666?

<details><summary>Ответ</summary>

Для каждого процесса считается badness = RSS + swap + page tables (в страницах)
плюс `oom_score_adj × totalpages / 1000`; убивают максимальный. `oom_score_adj` от −1000
(никогда не убивать) до +1000 (убивать первым). `/proc/PID/oom_score` в современных ядрах =
`(1000 + badness в промилле от RAM+swap) × 2/3`: у крошечного процесса с adj 0 доля ≈ 0,
значит 1000 × 2/3 ≈ 666. Процесс с adj −1000 показывает 0.

</details>

**A14.** Как по OOM-отчёту отличить глобальный OOM от OOM в cgroup?

<details><summary>Ответ</summary>

Глобальный: `constraint=CONSTRAINT_NONE`, `global_oom`, итоговая строка
`Out of memory: Killed process …`, кандидаты — все процессы. cgroup: `constraint=CONSTRAINT_MEMCG`,
`oom_memcg=&lt;путь cgroup&gt;`, строка `Memory cgroup out of memory: Killed process …`, кандидаты —
только процессы этой cgroup, на хосте память может быть свободна.

</details>

**A15.** Режимы `vm.overcommit_memory` 0/1/2. Что такое `CommitLimit` и `Committed_AS`?

<details><summary>Ответ</summary>

0 — эвристика, отказ только явно невозможным запросам (дефолт). 1 — разрешать всегда,
расплата — OOM killer. 2 — строгий учёт: суммарные обещания не больше `CommitLimit = swap +
RAM × overcommit_ratio / 100`, сверх — `ENOMEM`. `Committed_AS` — сколько виртуальной памяти
уже обещано всем процессам.

</details>

**A16.** Чем могут навредить Transparent Huge Pages и какой режим по умолчанию в Ubuntu 24.04?

<details><summary>Ответ</summary>

Компакция памяти и работа khugepaged дают всплески латентности, а процессы с разреженным
доступом раздувают RSS (2 МБ вместо 4 КБ). Режимы `always`/`madvise`/`never`; в Ubuntu 24.04 — `madvise`:
огромные страницы получает только тот, кто попросил через `madvise()`.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ mpstat -P ALL 1          (VM 4 vCPU, веб-сервер под трафиком, жалобы на латентность)
```text
<details><summary>Ответ</summary>

⚠️ Всё softirq на ядре 3 (`%soft` 90%, idle 0): прерывания сетевой карты обрабатываются
одним ядром, оно в полке, пакеты копятся — латентность растёт при «57% idle» в среднем.
Проверить `mpstat -I SCPU 1` (NET_RX на CPU3), `/proc/interrupts`; лечить RSS/RPS, `irqbalance`,
больше очередей NIC.

</details>

```text:no-line-numbers
     CPU    %usr   %sys %iowait   %irq   %soft  %steal   %idle
```text
```text:no-line-numbers
     all   14.20   3.10    0.00   0.00   25.30    0.00   57.40
```text
```text:no-line-numbers
       0   18.00   4.00    0.00   0.00    1.00    0.00   77.00
```text
```text:no-line-numbers
       1   16.00   3.00    0.00   0.00    0.00    0.00   81.00
```text
```text:no-line-numbers
       2   15.00   3.00    0.00   0.00    0.00    0.00   82.00
```text
```text:no-line-numbers
       3    8.00   2.00    0.00   0.00   90.00    0.00    0.00
```text
```text:no-line-numbers
B2.  $ vmstat 1                  (4 ядра)            $ pidstat -w -p 2210 1
```text
<details><summary>Ответ</summary>

⚠️ CPU saturation: `r` 9 при 4 ядрах, `id` 0, у java 1450 вытеснений в секунду при 3
добровольных — потокам не хватает CPU. Дальше: `pidstat -t` (какие потоки), `perf top -p 2210`;
решение — оптимизировать горячий код, уменьшить число потоков или добавить ядра.

</details>

```text:no-line-numbers
      r  b ... us sy id wa st                        PID   cswch/s nvcswch/s  Command
```text
```text:no-line-numbers
      9  0 ... 96  4  0  0  0                        2210     3.00   1450.00  java
```text
```text:no-line-numbers
B3.  top - %Cpu(s): 21.3 us,  2.0 sy,  0.0 ni,  0.0 id,  0.0 wa,  0.0 hi,  0.3 si, 76.4 st
```text
<details><summary>Ответ</summary>

⚠️ Steal 76%: гипервизор отдаёт VM лишь четверть времени. На t-классе почти наверняка
кончились CPU-кредиты (проверить в консоли облака). Решение — инстанс с постоянной
производительностью или unlimited-режим; код тут ни при чём.

</details>

```text:no-line-numbers
     (облачная VM t-класса, сервис не менялся неделю)
```text
```text:no-line-numbers
B4.  $ sudo perf top
```text
<details><summary>Ответ</summary>

⚠️ Почти половина CPU — ожидание спинлока в ядре (lock contention). Смотреть стек:
`sudo perf record -g -a -- sleep 10` и `perf report` — кто берёт лок (часто один сокет/accept
на много потоков, epoll, файловая система, conntrack). `%sys` высокий по той же причине.

</details>

```text:no-line-numbers
     Overhead  Shared Object   Symbol
```text
```text:no-line-numbers
       44.81%  [kernel]        [k] native_queued_spin_lock_slowpath
```text
```text:no-line-numbers
        9.12%  [kernel]        [k] _raw_spin_lock
```text
```text:no-line-numbers
        3.40%  app             [.] handle_conn
```text
```text:no-line-numbers
B5.  $ sudo perf report --stdio --no-children | head
```text
<details><summary>Ответ</summary>

⚠️ Профиль интерпретатора: perf не знает Python-функций, `[unknown]` — JIT/без символов.
Перезапустить с `python3 -X perf` (3.12+) или взять `py-spy record/top` — будут видны функции
скрипта.

</details>

```text:no-line-numbers
       71.20%  python3  python3.12      [.] _PyEval_EvalFrameDefault
```text
```text:no-line-numbers
        8.03%  python3  python3.12      [.] _PyObject_Malloc
```text
```text:no-line-numbers
        5.11%  python3  [unknown]       [.] 0x00007f3a91c2b1e0
```text
```text:no-line-numbers
B6.  $ free -m
```text
<details><summary>Ответ</summary>

⚠️ `shared` 3,9 ГБ — это tmpfs/shared memory (например, файлы в `/dev/shm` или `/run`),
он входит в buff/cache, но не освобождается, поэтому `available` всего 611 МБ. Искать
`df -h -t tmpfs`, `du -sh /dev/shm/*`; удалить мусор или ограничить размер tmpfs.

</details>

```text:no-line-numbers
                    total    used    free   shared  buff/cache  available
```text
```text:no-line-numbers
     Mem:            7821    7210     180     3900        4300        611
```text
```text:no-line-numbers
     (в top нет процессов с RSS больше 300 МБ)
```text
```text:no-line-numbers
B7.  $ sudo smem -k -s pss -r -P gunicorn
```text
<details><summary>Ответ</summary>

⚠️ Сумма RSS считает общие страницы (CoW от master-процесса, библиотеки) восемь раз.
Реально: сумма PSS ≈ 8 × 91 ≈ 730 МБ; USS 58 МБ — сколько освободится при убийстве одного
воркера. Мониторинг надо строить на PSS или на памяти cgroup.

</details>

```text:no-line-numbers
       PID User     Command                  Swap      USS      PSS      RSS
```text
```text:no-line-numbers
      1201 app      gunicorn: worker          0     58.1M    91.4M   301.2M
```text
```text:no-line-numbers
      1202 app      gunicorn: worker          0     57.9M    91.2M   300.9M
```text
```text:no-line-numbers
      ... (ещё 6 воркеров с такими же цифрами)
```text
```text:no-line-numbers
     Мониторинг суммирует RSS: «gunicorn занимает 2,4 ГБ».
```text
```text:no-line-numbers
B8.  kernel: sshd invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0, oom_score_adj=0
```text
<details><summary>Ответ</summary>

⚠️ sshd лишь попросил страницу в неудачный момент («invoked»). Виновник — java: RSS

</details>

```text:no-line-numbers
     kernel: [  pid  ]   uid  tgid total_vm      rss ... oom_score_adj name
```text
```text:no-line-numbers
     kernel: [    901]     0   901     4012     1630 ...             0 sshd
```text
```text:no-line-numbers
     kernel: [   2210]  1001  2210  1302312   838912 ...             0 java
```text
```text:no-line-numbers
     kernel: Out of memory: Killed process 2210 (java) total-vm:5209248kB, anon-rss:3355648kB, ...
```text
```text:no-line-numbers
     Коллега: «sshd сломал сервер, надо его обновить».
```text
```text:no-line-numbers
B9.  kernel: oom-kill:constraint=CONSTRAINT_MEMCG,...,oom_memcg=/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod6f1c…slice,...,task=node,pid=5521
```text
<details><summary>Ответ</summary>

⚠️ Это не нехватка памяти ноды: `CONSTRAINT_MEMCG` и `oom_memcg=…pod…` — контейнер
упёрся в свой `limits.memory` (~512 Mi по anon-rss). В Kubernetes это `OOMKilled`, код 137.
Поднимать лимит или чинить потребление — [06_cgroups_containers.md](/performance/06-cgroups-containers).

</details>

```text:no-line-numbers
     kernel: Memory cgroup out of memory: Killed process 5521 (node) total-vm:1441200kB, anon-rss:523220kB, ...
```text
```text:no-line-numbers
     $ free -g  →  available: 11
```text
```text:no-line-numbers
B10.  $ sysctl vm.overcommit_memory vm.overcommit_ratio
```text
<details><summary>Ответ</summary>

⚠️ Режим 2: `CommitLimit` = 0 swap + 8 ГБ × 50% ≈ 4 ГБ, и `Committed_AS` уже упёрся
в него. Любая новая аллокация (в том числе fork) получает ENOMEM при 3,6 ГБ доступной RAM.
Вернуть режим 0 или поднять `overcommit_ratio`/добавить swap после расчёта.

</details>

```text:no-line-numbers
     vm.overcommit_memory = 2
```text
```text:no-line-numbers
     vm.overcommit_ratio = 50
```text
```text:no-line-numbers
     $ grep -E 'MemTotal|MemAvailable|SwapTotal|CommitLimit|Committed_AS' /proc/meminfo
```text
```text:no-line-numbers
     MemTotal:  8008420 kB   MemAvailable: 3620120 kB   SwapTotal: 0 kB
```text
```text:no-line-numbers
     CommitLimit: 4004208 kB   Committed_AS: 3998950 kB
```text
```text:no-line-numbers
     app: fork failed: Cannot allocate memory
```text
```text:no-line-numbers
B11.  $ pidstat -r -p 3300 600            (сервис под постоянной нагрузкой)
```text
<details><summary>Ответ</summary>

⚠️ Утечки нет: RSS сервиса стабилен (~402 МБ). Растёт page cache (buff/cache), а
`available` почти не изменился — кэш освобождаемый. Это нормальная работа ядра.

</details>

```text:no-line-numbers
     10:00  VSZ 812340  RSS 402112
```text
```text:no-line-numbers
     10:10  VSZ 812340  RSS 402320
```text
```text:no-line-numbers
     10:20  VSZ 812340  RSS 401980
```text
```text:no-line-numbers
     $ free -m (за то же время): buff/cache 1200 → 3900, available 5100 → 4950
```text
```text:no-line-numbers
     Коллега: «у сервиса утечка, память растёт».
```text
```text:no-line-numbers
B12.  $ sar -B 1
```text
<details><summary>Ответ</summary>

⚠️ Сильное давление памяти: `pgscand/s` 12 тысяч — direct reclaim (процессы сами
чистят память на аллокациях), `majflt/s` 612 — страницы читаются с диска, `%vmeff` 43% — reclaim
неэффективен. Система на грани thrashing: латентность растёт, скоро OOM. Искать потребителя
(`smem`, `pidstat -r`), смотреть PSI memory.

</details>

```text:no-line-numbers
     pgpgin/s pgpgout/s   fault/s  majflt/s  pgfree/s pgscank/s pgscand/s pgsteal/s    %vmeff
```text
```text:no-line-numbers
     48210.00   9120.00  51200.00    612.00  60210.00  81200.00  12410.00  40120.00     42.84
```text
---

### Блок C. Практика


### C1. 🔑 Однопоточный процесс в полке
**1.** `stress-ng --cpu 1 --cpu-method matrixprod --timeout 120s &`

<details><summary>Ответ</summary>

Среднее `mpstat 1` ≈ 50% usr на 2 vCPU, `mpstat -P ALL 1` — одно ядро 100%, второе ~0%;
`pidstat -u 1` — `stress-ng-cpu` ~100% `%CPU`; в `top` после `1` видно ядро в полке. Процесс
однопоточный: он может занять только одно ядро одновременно, лишние vCPU будут простаивать.

</details>

**2.** Покажи: `mpstat` без `-P ALL` («всё нормально»), `mpstat -P ALL 1` (одно ядро 100%),
   `pidstat -u 1` (кто), `top` с клавишей `1`.

<details><summary>Ответ</summary>

) Убит процесс с adj 0: у второго badness уменьшен на 500 × totalpages / 1000 (≈ половину RAM),
при равном RSS его badness ниже. Отчёт — `CONSTRAINT_NONE`, `global_oom`,
`Out of memory: Killed process`. Второй процесс добей сам: `pkill -f leak.py`.

</details>

**3.** Объясни, почему добавление vCPU этому процессу не поможет.

<details><summary>Ответ</summary>

```bash
sudo perf record -F 99 -g -p $PID -- sleep 20 && sudo perf script > out.perf
~/FlameGraph/stackcollapse-perf.pl out.perf | ~/FlameGraph/flamegraph.pl > perf.svg
sudo profile-bpfcc -F 99 -f -p $PID 20 > bcc.folded && ~/FlameGraph/flamegraph.pl bcc.folded > bcc.svg
sudo ~/.local/bin/py-spy record -o py.svg --pid $PID --duration 20
```text
perf и profile-bpfcc показывают весь стек, включая C-функции интерпретатора и ядро (с `-X perf` —
ещё и `py::` кадры). py-spy показывает чистые Python-функции с номерами строк, но не ядро и не C-код.

</details>

### C2. 🔑 perf: от процесса до функции
**1.** `python3 ~/perf/02/cpu_hog.py &` и `sudo perf top -p $!` — что в топе?

<details><summary>Ответ</summary>

Среднее `mpstat 1` ≈ 50% usr на 2 vCPU, `mpstat -P ALL 1` — одно ядро 100%, второе ~0%;
`pidstat -u 1` — `stress-ng-cpu` ~100% `%CPU`; в `top` после `1` видно ядро в полке. Процесс
однопоточный: он может занять только одно ядро одновременно, лишние vCPU будут простаивать.

</details>

**2.** Перезапусти с `python3 -X perf ~/perf/02/cpu_hog.py &`, повтори.

<details><summary>Ответ</summary>

) Убит процесс с adj 0: у второго badness уменьшен на 500 × totalpages / 1000 (≈ половину RAM),
при равном RSS его badness ниже. Отчёт — `CONSTRAINT_NONE`, `global_oom`,
`Out of memory: Killed process`. Второй процесс добей сам: `pkill -f leak.py`.

</details>

**3.** `sudo perf record -F 99 -g -p &lt;PID&gt; -- sleep 20` → `sudo perf report --stdio --no-children | head -30`.
   Какая функция Python горячее: `fib` или `serialize`?

<details><summary>Ответ</summary>

```bash
sudo perf record -F 99 -g -p $PID -- sleep 20 && sudo perf script > out.perf
~/FlameGraph/stackcollapse-perf.pl out.perf | ~/FlameGraph/flamegraph.pl > perf.svg
sudo profile-bpfcc -F 99 -f -p $PID 20 > bcc.folded && ~/FlameGraph/flamegraph.pl bcc.folded > bcc.svg
sudo ~/.local/bin/py-spy record -o py.svg --pid $PID --duration 20
```text
perf и profile-bpfcc показывают весь стек, включая C-функции интерпретатора и ядро (с `-X perf` —
ещё и `py::` кадры). py-spy показывает чистые Python-функции с номерами строк, но не ядро и не C-код.

</details>

### C3. 🔑 Flame graph тремя способами
Для процесса из C2 (с `-X perf`): FlameGraph-скрипты, `sudo profile-bpfcc -F 99 -f -p &lt;PID&gt; 20`
и `sudo ~/.local/bin/py-spy record -o py.svg --pid &lt;PID&gt; --duration 20`. Сравни картинки:
что видно в каждой, что нет?

### C4. Voluntary против involuntary
Сравни `pidstat -w 1` для двух нагрузок: `stress-ng --cpu 4 --timeout 60s` (4 воркера на 2 vCPU)
и `while :; do sleep 0.001; done`. Какая колонка растёт в каждом случае и почему?

### C5. IPC: CPU-bound против memory-bound
`sudo perf stat -e cycles,instructions -- stress-ng --cpu 1 --cpu-method matrixprod -t 10s` и то же
для `stress-ng --stream 1 -t 10s`. Сравни IPC. Что делать, если `cycles` показывает `&lt;not supported&gt;`?

### C6. 🔑 RSS против PSS против USS
```text:no-line-numbers
# ~/perf/02/shared.py — родитель заполняет 200 МБ и форкает 3 ребёнка (copy-on-write)
```text
```text:no-line-numbers
import os, time
```text
```text:no-line-numbers
data = b"x" * (200 * 1024 * 1024)
```text
```text:no-line-numbers
for _ in range(3):
```text
```text:no-line-numbers
    if os.fork() == 0:
```text
```text:no-line-numbers
        time.sleep(600); os._exit(0)
```text
```text:no-line-numbers
time.sleep(600)
```text
Запусти, сравни `ps -o pid,rss,cmd -C python3`, `sudo smem -k -P shared.py -t` и `smaps_rollup`
одного ребёнка. Сколько памяти занято реально?

### C7. 🔑 Поймать утечку
`python3 ~/perf/02/leak.py &`. Докажи утечку тремя способами: `pidstat -r -p PID 5`,
`sudo pmap -x PID` дважды с `diff`, `smaps_rollup` (рост `Private_Dirty`). Останови до OOM.

### C8. 🔑 cgroup OOM против глобального
**1.** `sudo systemd-run --scope -p MemoryMax=200M python3 ~/perf/02/leak.py` — дождись смерти,
   найди отчёт в `journalctl -k`: constraint, `oom_memcg`, строка `Killed process`.

<details><summary>Ответ</summary>

Среднее `mpstat 1` ≈ 50% usr на 2 vCPU, `mpstat -P ALL 1` — одно ядро 100%, второе ~0%;
`pidstat -u 1` — `stress-ng-cpu` ~100% `%CPU`; в `top` после `1` видно ядро в полке. Процесс
однопоточный: он может занять только одно ядро одновременно, лишние vCPU будут простаивать.

</details>

**2.** ⚠️ Снапшот! Запусти два `leak.py`, одному поставь `echo -500 | sudo tee /proc/&lt;PID&gt;/oom_score_adj`.
   Дождись глобального OOM. Кого убили и почему? Сравни отчёты.

<details><summary>Ответ</summary>

) Убит процесс с adj 0: у второго badness уменьшен на 500 × totalpages / 1000 (≈ половину RAM),
при равном RSS его badness ниже. Отчёт — `CONSTRAINT_NONE`, `global_oom`,
`Out of memory: Killed process`. Второй процесс добей сам: `pkill -f leak.py`.

</details>

### C9. Overcommit на практике
**1.** `python3 -c "import time; x = bytearray(3 * 1024**3); time.sleep(30)" &` — сравни VSZ и RSS.

<details><summary>Ответ</summary>

Среднее `mpstat 1` ≈ 50% usr на 2 vCPU, `mpstat -P ALL 1` — одно ядро 100%, второе ~0%;
`pidstat -u 1` — `stress-ng-cpu` ~100% `%CPU`; в `top` после `1` видно ядро в полке. Процесс
однопоточный: он может занять только одно ядро одновременно, лишние vCPU будут простаивать.

</details>

**2.** ⚠️ `sudo sysctl vm.overcommit_memory=2`, повтори. Что изменилось? Посмотри `CommitLimit`.

<details><summary>Ответ</summary>

) Убит процесс с adj 0: у второго badness уменьшен на 500 × totalpages / 1000 (≈ половину RAM),
при равном RSS его badness ниже. Отчёт — `CONSTRAINT_NONE`, `global_oom`,
`Out of memory: Killed process`. Второй процесс добей сам: `pkill -f leak.py`.

</details>

**3.** Верни `sudo sysctl vm.overcommit_memory=0`.

<details><summary>Ответ</summary>

```bash
sudo perf record -F 99 -g -p $PID -- sleep 20 && sudo perf script > out.perf
~/FlameGraph/stackcollapse-perf.pl out.perf | ~/FlameGraph/flamegraph.pl > perf.svg
sudo profile-bpfcc -F 99 -f -p $PID 20 > bcc.folded && ~/FlameGraph/flamegraph.pl bcc.folded > bcc.svg
sudo ~/.local/bin/py-spy record -o py.svg --pid $PID --duration 20
```text
perf и profile-bpfcc показывают весь стек, включая C-функции интерпретатора и ядро (с `-X perf` —
ещё и `py::` кадры). py-spy показывает чистые Python-функции с номерами строк, но не ядро и не C-код.

</details>

### C10. Кандидаты на OOM и защита сервиса
Выведи топ-5 процессов по `oom_score`. Запусти `sudo systemd-run --unit=demo -p OOMScoreAdjust=-900 sleep 600`
и проверь `oom_score_adj` его процесса.

---

### Блок D. Инциденты


**D1.** Ночью Java-сервис перезапустился. В логах приложения пусто, `systemctl status` показывает
`code=killed, status=9/KILL`. Как доказать или опровергнуть OOM?

<details><summary>Ответ</summary>

`journalctl -k --since … | grep -E 'invoked oom-killer|Killed process'` (или
`journalctl -k -b -1` при ребуте), `grep oom_kill /proc/vmstat`; для cgroup-юнита —
`systemctl status` может показать `oom-kill`, а `memory.events` юнита — счётчик `oom_kill`. Нет
записей OOM — искать другой источник SIGKILL: systemd-oomd (`journalctl -u systemd-oomd`),
watchdog/таймаут остановки юнита, человек или скрипт с `kill -9`.

</details>

**D2.** После переезда в облако p99 API вырос вдвое. CPU utilization ~40%, код и конфиг те же.
Три гипотезы и как проверить каждую.

<details><summary>Ответ</summary>

1) Steal/CPU-кредиты — `mpstat` `%steal`, кредиты в консоли облака. 2) Меньше ядер или
другая частота — `nproc`, `lscpu`, `perf stat` (GHz, IPC) против старого сервера. 3) Сеть и диск
облака медленнее (сетевые диски с лимитом IOPS, межзонные вызовы) — `iostat -x` await,
`ss -ti` rtt. Плюс лимиты контейнера (throttling), если переехали и в Kubernetes.

</details>

**D3.** Мониторинг показывает «сервис из 20 воркеров занимает 12 ГБ», нода на 8 ГБ живёт спокойно.

<details><summary>Ответ</summary>

Мониторинг суммирует RSS, а воркеры после fork делят страницы (CoW, библиотеки).
Реальное потребление — сумма PSS (`smem -t`) или память cgroup контейнера (`memory.current`).
Исправить метрику на дашборде.

</details>

**D4.** `available` 200 МБ из 8 ГБ, но в `top` нет процессов с большим RSS. Где память?

<details><summary>Ответ</summary>

Кандидаты вне RSS процессов: tmpfs/shm (`shared` в `free`, `df -h -t tmpfs`); память ядра —
slab (`slabtop`, `SUnreclaim` в meminfo: например, раздутый dentry-кэш или утечка в драйвере);
зарезервированные HugePages (`HugePages_Total`); память виртуалок/ZFS ARC, если есть; удалённые,
но открытые файлы на tmpfs (`lsof +L1`).

</details>

**D5.** Каждую ночь в 02:00 OOM убивает PostgreSQL, хотя в это время работает только скрипт бэкапа.

<details><summary>Ответ</summary>

OOM убивает того, у кого максимальный badness, а PostgreSQL с большим shared_buffers — самый
«тяжёлый». Бэкап (pg_dump + сжатие, или копирование через page cache с большим anon) вызывает
нехватку. Смотреть таблицу Tasks state в отчёте. Лечение: ограничить бэкап (`systemd-run -p MemoryMax=…`,
отдельный юнит с лимитом), `OOMScoreAdjust=-900` для postgres, перенести бэкап на реплику.

</details>

**D6.** Периодические всплески латентности по 200–500 мс. `sar -B` в эти моменты показывает
`pgscand/s` в тысячах, `/sys/kernel/mm/transparent_hugepage/enabled` = `[always]`.

<details><summary>Ответ</summary>

THP `always` → khugepaged и прямая компакция памяти при аллокациях дают всплески
латентности; `pgscand` подтверждает direct reclaim. Переключить на `madvise` или `never`
(`echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled`, постоянно — параметр ядра
`transparent_hugepage=madvise`), проверить, не нужен ли THP конкретной БД.

</details>

**D7.** После «hardening» с `vm.overcommit_memory=2` сервисы падают с `Cannot allocate memory`,
хотя свободно 40% RAM.

<details><summary>Ответ</summary>

В режиме 2 лимит — `CommitLimit = swap + RAM × overcommit_ratio/100`; при ratio 50 и без
свопа половина RAM недоступна для обещаний, а `Committed_AS` у JVM/Go-процессов большой
(резервируют виртуальную память). Вернуть 0 или рассчитать ratio по `Committed_AS` с запасом.

</details>

**D8.** `perf top` на API-сервере: 40% в `[k] native_queued_spin_lock_slowpath`, `%sys` 45%.

<details><summary>Ответ</summary>

Lock contention в ядре — потоки конкурируют за один спинлок. `sudo perf record -a -g -- sleep 10`,
в `perf report` раскрыть стеки над `native_queued_spin_lock_slowpath`: какой syscall/подсистема
(accept на одном сокете → SO_REUSEPORT; conntrack; одна файловая система/inode; futex в приложении).
Лечить причину конкуренции, а не добавлять ядра — от них станет хуже.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Сервер тормозит, CPU 100%. Твои действия?

<details><summary>Ответ</summary>

Сначала масштаб: `mpstat -P ALL 1` (все ядра или одно, us или sy/si/st), `pidstat -u 1` (кто),
   `vmstat 1` (`r` против ядер). Если us — `perf top -p PID`/flame graph → функция; sy — `strace -c`,
   perf со `[k]`; si — прерывания; st — гипервизор. Параллельно — «что изменилось» (деплой, трафик).
   Смягчение (откат, scale out) — до поиска первопричины.

</details>

**2.** Что значат `us`, `sy`, `wa`, `st` в top?

<details><summary>Ответ</summary>

us — код приложений, sy — ядро по просьбе процессов (syscalls, page faults), wa — простой CPU
   при незавершённом I/O (не нагрузка), st — время, отобранное гипервизором.

</details>

**3.** Как найти, какая функция в приложении ест CPU?

<details><summary>Ответ</summary>

`perf record -F 99 -g -p PID -- sleep 30` + `perf report` или flame graph; для Python —
   `-X perf` или py-spy, для Java — async-profiler, для Go — pprof. На проде — коротко, 99 Гц.

</details>

**4.** Что такое flame graph и как его читать?

<details><summary>Ответ</summary>

Визуализация сэмплированных стеков: ширина = доля CPU, высота = глубина стека, ось X не время;
   ищут широкие плато сверху — функции, которые сами жгут CPU.

</details>

**5.** Как понять, что серверу не хватает памяти?

<details><summary>Ответ</summary>

Не по `free`, а по `available`, `si/so` и `majflt` (своп и чтение страниц), `pgscand`
   (direct reclaim), PSI memory, OOM-событиям в `dmesg`.

</details>

**6.** Чем отличаются VSZ, RSS и PSS?

<details><summary>Ответ</summary>

VSZ — вся виртуальная память (обещанная, не выделенная), почти бесполезна. RSS — страницы
   в RAM, включая общие. PSS — общие страницы поделены между владельцами, честно суммируется.

</details>

**7.** Как работает OOM killer и как защитить важный процесс?

<details><summary>Ответ</summary>

При нехватке памяти ядро убивает процесс с максимальным badness (RSS + swap + page tables +
   поправка `oom_score_adj`). Защита: `oom_score_adj`/`OOMScoreAdjust=` (−1000 — только для
   критичного вроде sshd), но главное — лимиты памяти соседям (cgroups, systemd `MemoryMax=`).

</details>

**8.** Как найти утечку памяти на проде?

<details><summary>Ответ</summary>

Тренд RSS/USS под постоянной нагрузкой (`pidstat -r`, метрики), `pmap -x` во времени — какой
   регион растёт; дальше профайлер памяти языка (tracemalloc/memray, pprof heap, heap dump)
   или `memleak-bpfcc`. Отличать от роста page cache.

</details>

**9.** Что такое overcommit памяти в Linux?

<details><summary>Ответ</summary>

Ядро обещает больше виртуальной памяти, чем есть, а страницы выделяет при первом обращении.
   Режимы 0 (эвристика), 1 (всегда), 2 (строго по `CommitLimit`, иначе ENOMEM).

</details>

**10.** Нужен ли swap на сервере?

<details><summary>Ответ</summary>

Зависит от задачи: небольшой swap сглаживает редкие пики и выселяет холодные страницы, но
    для latency-чувствительных сервисов и БД своп-ад хуже быстрого OOM. Решение осознанное:
    размер, `swappiness`, мониторинг `si/so`. В Kubernetes swap исторически выключали.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Смотрю CPU по ядрам и отличаю us/sy/si/wa/st по смыслу, а не по названию
- [ ] Отличаю voluntary и involuntary context switches и знаю, что значит рост каждого
- [ ] `perf top`, `perf record -g`, `perf report` на стенде работают, IPC умею читать
- [ ] Построил flame graph тремя способами и объясняю, как его читать
- [ ] Python-профиль с `-X perf` показывает функции скрипта
- [ ] Читаю `free -w` и `/proc/meminfo`, объясняю `available` и `shared`
- [ ] Считаю RSS/PSS/USS и объясняю, почему сумма RSS врёт
- [ ] Доказал утечку по росту RSS и `pmap -x`
- [ ] Разобрал cgroup OOM и глобальный OOM построчно, объяснил, почему убит именно этот процесс
- [ ] Знаю режимы overcommit и последствия режима 2
