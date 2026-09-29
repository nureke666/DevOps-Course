---
title: "01. Методология: USE, «60 секунд» и load average"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 01. Опирается на"
---

# 01. Методология: USE, «60 секунд» и load average

> Блок → Deep Linux Troubleshooting & Performance → тема 01. Опирается на
> [../Linux/14_process_utilization.md](/linux/14-process-utilization) (top, vmstat, iostat,
> sar — базово), [../Linux/21_troubleshooting.md](/linux/21-troubleshooting) (диагностика
> сети снизу вверх) и [../Left/02_Monitoring/07_what_to_monitor.md](/monitoring/07-what-to-monitor)
> (USE и RED как метрики в Prometheus).
>
> **После темы ты умеешь:** идти по методу вместо случайных команд; за минуту снять картину
> системы чек-листом Брендана Грегга и объяснить каждую важную колонку; правильно читать load
> average; отличать latency от throughput; вести расследование как эксперимент и отвечать
> на «что было в 03:00» через историю sar.

---

## 🗺️ Карта темы

```text
 жалоба: «тормозит»
        │
        ▼
 RED сервиса ─────────► какой эндпоинт, с какого времени, какой хост/под?
        │
        ▼
 «60 секунд» на хосте ─► uptime · dmesg · vmstat · mpstat · pidstat · iostat · free · sar×2 · top
        │
        ▼
 USE по каждому ресурсу: Errors → Saturation → Utilization
        │                       │
        │     ничего не нашли?  └──► программные ресурсы: fd, conntrack, порты, пулы, cgroups
        ▼
 гипотеза + предсказание ──► замер (02 CPU/память · 03 диск · 04 сеть · 05 strace · 06 cgroups · 07 eBPF)
        │
        ▼
 одно изменение ──► замер «после» тем же инструментом ──► причина доказана ──► постмортем
```text
---

## 1. Почему метод, а не «команды по привычке»

Брендан Грегг описывает **анти-методы** — то, чем занимаются под давлением инцидента:

| Анти-метод | Как выглядит | Чем плох |
|------------|--------------|----------|
| **Streetlight** («под фонарём») | Смотрю `top`, потому что его знаю | Видишь только то, что умеет инструмент; диск и сеть остаются в темноте |
| **Random change** | Покрутил `somaxconn`, `swappiness`, перезапустил | Непонятно, что помогло; часто становится хуже, а причина остаётся |
| **Blame someone else** | «Это сеть», «это база» | Задача уходит по кругу, время идёт |
| **Drunk man** | Меняю всё подряд, пока не пройдёт | То же, что random change, только дольше |

**Методы**, которые работают:

| Метод | Вопрос | Когда |
|-------|--------|-------|
| **USE** | Какой ресурс упёрся или сломан? | Хост, VM, нода — всегда первым |
| **RED** | Какому сервису плохо и насколько? | Сервисы и API (детали — в мониторинге) |
| **Workload characterization** | Кто создаёт нагрузку, зачем, какую, как меняется во времени? | Когда ресурс найден, а виновник — нет |
| **Drill-down** | Спускаемся слоями: сервис → процесс → syscall → ядро | После USE, инструментами тем 02–07 |
| **Чек-лист «60 секунд»** | Что видно десятью командами за минуту? | Первая минута на незнакомом хосте |

> ⭐ Главное преимущество метода — он показывает не только проблему, но и **отсутствие**
> проблемы: «CPU, память и сеть в норме, насыщен только диск» — это уже половина ответа.

---

## 2. USE-метод на CLI

Определения и PromQL — в [../Left/02_Monitoring/07_what_to_monitor.md](/monitoring/07-what-to-monitor).
Здесь — **какая команда отвечает на какой вопрос** на живом хосте.

| Ресурс | Utilization | Saturation | Errors |
|--------|-------------|------------|--------|
| **CPU** | `mpstat -P ALL 1`: `100 − %idle` по каждому ядру | `vmstat 1`: `r` > числа ядер; `sar -q`: `runq-sz`; `/proc/pressure/cpu`; `runqlat-bpfcc` | `dmesg`: MCE, thermal throttling |
| **Память** | `free -m`: `available` против `total` | `vmstat 1`: `si`/`so` > 0; `sar -B`: `pgscand/s`, `majflt/s`; `/proc/pressure/memory` | `dmesg`: `Out of memory`; `memory.events` → `oom_kill` |
| **Диск (I/O)** | `iostat -xz 1`: `%util` (⚠️ не для NVMe/RAID) | `iostat`: `aqu-sz`, `r_await`/`w_await`; `/proc/pressure/io` | `dmesg`: `I/O error`, `EXT4-fs error`; `smartctl -a` |
| **Диск (место)** | `df -h`, `df -i` | — (пока есть место, очереди нет) | `ENOSPC` в логах приложения |
| **Сеть** | `sar -n DEV 1`: `rxkB/s`/`txkB/s` против скорости линка, `%ifutil` | `ip -s link`: `dropped`; `nstat`: `ListenOverflows`; `sar -n ETCP`: `retrans/s` | `sar -n EDEV 1`; `ethtool -S` |
| **Программные** | fd: `ls /proc/PID/fd \| wc -l`; conntrack: `nf_conntrack_count` | fd против `ulimit -n`; count против `nf_conntrack_max`; `cpu.stat` → `nr_throttled` | `Too many open files`, `table full, dropping packet`, `cannot assign requested address` |

Порядок обхода — **E → S → U**:
- **Errors** первыми: они дешёвые и однозначные. Одна строка `Out of memory` в `dmesg`
  объясняет больше, чем полчаса графиков.
- **Saturation** — вторыми: очередь означает, что кто-то **уже ждёт**, то есть страдает latency.
- **Utilization** — последней: 90% CPU без очереди — просто хорошо загруженная машина.

> ⚠️ Utilization за интервал прячет всплески: «60% за минуту» может быть 30 секунд по 100%
> и 30 секунд простоя. Для коротких всплесков нужны интервалы по 1 секунде и гистограммы
> (тема [07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace)).

**Программные ресурсы** забывают чаще всего, а ломаются они не реже железа: файловые
дескрипторы, conntrack, эфемерные порты, пулы потоков и соединений к БД, лимиты cgroups.
Если USE по железу чистый, а сервису плохо — ищи здесь (темы
[04_network_deep.md](/performance/04-network-deep) и [06_cgroups_containers.md](/performance/06-cgroups-containers)).

---

## 3. RED → USE: от сервиса к ресурсу

```text
 RED (Grafana / SLO)                      USE (хост / под)
 ─────────────────────────────            ──────────────────────────────────────
 Duration p99 /checkout ×10 с 13:40 ──►   какие инстансы? все или один?
 Errors: 504 от payments          ──►     на хосте payments: 60 секунд + USE
 Rate без изменений               ──►     значит, не нагрузка, а деградация
                                          ▼
                                  диск: w_await 180 мс, aqu-sz 36 ──► кто пишет? (pidstat -d)
```text
RED говорит **«что и где болит»** (детали — [../Left/02_Monitoring/07_what_to_monitor.md](/monitoring/07-what-to-monitor)
и [../SRE/02_sli_slo_error_budget.md](/sre/02-sli-slo-error-budget)), USE — **«почему»**.
Когда ресурс найден, включается **workload characterization**:

| Вопрос | Команда (пример для диска) |
|--------|----------------------------|
| **Кто?** PID, пользователь, контейнер | `pidstat -d 1`, `sudo iotop -o` |
| **Почему?** какой код/стек | `sudo perf record -g`, `sudo biosnoop-bpfcc`, `strace -p` |
| **Что?** операции, размер, чтение/запись | `iostat -xz 1`: `r/s`, `w/s`, `rareq-sz`, `wareq-sz` |
| **Как меняется?** всплески, тренд, время суток | `sar -d -p -f …`, графики node_exporter |

---

## 4. «Linux Performance Analysis in 60 Seconds»

Чек-лист Брендана Грегга из статьи Netflix (2015): десять команд, которые за минуту дают
картину USE почти по всем ресурсам. Запоминается как «цепочка», а не как список.

```bash
uptime
sudo dmesg -T | tail          # на Ubuntu kernel.dmesg_restrict=1 → нужен sudo
vmstat 1
mpstat -P ALL 1
pidstat 1
iostat -xz 1
free -m
sar -n DEV 1
sar -n TCP,ETCP 1
top
```text
### 4.1. `uptime` — есть ли нагрузка и куда она идёт

```text
# пример вывода, VM 2 vCPU
 14:02:11 up 12 days,  3:40,  1 user,  load average: 8.12, 5.40, 1.95
```text
1-минутный LA намного выше 15-минутного → нагрузка **растёт прямо сейчас**. Обратная
картина (`0.9, 3.2, 7.8`) — проблема проходит, и ты, возможно, пришёл к её хвосту.
Что входит в LA — раздел 5.

### 4.2. `dmesg -T | tail` — ошибки ядра

Ищешь строки, которые сразу называют причину: `Out of memory: Killed process`,
`nf_conntrack: table full, dropping packet`, `blocked for more than 120 seconds`,
`I/O error`, `Possible SYN flooding`. Полная таблица — в [../Linux/15_logging.md](/linux/15-logging).
Это буква **E** из USE сразу для всех ресурсов.

### 4.3. `vmstat 1` — общая картина по секундам

```text
# пример вывода, VM 2 vCPU, procps-ng 4.0 (Ubuntu 24.04)
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0      0 812344  52104 2410200    0    0    12    40  210  390  3  1 96  0  0  0   ← среднее с загрузки
 5  0      0 811920  52104 2410216    0    0     0     0 2110 1850 97  3  0  0  0  0
 6  0      0 811880  52104 2410216    0    0     0    64 2098 1911 98  2  0  0  0  0
```text
| Колонка | Что значит | Тревога |
|---------|------------|---------|
| `r` | Runnable: выполняются **или ждут** CPU | Стабильно больше числа ядер → CPU saturation |
| `b` | Заблокированы в ожидании I/O (D-state) | Любое устойчивое значение > 0 |
| `free` / `buff` / `cache` | Свободно / буферы / page cache (КиБ) | `free` мал — не тревога сам по себе (тема 02) |
| `si` / `so` | Swap-in / swap-out, КиБ/с | Постоянно > 0 → не хватает RAM |
| `bi` / `bo` | Блоков прочитано / записано в секунду | Сравни с `iostat` — там детали по устройствам |
| `in` / `cs` | Прерывания / переключения контекста в секунду | Резкий рост `cs` → конкуренция потоков, блокировки |
| `us sy id wa st gu` | user / system / idle / iowait / steal / guest | `sy` > 20–30%, `wa` ≫ 0, `st` > 5–10% |

> ⚠️ **Первая строка** `vmstat` и `iostat` — среднее **с момента загрузки**. Для
> диагностики её пропускают и смотрят со второй.

Здесь: `r` 5–6 при 2 ядрах, `us` 97–98%, `id` 0 → CPU насыщен пользовательским кодом.

### 4.4. `mpstat -P ALL 1` — баланс по ядрам

```text
# пример вывода
02:03:15 PM  CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle
02:03:16 PM  all   51.50    0.00    1.00    0.00    0.00    0.50    0.00    0.00    0.00   47.00
02:03:16 PM    0    2.00    0.00    1.00    0.00    0.00    1.00    0.00    0.00    0.00   96.00
02:03:16 PM    1  100.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00
```text
«В среднем 50%» при одном ядре в полке — **однопоточное узкое место** (однопоточный
процесс, Redis, Node.js, большой lock). `%soft` высокий на одном ядре — сетевые прерывания
на одной очереди NIC. `%steal` — CPU забирает гипервизор (тема 02).

### 4.5. `pidstat 1` — кто ест CPU, без мелькания `top`

```text
# пример вывода
02:03:20 PM   UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
02:03:21 PM  1000      4312   61.00    1.00    0.00   37.00   62.00     1  python3
02:03:21 PM  1000      4390   63.00    0.00    0.00   36.00   63.00     0  stress-ng-cpu
02:03:21 PM  1000      4391   62.00    1.00    0.00   36.00   63.00     0  stress-ng-cpu
```text
Печатает сводку каждую секунду, не перерисовывая экран, — удобно копировать в тикет.
**`%wait`** — доля времени, когда задача была готова работать, но **ждала CPU** в очереди:
прямая метрика CPU saturation по процессу. `%CPU` 100 = одно ядро целиком. Здесь три
CPU-bound процесса делят 2 ядра: каждый работает ~62% времени и ~36% стоит в очереди.

### 4.6. `iostat -xz 1` — диски

```text
# пример вывода (урезано до главных колонок)
Device     r/s    rkB/s  r_await   w/s    wkB/s  w_await  aqu-sz  %util
vda       2.00    16.00     0.80  3.00    40.00     1.20    0.01   0.60
vdb     410.00  3280.00    38.20  0.00     0.00     0.00   15.66  99.60
```text
`-x` — расширенная статистика, `-z` — скрыть простаивающие устройства. Смотришь на
**latency** (`r_await`/`w_await`, мс) и **очередь** (`aqu-sz`), а не только на `%util`.
Здесь vdb: 410 чтений/с по 8 КиБ, каждое ждёт 38 мс, в очереди ~16 запросов — диск насыщен
мелким случайным чтением. Все колонки и подвох с `%util` — [03_disk_io.md](/performance/03-disk-io).

### 4.7. `free -m` — память

```text
# пример вывода, VM 4 ГБ
               total        used        free      shared  buff/cache   available
Mem:            3915        3602          98           4         214         151
Swap:              0           0           0
```text
Смотришь на **`available`** — сколько можно выделить без свопа, с учётом освобождаемого
кэша. Здесь 151 МиБ из 3,9 ГиБ, кэш выжат до 214 МиБ, свопа нет → OOM близко.
Подробно — [02_cpu_memory.md](/performance/02-cpu-memory).

### 4.8. `sar -n DEV 1` — пропускная способность интерфейсов

```text
# пример вывода
02:04:01 PM     IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil
02:04:02 PM      eth0  81234.00  80112.00 118420.00 116980.00      0.00      0.00      0.00     97.01
```text
`rxkB/s`/`txkB/s` сравнивают со скоростью линка (`ethtool eth0 | grep Speed`); `%ifutil` —
то же в процентах (если драйвер сообщает скорость). ~118 МБ/с на гигабитном линке — полка.

### 4.9. `sar -n TCP,ETCP 1` — TCP-активность и ретрансмиты

```text
# пример вывода
02:04:10 PM  active/s passive/s    iseg/s    oseg/s
02:04:11 PM      2.00    840.00   9120.00   9870.00

02:04:10 PM  atmptf/s  estres/s retrans/s isegerr/s   orsts/s
02:04:11 PM      0.00      3.00    412.00      0.00     25.00
```text
| Колонка | Смысл |
|---------|-------|
| `active/s` | Исходящие соединения в секунду (`connect()`) — сервер как клиент БД/апстримов |
| `passive/s` | Входящие соединения в секунду (`accept()`) — грубо, новые клиенты |
| `iseg/s` / `oseg/s` | TCP-сегментов получено / отправлено |
| `retrans/s` | Ретрансмиты: ⚠️ 412 на ~9900 сегментов ≈ 4% — потери в сети или перегрузка |
| `atmptf/s` | Неудачные попытки соединения |
| `estres/s` / `orsts/s` | Сбросы установленных соединений / отправленные RST |

### 4.10. `top` — финальная сверка

После девяти команд `top` проверяет картину целиком: сходится ли `%CPU` процессов с `us/sy`,
нет ли процессов в состоянии `D` (колонка `S`) или зомби. Клавиши — в
[../Linux/14_process_utilization.md](/linux/14-process-utilization).

### Скрипт: снять картину в файл

На инциденте удобно сохранить всё сразу — пригодится для постмортема:

```bash
#!/usr/bin/env bash
# ~/perf/60s.sh — «60 секунд» в файл (~35 секунд работы)
out=~/perf/60s-$(hostname)-$(date +%F_%H%M%S).txt
{
  echo "### uptime";     uptime
  echo "### dmesg";      sudo dmesg -T | tail -n 30
  echo "### vmstat";     vmstat -w 1 5
  echo "### mpstat";     mpstat -P ALL 1 5
  echo "### pidstat";    pidstat 1 5
  echo "### iostat";     iostat -xz 1 5
  echo "### free";       free -m
  echo "### sar DEV";    sar -n DEV 1 5
  echo "### sar TCP";    sar -n TCP,ETCP 1 5
  echo "### top";        top -b -n 1 | head -25
} > "$out" 2>&1
echo "сохранено: $out"
```text
---

## 5. Load average: что на самом деле считается

```text
$ cat /proc/loadavg
2.27 2.62 2.25 5/3313 340192
 │    │    │   │  │     └─ последний выданный PID
 │    │    │   │  └─ всего задач (процессы + потоки)
 │    │    │   └─ сейчас в состоянии R
 │    │    └─ 15 минут ┐
 │    └─ 5 минут       ├─ экспоненциально сглаженное среднее, пересчёт каждые ~5 секунд
 └─ 1 минута           ┘
```text
**Что входит:** число задач в состоянии **R** (выполняются или ждут CPU) **плюс** в
состоянии **D** (uninterruptible sleep — диск, NFS, некоторые блокировки ядра). Так в Linux
с 1993 года; в других Unix LA — только очередь к CPU. Поэтому в Linux LA — это
«нагрузка на систему», а не «нагрузка на CPU».

```text
                 LA ≈ R (на CPU + в очереди) + D (ждут I/O и ядро)
                         │                        │
               сравнивай с nproc            CPU тут не поможет
```text
Как интерпретировать — всегда вместе с `nproc`, `vmstat` и `%idle`:

| Картина | Диагноз |
|---------|---------|
| LA 20 на 32 ядрах, `id` 40%, `r` ≈ 20 | Норма: загрузка ~62%, очереди нет |
| LA 20 на 4 ядрах, `id` 0%, `r` 18, `b` 0 | CPU saturation: 16 задач стоят в очереди → `pidstat`, `perf` (тема 02) |
| LA 20 на 4 ядрах, `id` 90%, `r` 1, `b` 18 | **D-state**: задачи ждут диск/NFS, CPU не виноват → `iostat`, `ps` по `D` (темы 03, 05) |
| LA 1.0 на 1 ядре | Ровно полная загрузка, без запаса |
| LA 8, 4, 1 | Всплеск начался несколько минут назад и растёт |

Найти, кто создаёт LA:
```bash
ps -eo state,pid,ppid,comm,wchan:32 | awk '$1 ~ /^[RD]/'     # кто в R и D прямо сейчас
vmstat 1 5                                                   # r против b
sar -q 1 3                                                   # runq-sz, blocked
cat /proc/pressure/cpu /proc/pressure/io                     # PSI: доля времени ожидания
```text
```text
# пример вывода: высокий LA при простаивающем CPU
S   PID  PPID COMMAND  WCHAN
D  3870  3861 rsync    rpc_wait_bit_killable
D  3871  3870 rsync    rpc_wait_bit_killable
D  3874  3702 du       rpc_wait_bit_killable        ← все ждут ответа NFS-сервера
```text
> ⚠️ **iowait — это разновидность idle.** CPU считается «в iowait», только когда ему нечего
> делать и при этом есть незавершённый блочный I/O. На загруженном CPU iowait падает до нуля,
> даже если диск тормозит; D-state на NFS или блокировках ядра может вообще не давать iowait.
> Поэтому «высокий iowait» — повод смотреть `iostat`, а «низкий iowait» — не алиби для диска.

> 💡 PSI (`/proc/pressure/*`) — более честная метрика saturation, чем LA: доля времени,
> когда хотя бы одна задача ждала ресурс (`some`) или ждали все (`full`). Подробно —
> [06_cgroups_containers.md](/performance/06-cgroups-containers).

---

## 6. Latency vs throughput и почему средние врут

| | Throughput | Latency |
|---|------------|---------|
| Что это | Сколько операций в единицу времени | Сколько длится одна операция |
| Единицы | RPS, IOPS, МБ/с, пакетов/с | мс, мкс: `await`, время ответа, RTT |
| Кому важно | Батчи, бэкапы, ETL | Пользователям, API, базам |

Связь через очередь: чем ближе утилизация к 100%, тем быстрее растёт время ожидания.
Простейшая модель очереди (M/M/1): **время ответа ≈ время обслуживания / (1 − U)**.

```text
 U = 50%  → ×2      U = 90% → ×10
 U = 80%  → ×5      U = 95% → ×20      ← «колено»: последние проценты загрузки самые дорогие
```text
Поэтому «диск делает на 10% больше IOPS» может быть **хуже**: 5000 IOPS при `w_await` 2 мс
против 5500 IOPS при 40 мс — throughput вырос, а пользователи страдают.

**Закон Литтла** — проверка на здравый смысл: `L = λ × W` (в системе = входящий поток × время).
Для диска: `aqu-sz ≈ (r/s × r_await + w/s × w_await) / 1000`. В примере из 4.6:
410 × 38,2 / 1000 ≈ 15,7 — ровно `aqu-sz`. Цифры сходятся — значит, читаешь правильно.

**Средние врут:**
- Среднее за секунду прячет хвост: `await` 5 мс может быть «99% по 1 мс и 1% по 400 мс».
- Среднее по ядрам прячет одно ядро в полке (раздел 4.4).
- Среднее по времени прячет всплески (раздел 2).
Лекарство — перцентили и гистограммы: `biolatency-bpfcc`, `runqlat-bpfcc`
(тема [07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace)), p99 в мониторинге.

---

## 7. Научный метод: гипотеза → замер → одно изменение

```text
 вопрос ──► гипотеза ──► предсказание ──► замер ──► подтвердилась? ──► одно изменение ──► замер «после»
               ▲                                        │ нет
               └────────────────────────────────────────┘
```text
Правила:
1. **Baseline до изменений.** Без «было» нельзя доказать «стало лучше».
2. **Предсказание до замера.** «Если это accept queue, `ListenOverflows` будет расти
   во время всплеска» — такую гипотезу можно опровергнуть. «Что-то с сетью» — нельзя.
3. **Одно изменение за раз**, и обратимое. Три sysctl сразу — и ты не знаешь, что сработало.
4. **Тот же инструмент и окно** для «до» и «после».
5. **Журнал с временем** — готовый таймлайн для постмортема ([../SRE/05_postmortems.md](/sre/05-postmortems)).

```text
# пример журнала расследования
14:02  симптом: p99 /api 2,3 с (норма 200 мс) с 13:40; RPS без изменений
14:03  60 с: LA 12 на 4 vCPU; us 20 sy 5 id 10 wa 65 → подозрение на I/O
14:05  H1: диск vdb насыщен. Предсказание: aqu-sz > 1, w_await ≫ 5 мс
14:06  iostat -xz: vdb w_await 180 мс, aqu-sz 36, w/s 190 → подтверждено
14:08  кто пишет: pidstat -d 1 → backup.sh (tar) 95 МБ/с, postgres (WAL) 2 МБ/с
14:10  изменение: ionice -c3 -p &lt;PID tar&gt;  (одно, обратимое)
14:13  vdb w_await 12 мс, p99 /api 250 мс → причина доказана
14:20  action item: бэкап — с реплики и с ionice в юните (IOSchedulingClass=idle)
```text
> 💡 Отрицательный результат — тоже результат: «H1 не подтвердилась, диск чистый» сужает
> поиск. Запиши и иди к следующей гипотезе.

---

## 8. sar-история: «что было в 03:00»

Как включить и базовые ключи — в [../Linux/14_process_utilization.md](/linux/14-process-utilization).
Глубже — как это устроено на Ubuntu 24.04:

| Что | Где / как |
|-----|-----------|
| Сбор | `sysstat-collect.timer` каждые 10 минут запускает `sa1` → бинарный `/var/log/sysstat/saDD` |
| Суточная сводка | `sysstat-summary.timer` → `sa2` → текстовый `sarDD` |
| Включение | `sudo systemctl enable --now sysstat` (переменная `ENABLED` в `/etc/default/sysstat` влияет только на cron-путь) |
| Сколько хранить | `HISTORY=` в `/etc/sysstat/sysstat` (в Ubuntu — 7 дней) |
| Что собирать | `SADC_OPTIONS=` там же: по умолчанию `-S DISK` — **без TCP/SNMP**; для `sar -n TCP` в истории нужен `-S XALL` |
| Чаще, чем раз в 10 минут | `sudo systemctl edit sysstat-collect.timer` → `[Timer]`, пустой `OnCalendar=`, затем `OnCalendar=*:00/2` |

> ⚠️ Новые `SADC_OPTIONS` применяются к **новому** суточному файлу: sadc не меняет набор
> метрик в уже начатом файле. Проверишь завтра.

```bash
F=/var/log/sysstat/sa$(date -d yesterday +%d)          # вчерашний файл
sar -q          -f $F -s 02:30:00 -e 03:40:00          # LA, очередь, blocked
sar -u ALL      -f $F -s 02:30:00 -e 03:40:00          # CPU с irq/soft/steal
sar -r          -f $F -s 02:30:00 -e 03:40:00          # память (kbavail, kbdirty)
sar -B          -f $F -s 02:30:00 -e 03:40:00          # paging: majflt/s, pgscand/s
sar -d -p       -f $F -s 02:30:00 -e 03:40:00          # диски: await, aqu-sz, %util
sar -n DEV      -f $F                                  # сеть по интерфейсам
sar -n SOCK     -f $F                                  # сокеты, tcp-tw (TIME_WAIT)
sar -n TCP,ETCP -f $F                                  # нужен -S XALL
sar -A          -f $F > /tmp/sar-all.txt               # вообще всё

sadf -d $F -- -q > q.csv        # CSV (разделитель «;») — в таблицу
sadf -g $F -- -q > q.svg        # SVG-график — открыть в браузере
```text
```text
# пример: sar -q за ночь — что-то началось в 03:00
02:50:01 AM   runq-sz  plist-sz   ldavg-1   ldavg-5  ldavg-15   blocked
03:00:01 AM         1       412      0.41      0.38      0.30         0
03:10:01 AM         2       431      9.87      6.12      2.74        11   ← blocked 11: D-state
03:20:01 AM         1       429     11.02      9.40      5.51        12
03:30:01 AM         0       414      1.12      4.33      4.60         0
```text
Дальше по цепочке: `sar -d -p` в то же окно (чей `await` вырос?) → что запускалось в 03:00:
`systemctl list-timers --all`, `grep CRON` в `journalctl --since "03:00" --until "03:30"`.

Ограничения sar:
- **10-минутные средние** сглаживают короткие всплески — 40 секунд полки превратятся в «7%».
- **Нет процессов**: sar скажет «диск был занят», но не «кем». Для истории по процессам —
  `atop` со своим журналом (`/var/log/atop/atop_ГГГГММДД`, тоже раз в 10 минут):
  `atop -r /var/log/atop/atop_20260926 -b 0250`, внутри `t`/`T` — следующий/предыдущий
  интервал.
- В инфраструктуре с мониторингом эту роль играют node_exporter + Prometheus; sar — страховка
  на хостах, где мониторинга нет или он сам лежал.

---

## 9. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Смотреть только `top` | Streetlight: диск, сеть, ошибки ядра не видны | «60 секунд» + USE по всем ресурсам |
| Верить первой строке `vmstat`/`iostat` | Это среднее с загрузки | Смотреть со второй строки |
| LA = загрузка CPU | В Linux LA включает D-state | LA / `nproc` + `vmstat` r против b + `%idle` |
| `%util` 100% = диск в полке | На NVMe/RAID запросы идут параллельно | `await`, `aqu-sz`, latency приложения |
| Высокий iowait = медленный диск | iowait — idle с незавершённым I/O | `iostat -x`: await и очередь |
| Низкий `free` = память кончилась | Page cache освобождается по требованию | `available`, `si`/`so`, PSI |
| Три sysctl за раз | Непонятно, что помогло или навредило | Одно обратимое изменение + замер |
| Минутные средние на всплесках | Короткие пики растворяются | Интервал 1 с, гистограммы, p99 |
| sar не включён или `-S DISK` | Нет истории / нет TCP в истории | `enable --now sysstat`, `SADC_OPTIONS="-S XALL"` |
| «IOPS выросли — стало лучше» | Throughput ≠ latency | Смотреть оба; решает latency для пользователя |
| Не записывать время | Не собрать таймлайн и доказательства | Журнал расследования с временем |
| Игнорировать `st` в VM | Шумный сосед выглядит как «медленный код» | `mpstat`/`vmstat` → `%steal`, тема 02 |

---

## 💼 Как это в DevOps

- «60 секунд» — первое, что делают после SSH на хост из алерта. Скрипт `60s.sh` кладут
  в runbook и в образ (или Ansible-ролью на все хосты), чтобы вывод прикладывался к инциденту.
- USE-таблица из раздела 2 — готовый список алертов для node_exporter: алертят на saturation
  и errors (очередь, своп, OOM, дропы, conntrack), а не на «CPU > 80%».
- Журнал расследования с временем — это будущий таймлайн постмортема; без него разбор
  превращается в «кажется, где-то в 14:10 я что-то поменял».
- sar с `-S XALL` раскатывают на все хосты базовой ролью: стоит копейки, а на вопрос
  «что было ночью, когда Prometheus тоже лежал» отвечает только он.
- На собеседовании вопрос «сервер тормозит, что делаешь?» проверяет именно метод: USE
  и порядок E → S → U звучат сильнее, чем перечисление команд.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Картина за минуту | `uptime; sudo dmesg -T \| tail; vmstat 1; mpstat -P ALL 1; pidstat 1; iostat -xz 1; free -m; sar -n DEV 1; sar -n TCP,ETCP 1; top` |
| Кто в R и D | `ps -eo state,pid,comm,wchan:32 \| awk '$1 ~ /^[RD]/'` |
| CPU saturation | `vmstat 1` (r > nproc), `pidstat 1` (`%wait`), `sar -q`, `/proc/pressure/cpu` |
| Одно ядро в полке | `mpstat -P ALL 1` |
| Память | `free -m` → `available`; `vmstat 1` → `si`/`so`; `sar -B` |
| Диск | `iostat -xz 1` → `r_await`/`w_await`, `aqu-sz`; `pidstat -d 1` |
| Сеть | `sar -n DEV 1`, `sar -n TCP,ETCP 1`, `sar -n EDEV 1` |
| Проверка чтения iostat | `aqu-sz ≈ (r/s·r_await + w/s·w_await) / 1000` |
| История за ночь | `sar -q -f /var/log/sysstat/saDD -s 02:30:00 -e 03:40:00` |
| История в CSV / SVG | `sadf -d saDD -- -q`, `sadf -g saDD -- -q > q.svg` |
| TCP в истории sar | `SADC_OPTIONS="-S XALL"` в `/etc/sysstat/sysstat` |
| История по процессам | `atop -r /var/log/atop/atop_ГГГГММДД -b 0250` |

---

## 🧠 Что запомнить

1. Метод важнее команд: USE по каждому ресурсу, порядок E → S → U, программные ресурсы — тоже ресурсы.
2. RED говорит, какому сервису плохо; USE — какой ресурс виноват; дальше — кто, почему, что, как.
3. «60 секунд»: uptime, dmesg, vmstat, mpstat, pidstat, iostat, free, sar DEV, sar TCP/ETCP, top.
4. Первая строка `vmstat`/`iostat` — среднее с загрузки, её пропускают.
5. Load average в Linux = R + D. Высокий LA при высоком `%idle` — D-state, а не CPU.
6. LA сравнивают с `nproc`: 20 на 32 ядрах — норма, 20 на 4 ядрах — очередь или D-state.
7. iowait — вид idle: высокий — повод смотреть диск, низкий — не алиби.
8. Saturation (очереди, `%wait`, `aqu-sz`, PSI) показывает боль раньше и честнее utilization.
9. Latency ≠ throughput; у колена очереди последние проценты загрузки самые дорогие; средние прячут хвосты.
10. Гипотеза с предсказанием → замер → одно обратимое изменение → замер тем же инструментом.
11. sar отвечает на «что было в 03:00»; для TCP в истории нужен `-S XALL`, для процессов — atop.

➡️ Дальше: [02_cpu_memory.md](/performance/02-cpu-memory) · задачи: 01_methodology_tasks.md


---

### Блок A. Теория


**A1.** Назови четыре анти-метода траблшутинга. Чем каждый плох?

<details><summary>Ответ</summary>

Streetlight — смотришь тем, что умеешь (`top`), и не видишь остальное. Random change —
крутишь параметры наугад: неясно, что помогло, можно сделать хуже. Blame someone else —
перекладываешь на «сеть/базу» без данных, задача ходит по кругу. Drunk man — меняешь всё подряд,
пока не пройдёт: долго, причина не найдена.

</details>

**A2.** Что означают U, S и E в USE-методе? Почему обходить их удобно в порядке E → S → U?

<details><summary>Ответ</summary>

U — насколько ресурс занят (доля времени/ёмкости). S — сколько работы стоит в очереди
(кто уже ждёт). E — ошибки ресурса. E первыми, потому что их дёшево проверить и они однозначны
(`dmesg`, счётчики ошибок); S вторыми — очередь означает, что latency уже страдает; U последней —
высокая загрузка без очереди не проблема.

</details>

**A3.** ⭐ Для CPU, памяти, диска и сети назови по одной команде на utilization, saturation и errors.

<details><summary>Ответ</summary>

CPU: U — `mpstat -P ALL 1`, S — `vmstat 1` (`r` > nproc) или `/proc/pressure/cpu`,
E — `dmesg` (MCE, throttling). Память: U — `free -m` (`available`), S — `vmstat` `si`/`so`,
`sar -B` `majflt/s`, E — `dmesg | grep -i "out of memory"`. Диск: U — `iostat -xz` `%util`
(не для NVMe), S — `aqu-sz`, `await`, E — `dmesg` `I/O error`. Сеть: U — `sar -n DEV 1`,
S — `ip -s link` dropped / `nstat` ListenOverflows / `retrans/s`, E — `sar -n EDEV 1`, `ethtool -S`.

</details>

**A4.** Что такое «программные ресурсы» в USE? Приведи четыре примера и признак исчерпания каждого.

<details><summary>Ответ</summary>

Ресурсы, которые выделяет ядро или приложение, а не железо. Файловые дескрипторы —
`Too many open files`, число fd упёрлось в `ulimit -n`. Conntrack — `nf_conntrack: table full`,
`count` ≈ `max`. Эфемерные порты — `cannot assign requested address`. Пулы потоков/соединений
к БД — ожидание пула, таймауты при низкой загрузке железа. Лимиты cgroups — `nr_throttled`,
`oom_kill` в `memory.events`.

</details>

**A5.** Чем RED отличается от USE и как они стыкуются в расследовании? Какие четыре вопроса
задаёт workload characterization?

<details><summary>Ответ</summary>

RED смотрит на сервис глазами пользователя (rate, errors, duration) и говорит, что
и где болит; USE смотрит на ресурсы и говорит почему. Стык: RED → какой эндпоинт/инстанс →
на этом хосте USE → насыщенный ресурс. Workload characterization: кто создаёт нагрузку, почему
(какой код/стек), что это за нагрузка (операции, размер, чтение/запись), как она меняется во времени.

</details>

**A6.** ⭐ Перечисли десять команд «60 секунд» по порядку и скажи, что даёт каждая.

<details><summary>Ответ</summary>

`uptime` — LA и тренд; `dmesg -T | tail` — ошибки ядра (OOM, conntrack, I/O, hung task);
`vmstat 1` — очередь CPU, D-state, своп, us/sy/wa/st; `mpstat -P ALL 1` — дисбаланс ядер, steal,
softirq; `pidstat 1` — кто ест CPU и кто ждёт (`%wait`); `iostat -xz 1` — латентность и очередь
дисков; `free -m` — `available`, кэш; `sar -n DEV 1` — трафик интерфейсов против линка;
`sar -n TCP,ETCP 1` — соединения в секунду и ретрансмиты; `top` — финальная сверка, D и зомби.

</details>

**A7.** Почему первую строку `vmstat 1` и `iostat -xz 1` пропускают?

<details><summary>Ответ</summary>

Первая строка — среднее с момента загрузки системы, а не текущее состояние. Она может
выглядеть страшно (ночной бэкап неделю назад) или слишком спокойно. Смотрят со второй строки.

</details>

**A8.** ⭐ Что входит в load average в Linux? Чем это отличается от классических Unix
и что из этого следует?

<details><summary>Ответ</summary>

Экспоненциально сглаженное среднее числа задач в состоянии R (выполняются или ждут CPU)
плюс D (uninterruptible: диск, NFS, блокировки ядра) за 1, 5 и 15 минут. В классических Unix —
только очередь к CPU. Следствие: в Linux LA — нагрузка на систему, а не на CPU; высокий LA при
высоком `%idle` — это D-state, и добавление ядер не поможет.

</details>

**A9.** Чем колонка `r` в `vmstat` и `%wait` в `pidstat` отличаются от `us` и `%CPU`?

<details><summary>Ответ</summary>

`us`/`%CPU` — сколько CPU реально потрачено. `r` — сколько задач готовы работать
(включая выполняющиеся); если `r` стабильно больше числа ядер — есть очередь. `%wait` в pidstat —
доля времени, когда задача была готова, но ждала CPU. Это saturation, а `us`/`%CPU` — utilization.

</details>

**A10.** Почему iowait называют «разновидностью idle»? Назови два практических следствия.

<details><summary>Ответ</summary>

CPU считается в iowait, только когда ему нечего выполнять и при этом есть незавершённый
блочный I/O. Следствия: на загруженном CPU iowait падает до нуля, даже если диск медленный
(«низкий iowait — не алиби»); высокий iowait может быть при нормальном диске на простаивающей
машине и не означает, что диск — узкое место; D-state на NFS/блокировках может не давать iowait вовсе.

</details>

**A11.** Чем latency отличается от throughput? Что происходит со временем ответа, когда
утилизация приближается к 100%? Приведи цифры.

<details><summary>Ответ</summary>

Throughput — операций в единицу времени (RPS, IOPS, МБ/с), latency — время одной операции.
По модели M/M/1 время ответа ≈ время обслуживания / (1 − U): при 50% — ×2, 80% — ×5, 90% — ×10,

</details>

**A12.** Что такое закон Литтла и как им проверить, что ты правильно читаешь `iostat -x`?

<details><summary>Ответ</summary>

`L = λ × W`: среднее число запросов в системе = поток × среднее время. Для диска:
`aqu-sz ≈ (r/s × r_await + w/s × w_await) / 1000`. Если сходится — ты правильно понимаешь
единицы (мс, операции в секунду) и смотришь на одну и ту же строку-интервал.

</details>

**A13.** Сформулируй пять правил научного метода в траблшутинге.

<details><summary>Ответ</summary>

Снять baseline до изменений; сформулировать гипотезу с проверяемым предсказанием;
менять одно и обратимо; мерить «после» тем же инструментом и окном; вести журнал с временем.

</details>

**A14.** Как на Ubuntu 24.04 собирается история sar? Почему `sar -n TCP -f saDD` может
ответить `Requested activities not available in file`?

<details><summary>Ответ</summary>

`sysstat-collect.timer` каждые 10 минут запускает `sa1`, тот пишет бинарный
`/var/log/sysstat/saDD`; раз в сутки `sa2` делает текстовый `sarDD`. Включается
`systemctl enable --now sysstat`. По умолчанию `SADC_OPTIONS="-S DISK"` — SNMP-метрики (TCP)
не собираются, поэтому в файле нет активности TCP и sar отвечает «not available». Нужен
`-S XALL` (или `-S SNMP`), и применится он только к новому суточному файлу.

</details>

**A15.** Какие ограничения у sar-истории и чем их закрыть?

<details><summary>Ответ</summary>

10-минутные средние прячут короткие всплески; нет данных по процессам; хранится
недолго (`HISTORY`, в Ubuntu 7 дней); без `-S XALL` нет TCP. Закрывают: интервал чаще
(override `OnCalendar` таймера), `atop` с журналом по процессам, node_exporter + Prometheus
для нормальной истории и алертов.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # VM 4 vCPU
```text
<details><summary>Ответ</summary>

LA падает: 9,1 за 15 минут → 0,95 за минуту. Проблема была и почти прошла; ты пришёл
к хвосту. Смотреть историю (sar, мониторинг) и `dmesg` — что было 10–15 минут назад.

</details>

```text:no-line-numbers
     $ uptime
```text
```text:no-line-numbers
      09:14:02 up 40 days,  2:11,  1 user,  load average: 0.95, 3.80, 9.10
```text
```text:no-line-numbers
B2.  # VM 4 vCPU, LA ≈ 15
```text
<details><summary>Ответ</summary>

`b` 14–15, `r` ≈ 1, `%idle` 88 на 4 vCPU: LA ≈ 15 создают задачи в D-state, CPU не при чём.
`wa` 9% не очень высокий — часть задач может ждать не блочный I/O (NFS, заморозка ФС).
Дальше: `ps -eo state,pid,comm,wchan:32 | awk '$1=="D"'`, `iostat -xz 1`, `dmesg` (hung task).

</details>

```text:no-line-numbers
     $ vmstat 1
```text
```text:no-line-numbers
      r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
```text
```text:no-line-numbers
      1 14      0 402112  81220 2210032    0    0     4     0  310  402  2  1 88  9  0  0
```text
```text:no-line-numbers
      0 15      0 402100  81220 2210040    0    0     0     0  298  388  1  1 89  9  0  0
```text
```text:no-line-numbers
B3.  $ mpstat -P ALL 1          # 4 vCPU
```text
<details><summary>Ответ</summary>

Среднее 25% скрывает, что CPU3 загружен на 100% user-кодом, а остальные простаивают:
однопоточное узкое место. Найти процесс (`pidstat 1`), дальше — `perf top -p` (тема 02).
Масштабировать ядрами бесполезно; нужен параллелизм или шардирование.

</details>

```text:no-line-numbers
     CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle
```text
```text:no-line-numbers
     all   25.10    0.00    0.20    0.00    0.00    0.00    0.00    0.00    0.00   74.70
```text
```text:no-line-numbers
       0    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00  100.00
```text
```text:no-line-numbers
       1    0.40    0.00    0.80    0.00    0.00    0.00    0.00    0.00    0.00   98.80
```text
```text:no-line-numbers
       2    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00  100.00
```text
```text:no-line-numbers
       3  100.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00    0.00
```text
```text:no-line-numbers
B4.  # «смотри, какой своп и I/O!» — прислал коллега, запустив vmstat один раз
```text
<details><summary>Ответ</summary>

`vmstat` без интервала печатает одну строку — средние с загрузки. Цифры `si`/`so`/`bi`
ничего не говорят о текущем моменте. Нужно `vmstat 1 5` и смотреть со второй строки.

</details>

```text:no-line-numbers
     $ vmstat
```text
```text:no-line-numbers
      r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
```text
```text:no-line-numbers
      0  0 204800 512000  90112 1802200  150  300  9000  4200  900 1400  8  3 85  4  0  0
```text
```text:no-line-numbers
B5.  # «память кончилась, надо добавить RAM»
```text
<details><summary>Ответ</summary>

Память не кончилась: `available` 3050 МиБ из 3915; маленький `free` — потому что
почти всё занято page cache (2985 МиБ), который ядро отдаст по требованию. Добавлять RAM
не нужно, свопа и давления нет.

</details>

```text:no-line-numbers
     $ free -m
```text
```text:no-line-numbers
                    total        used        free      shared  buff/cache   available
```text
```text:no-line-numbers
     Mem:            3915         810         120           6        2985        3050
```text
```text:no-line-numbers
     Swap:              0           0           0
```text
```text:no-line-numbers
B6.  # «NVMe в полке, срочно менять диск»
```text
<details><summary>Ответ</summary>

Не обязательно. NVMe обрабатывает много запросов параллельно; `%util` = доля времени,
когда был хоть один запрос, и упирается в 100% задолго до предела устройства. `r_await` 0,12 мс
при 42 000 IOPS и очереди ~5 — отличная латентность. Проверка Литтлом: 42 000 × 0,12 / 1000 ≈ 5,04 ✓.
Решает latency приложения, а не `%util`.

</details>

```text:no-line-numbers
     Device       r/s     rkB/s  r_await  w/s  wkB/s  w_await  aqu-sz  %util
```text
```text:no-line-numbers
     nvme0n1  42000.00 168000.00     0.12 0.00   0.00     0.00    5.04  100.00
```text
```text:no-line-numbers
B7.  # два сервера, sar -n TCP,ETCP 1
```text
<details><summary>Ответ</summary>

server-a: 0,5 / 12 000 ≈ 0,004% — норма. server-b: 810 / 9000 ≈ 9% ретрансмитов — потери
пакетов или перегрузка на пути/интерфейсе. Дальше: `ss -ti` (retrans по соединениям), `ip -s link`
(dropped), `nstat`, `tcpretrans-bpfcc` (тема 04).

</details>

```text:no-line-numbers
     server-a:  oseg/s 12000   retrans/s   0.50
```text
```text:no-line-numbers
     server-b:  oseg/s  9000   retrans/s 810.00
```text
```text:no-line-numbers
B8.  # VM 2 vCPU, «java ест всего 35%, CPU свободен»
```text
<details><summary>Ответ</summary>

`%wait` 61%: java 61% времени готова работать, но ждёт CPU в очереди, — CPU насыщен
другими задачами. «35%» — это utilization, а не свобода. Смотреть `vmstat` (`r`), кто ещё
в `pidstat`, не ограничен ли процесс cgroup-квотой (тема 06).

</details>

```text:no-line-numbers
     $ pidstat 1
```text
```text:no-line-numbers
        UID       PID    %usr %system  %guest   %wait    %CPU   CPU  Command
```text
```text:no-line-numbers
       1000      2190   33.00    2.00    0.00   61.00   35.00     1  java
```text
```text:no-line-numbers
B9.  # облачная VM, код не меняли, «всё стало медленнее»
```text
<details><summary>Ответ</summary>

35% времени CPU забирает гипервизор (steal): VM получает меньше процессора, чем думает.
Код тот же, а работает медленнее. Решение на стороне облака: другой тип инстанса (не burstable/
shared), выделенные хосты, миграция, проверка CPU credits у burstable-типов.

</details>

```text:no-line-numbers
     $ mpstat 1
```text
```text:no-line-numbers
     CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle
```text
```text:no-line-numbers
     all   48.00    0.00    6.00    0.00    0.00    1.00   35.00    0.00    0.00   10.00
```text
```text:no-line-numbers
B10.  # «ночью в 03:10 CPU был перегружен» — вывод коллеги по sar -q
```text
<details><summary>Ответ</summary>

Вывод неверный: `runq-sz` 1, а `blocked` 11 — LA 9,87 создан задачами в D-state, CPU
был свободен. Смотреть `sar -d -p` за то же окно (чей `await` вырос) и что запускалось в 03:00
(`systemctl list-timers --all`, `journalctl --since 03:00`).

</details>

```text:no-line-numbers
     03:00:01 AM   runq-sz  plist-sz   ldavg-1   ldavg-5  ldavg-15   blocked
```text
```text:no-line-numbers
     03:10:01 AM         1       431      9.87      6.12      2.74        11
```text
```text:no-line-numbers
B11.  # журнал «расследования»
```text
<details><summary>Ответ</summary>

Три изменения сразу, без гипотезы, baseline и замера «после»; рестарт приложения сам
по себе мог временно «помочь» (сброс утечки, кэшей, соединений). Непонятно, что сработало,
и есть риск вреда (`swappiness=1`, `tcp_tw_reuse=1` без нужды). Нужно откатить до известного
состояния и идти по одной гипотезе.

</details>

```text:no-line-numbers
     14:10  поставил net.core.somaxconn=65535, vm.swappiness=1, tcp_tw_reuse=1
```text
```text:no-line-numbers
     14:11  перезапустил приложение
```text
```text:no-line-numbers
     14:15  вроде стало лучше, закрываю
```text
```text:no-line-numbers
B12.  $ sar -n TCP,ETCP -f /var/log/sysstat/sa24
```text
<details><summary>Ответ</summary>

В файле нет TCP-активности: sadc собирает по умолчанию `-S DISK`, а TCP относится
к SNMP-группе. Включить `SADC_OPTIONS="-S XALL"` в `/etc/sysstat/sysstat`; сработает с нового
суточного файла.

</details>

```text:no-line-numbers
     Requested activities not available in file /var/log/sysstat/sa24
```text
---

### Блок C. Практика


### C1. 🔑 Baseline на спокойной VM
**1.** Создай `~/perf/60s.sh` из конспекта и запусти на ненагруженной VM.

<details><summary>Ответ</summary>

На спокойной 2 vCPU VM ориентиры: LA < 0,5; `r` 0–1, `b` 0; `%idle` > 95% на обоих ядрах;
`available` ≈ 3,4–3,6 ГиБ из 3,9; `w_await` на vda — единицы мс; `retrans/s` ≈ 0. Выводы вида
«CPU — ок: idle 97%, очереди нет».

</details>

**2.** Выпиши «нормальные» значения: LA, `r`, `b`, `cs`, `%idle` по ядрам, `available`,
   `await` на vda, `retrans/s`. Это твой baseline для всех следующих задач.

<details><summary>Ответ</summary>

,7 при `aqu-sz` 2,71). `wareq-sz` = `wkB/s` / `w/s` — средний размер записи в КиБ.

</details>

**3.** Сделай вывод за 1 предложение по каждому ресурсу: «CPU — ок, потому что …».

<details><summary>Ответ</summary>

LA растёт к ~4 (+фон) при `%idle` ≈ 100 и `%iowait` ≈ 0; в `vmstat` `b` = 4, `r` ≈ 0;
в `ps` четыре процесса `sh` в состоянии D, `wchan` вида `percpu_rwsem_wait` (ожидание
заморозки ФС). После `fsfreeze -u` записи сразу завершаются, фоновые задачи выходят, LA начинает
плавно падать (1-минутный быстрее 15-минутного). Вывод: высокий LA при простаивающем CPU и нулевом
iowait — D-state не из-за диска.

</details>

### C2. 🔑 CPU saturation своими глазами
**1.** `stress-ng --cpu 4 --timeout 180s &` на VM с 2 vCPU.

<details><summary>Ответ</summary>

На спокойной 2 vCPU VM ориентиры: LA < 0,5; `r` 0–1, `b` 0; `%idle` > 95% на обоих ядрах;
`available` ≈ 3,4–3,6 ГиБ из 3,9; `w_await` на vda — единицы мс; `retrans/s` ≈ 0. Выводы вида
«CPU — ок: idle 97%, очереди нет».

</details>

**2.** Через 60 секунд: `uptime`, `vmstat 1 5`, `pidstat 1 3`, `mpstat -P ALL 1 3`, `cat /proc/pressure/cpu`.

<details><summary>Ответ</summary>

,7 при `aqu-sz` 2,71). `wareq-sz` = `wkB/s` / `w/s` — средний размер записи в КиБ.

</details>

**3.** Какой LA ты ожидаешь через 3 минуты? Какие `r` и `%wait` у воркеров? Сверь с предсказанием.

<details><summary>Ответ</summary>

LA растёт к ~4 (+фон) при `%idle` ≈ 100 и `%iowait` ≈ 0; в `vmstat` `b` = 4, `r` ≈ 0;
в `ps` четыре процесса `sh` в состоянии D, `wchan` вида `percpu_rwsem_wait` (ожидание
заморозки ФС). После `fsfreeze -u` записи сразу завершаются, фоновые задачи выходят, LA начинает
плавно падать (1-минутный быстрее 15-минутного). Вывод: высокий LA при простаивающем CPU и нулевом
iowait — D-state не из-за диска.

</details>

### C3. 🔑 Высокий LA при простаивающем CPU
⚠️ Только на VM. Воспроизводим D-state без диска — замороженной файловой системой:
```text:no-line-numbers
mkdir -p ~/perf && truncate -s 512M ~/perf/fs.img && mkfs.ext4 -q ~/perf/fs.img
```text
```text:no-line-numbers
sudo mkdir -p /mnt/frz && sudo mount -o loop ~/perf/fs.img /mnt/frz
```text
```text:no-line-numbers
sudo fsfreeze -f /mnt/frz                       # все записи в ФС будут ждать
```text
```text:no-line-numbers
for i in 1 2 3 4; do sudo sh -c "echo x > /mnt/frz/f$i" & done
```text
**1.** Через 1–2 минуты: `uptime`, `vmstat 1 3`, `ps -eo state,pid,comm,wchan:32 | awk '$1=="D"'`,
   `mpstat 1 1`. Что с LA, `b`, `%idle` и `%iowait`?

<details><summary>Ответ</summary>

На спокойной 2 vCPU VM ориентиры: LA < 0,5; `r` 0–1, `b` 0; `%idle` > 95% на обоих ядрах;
`available` ≈ 3,4–3,6 ГиБ из 3,9; `w_await` на vda — единицы мс; `retrans/s` ≈ 0. Выводы вида
«CPU — ок: idle 97%, очереди нет».

</details>

**2.** `sudo fsfreeze -u /mnt/frz` — что произошло с процессами и LA?

<details><summary>Ответ</summary>

,7 при `aqu-sz` 2,71). `wareq-sz` = `wkB/s` / `w/s` — средний размер записи в КиБ.

</details>

**3.** Уборка: `sudo umount /mnt/frz`.

<details><summary>Ответ</summary>

LA растёт к ~4 (+фон) при `%idle` ≈ 100 и `%iowait` ≈ 0; в `vmstat` `b` = 4, `r` ≈ 0;
в `ps` четыре процесса `sh` в состоянии D, `wchan` вида `percpu_rwsem_wait` (ожидание
заморозки ФС). После `fsfreeze -u` записи сразу завершаются, фоновые задачи выходят, LA начинает
плавно падать (1-минутный быстрее 15-минутного). Вывод: высокий LA при простаивающем CPU и нулевом
iowait — D-state не из-за диска.

</details>

### C4. Одно ядро в полке
**1.** `stress-ng --cpu 1 --timeout 90s &`.

<details><summary>Ответ</summary>

На спокойной 2 vCPU VM ориентиры: LA < 0,5; `r` 0–1, `b` 0; `%idle` > 95% на обоих ядрах;
`available` ≈ 3,4–3,6 ГиБ из 3,9; `w_await` на vda — единицы мс; `retrans/s` ≈ 0. Выводы вида
«CPU — ок: idle 97%, очереди нет».

</details>

**2.** Сравни `mpstat 1 3` (только `all`) и `mpstat -P ALL 1 3`. Почему на 32-ядерном сервере
   такой процесс в `all` был бы почти не виден?

<details><summary>Ответ</summary>

,7 при `aqu-sz` 2,71). `wareq-sz` = `wkB/s` / `w/s` — средний размер записи в КиБ.

</details>

### C5. USE-таблица своей VM
Заполни таблицу реальными значениями с командами, которыми их получил: CPU, память,
диск (I/O и место), сеть и программные ресурсы — fd (`cat /proc/sys/fs/file-nr`),
conntrack (`nf_conntrack_count`/`max`), эфемерные порты (`ss -tan | wc -l` против
`ip_local_port_range`). Для каждой строки — вывод «норма / тревога».

### C6. 🔑 «Что было час назад» через sar
**1.** Проверь, что сбор идёт: `systemctl list-timers | grep sysstat`, `ls /var/log/sysstat/`.

<details><summary>Ответ</summary>

На спокойной 2 vCPU VM ориентиры: LA < 0,5; `r` 0–1, `b` 0; `%idle` > 95% на обоих ядрах;
`available` ≈ 3,4–3,6 ГиБ из 3,9; `w_await` на vda — единицы мс; `retrans/s` ≈ 0. Выводы вида
«CPU — ок: idle 97%, очереди нет».

</details>

**2.** Запиши время и запусти `stress-ng --cpu 4 --timeout 600s` (10 минут — чтобы попасть
   хотя бы в один 10-минутный интервал).

<details><summary>Ответ</summary>

,7 при `aqu-sz` 2,71). `wareq-sz` = `wkB/s` / `w/s` — средний размер записи в КиБ.

</details>

**3.** Через полчаса найди нагрузку в истории: `sar -q` и `sar -u` с `-s`/`-e` вокруг этого времени.

<details><summary>Ответ</summary>

LA растёт к ~4 (+фон) при `%idle` ≈ 100 и `%iowait` ≈ 0; в `vmstat` `b` = 4, `r` ≈ 0;
в `ps` четыре процесса `sh` в состоянии D, `wchan` вида `percpu_rwsem_wait` (ожидание
заморозки ФС). После `fsfreeze -u` записи сразу завершаются, фоновые задачи выходят, LA начинает
плавно падать (1-минутный быстрее 15-минутного). Вывод: высокий LA при простаивающем CPU и нулевом
iowait — D-state не из-за диска.

</details>

**4.** Выгрузи график: `sadf -g /var/log/sysstat/sa$(date +%d) -- -q > ~/perf/q.svg` и открой на хосте.

<details><summary>Ответ</summary>

В `all` — ~50% при 2 ядрах, а в `-P ALL` видно одно ядро 100% `%usr`. На 32 ядрах
в `all` это ~3%: среднее по ядрам прячет однопоточную полку.

</details>

### C7. Журнал расследования
Оформи задачу C3 как журнал из раздела 7 конспекта: время, симптом, гипотеза с предсказанием,
замер, вывод, одно изменение, замер «после». Минимум две гипотезы, одна должна быть опровергнута.

### C8. Проверка чтения iostat законом Литтла
**1.** `stress-ng --hdd 1 --hdd-bytes 512M --timeout 60s &`.

<details><summary>Ответ</summary>

На спокойной 2 vCPU VM ориентиры: LA < 0,5; `r` 0–1, `b` 0; `%idle` > 95% на обоих ядрах;
`available` ≈ 3,4–3,6 ГиБ из 3,9; `w_await` на vda — единицы мс; `retrans/s` ≈ 0. Выводы вида
«CPU — ок: idle 97%, очереди нет».

</details>

**2.** `iostat -xz 1 5`: для vda посчитай `(r/s·r_await + w/s·w_await)/1000` и сравни с `aqu-sz`.

<details><summary>Ответ</summary>

,7 при `aqu-sz` 2,71). `wareq-sz` = `wkB/s` / `w/s` — средний размер записи в КиБ.

</details>

**3.** Проверь, что `wareq-sz ≈ wkB/s / w/s`.

<details><summary>Ответ</summary>

LA растёт к ~4 (+фон) при `%idle` ≈ 100 и `%iowait` ≈ 0; в `vmstat` `b` = 4, `r` ≈ 0;
в `ps` четыре процесса `sh` в состоянии D, `wchan` вида `percpu_rwsem_wait` (ожидание
заморозки ФС). После `fsfreeze -u` записи сразу завершаются, фоновые задачи выходят, LA начинает
плавно падать (1-минутный быстрее 15-минутного). Вывод: высокий LA при простаивающем CPU и нулевом
iowait — D-state не из-за диска.

</details>

### C9. Загадка «что грузит VM»
Попроси кого-нибудь (или скрипт) запустить случайную нагрузку и очистить экран:
```text:no-line-numbers
case $((RANDOM % 3)) in
```text
```text:no-line-numbers
  0) stress-ng --cpu 2 --timeout 180s ;;
```text
```text:no-line-numbers
  1) stress-ng --hdd 2 --hdd-bytes 1G --timeout 180s ;;
```text
```text:no-line-numbers
  2) stress-ng --vm 1 --vm-bytes 85% --vm-keep --timeout 180s ;;
```text
```text:no-line-numbers
esac >/dev/null 2>&1 &
```text
```text:no-line-numbers
clear
```text
За 2 минуты определи ресурс только «60 секундами» и назови метрику-доказательство.

---

### Блок D. Инциденты


**D1.** Алерт «LA > 30» на 16-ядерном сервере. Пользователи не жалуются, `%idle` — 70%.
Что происходит и что делаешь?

<details><summary>Ответ</summary>

LA 30 на 16 ядрах при `%idle` 70% — не CPU (на CPU-очередь было бы `idle` ≈ 0). Вероятно,
D-state: `vmstat` → `b`, `ps` по `D` с `wchan`, `iostat -x`, `dmesg` (hung task, NFS). Если
пользователи не страдают (RED в норме) — это кандидат на смену алерта: алертить на saturation
по ресурсу и на SLO, а не на голый LA.

</details>

**D2.** Инженер поменял три sysctl и перезапустил сервис — latency упала. Через сутки
снова выросла. Что было не так с методом и что делать теперь?

<details><summary>Ответ</summary>

Не было гипотезы, baseline и одного изменения; рестарт сам сбросил симптомы (утечка,
кэш, соединения) и маскировал причину. Сейчас: вернуть sysctl к исходным (или хотя бы
зафиксировать текущие), снять baseline в момент деградации, пройти USE, проверить гипотезу
«утечка/накопление» — растущий RSS, fd, соединения, очереди со временем после рестарта.

</details>

**D3.** Каждую ночь в 03:10 приходит алерт «API p99 > 1 с» и сам гаснет к 03:40.
Мониторинга хоста нет, есть только SSH. Как расследовать?

<details><summary>Ответ</summary>

Проверить/включить sysstat (`-S XALL`) и поставить atop с журналом; на следующую ночь —
`sar -q/-u/-d -p/-r/-n DEV` за 02:50–03:50: какой ресурс и когда насыщается. Найти, что
стартует в 03:00: `systemctl list-timers --all`, `crontab -l`/`/etc/cron.d`, журнал за окно.
Можно поставить `at`/таймер на 03:05, который запустит `60s.sh` и сохранит вывод. Гипотеза
(бэкап/батч) → подтверждение по совпадению времени и метрик → фикс (ionice, перенос, реплика).

</details>

**D4.** Коллега: «CPU 40%, значит сервер не перегружен, это код тормозит». При этом p99
плохой. Что проверить, прежде чем соглашаться?

<details><summary>Ответ</summary>

Среднее «40%» может прятать: одно ядро в полке (`mpstat -P ALL`); очередь к CPU
(`vmstat` r, `pidstat` %wait, PSI); steal в VM; throttling контейнера по CPU-квоте при низком
среднем (`cpu.stat` → `nr_throttled`, тема 06); и latency не из CPU — диск, сеть, блокировки.
Соглашаться «это код» можно после проверки saturation, а не utilization.

</details>

**D5.** Облачная VM: код и нагрузка не менялись, всё стало медленнее на 30%.
`mpstat` показывает `%steal` 25%.

<details><summary>Ответ</summary>

Steal 25% — VM недополучает CPU от гипервизора: шумный сосед, перепродажа хоста,
исчерпанные CPU credits у burstable-инстанса. Доказательство — `mpstat`/`sar -u` `%steal`
во времени. Лечение: другой тип/размер инстанса, выделенный хост, пересоздание VM (переедет
на другой хост), для burstable — unlimited-режим или смена класса.

</details>

**D6.** «Сервер тормозит»: USE по CPU, памяти, диску и сети чистый. Куда смотреть дальше?

<details><summary>Ответ</summary>

Программные ресурсы: fd против лимитов, conntrack, эфемерные порты, пулы потоков
и соединений, лимиты cgroups (throttling, memory.high). Затем зависимости: DNS, база,
внешние API (время в трейсах, `strace -T` на процессе). И сам процесс: блокировки, GC
(py-spy/jstack), `strace -c`/`-p` — на чём он ждёт (тема 05).

</details>

**D7.** Дежурный на «тормоза» перезагрузил сервер — прошло. Что потеряно и что надо было
сделать за две минуты до ребута?

<details><summary>Ответ</summary>

Потеряно всё состояние: процессы в D и их стеки, утечки, очереди, соединения,
`dmesg`-буфер (если нет persistent journal), шанс понять причину — значит, повторится.
За две минуты: `60s.sh` в файл, `sudo dmesg -T > file`, `ps auxf`, `ss -s`, `top -b -n1`,
для зависшего процесса — `cat /proc/PID/stack` и `py-spy dump`/`jstack`. Потом ребут, если
нужно быстро восстановить сервис.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое USE-метод?

<details><summary>Ответ</summary>

Метод проверки каждого ресурса (CPU, память, диск, сеть, программные — fd, пулы, лимиты)
   по трём вопросам: utilization — насколько занят, saturation — есть ли очередь, errors — есть
   ли ошибки. Обхожу в порядке ошибки → очередь → загрузка: так быстро находится узкое место
   и так же быстро исключаются здоровые ресурсы.

</details>

**2.** Расскажи чек-лист «Linux performance analysis in 60 seconds».

<details><summary>Ответ</summary>

Десять команд Брендана Грегга: `uptime` (LA и тренд), `dmesg -T | tail` (OOM, I/O, conntrack),
   `vmstat 1` (r, b, своп, us/sy/wa/st), `mpstat -P ALL 1` (дисбаланс ядер, steal), `pidstat 1`
   (кто ест и кто ждёт CPU), `iostat -xz 1` (await, aqu-sz), `free -m` (available), `sar -n DEV 1`
   (трафик против линка), `sar -n TCP,ETCP 1` (соединения/с, ретрансмиты), `top`.

</details>

**3.** Что такое load average и как его интерпретировать?

<details><summary>Ответ</summary>

Сглаженное среднее числа задач в состояниях R и D за 1/5/15 минут. Сравниваю с числом ядер
   и смотрю тренд; чтобы понять, CPU это или I/O, смотрю `vmstat` (r против b) и `%idle`.

</details>

**4.** Load average высокий, а CPU простаивает. Что это может быть?

<details><summary>Ответ</summary>

Задачи в D-state: ждут диск, NFS, заморозку ФС, блокировки ядра. Проверяю `vmstat` b,
   `ps` по `D` с `wchan`, `iostat -x`, `dmesg` на hung task, для конкретного процесса —
   `/proc/PID/stack`.

</details>

**5.** Что такое iowait и почему ему нельзя слепо верить?

<details><summary>Ответ</summary>

Доля времени, когда CPU простаивал при незавершённом блочном I/O. Это разновидность idle:
   на загруженном CPU iowait исчезает при медленном диске, а на пустой машине бывает высоким
   без проблем. Про диск честнее говорят `await` и `aqu-sz`.

</details>

**6.** Чем latency отличается от throughput?

<details><summary>Ответ</summary>

Throughput — сколько операций в секунду, latency — сколько длится одна. У колена очереди
   throughput растёт слабо, а latency — резко (×10 при 90% загрузки по M/M/1). Пользователь
   чувствует latency.

</details>

**7.** Как узнать, что было на сервере ночью, если мониторинга нет?

<details><summary>Ответ</summary>

sar из sysstat пишет историю раз в 10 минут: `sar -q/-u/-r/-d/-n DEV -f /var/log/sysstat/saDD
   -s … -e …`. Для TCP в истории нужен `-S XALL`, для процессов — atop с журналом. Плюс
   `journalctl` за окно и `systemctl list-timers` — что запускалось.

</details>

**8.** Сервер тормозит. Твои первые шаги?

<details><summary>Ответ</summary>

Масштаб и влияние (RED/SLO: все или один хост), «что изменилось», затем на хосте «60 секунд»
   и USE по ресурсам в порядке errors → saturation → utilization, включая программные ресурсы.
   Дальше — drill-down инструментом под найденный ресурс; всё с журналом времени.

</details>

**9.** Как доказать причину проблемы, а не угадать её?

<details><summary>Ответ</summary>

Гипотеза с проверяемым предсказанием, baseline, замер, одно обратимое изменение и замер
   «после» тем же инструментом. Причина доказана, когда её можно воспроизвести и показать цифру
   до и после фикса.

</details>

**10.** Что такое saturation и почему она важнее utilization?

<details><summary>Ответ</summary>

Saturation — работа, которая ждёт в очереди к ресурсу (run queue, `aqu-sz`, accept queue,
    throttling, PSI). Очередь означает, что кто-то уже ждёт — latency страдает, тогда как высокая
    utilization без очереди — просто эффективная загрузка.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Называю анти-методы и объясняю, чем метод лучше случайных команд
- [ ] ⭐ Для каждого ресурса знаю команды на U, S и E и обхожу в порядке E → S → U
- [ ] Помню программные ресурсы: fd, conntrack, порты, пулы, лимиты cgroups
- [ ] ⭐ Прогоняю «60 секунд» по памяти и объясняю важные колонки каждой команды
- [ ] Не верю первой строке `vmstat`/`iostat`
- [ ] ⭐ Объясняю LA = R + D и отличаю CPU-очередь от D-state по `vmstat` и `%idle`
- [ ] Понимаю, почему iowait — вид idle и почему он не алиби для диска
- [ ] Объясняю latency vs throughput, колено очереди и проверяю iostat законом Литтла
- [ ] Веду журнал расследования: гипотеза → предсказание → замер → одно изменение
- [ ] Нахожу в sar-истории, что было ночью, и выгружаю график через `sadf -g`
- [ ] Baseline своей VM записан
