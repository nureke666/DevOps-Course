---
title: "07. eBPF, bcc и bpftrace: вопросы прямо к ядру"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 07. Опирается на"
---

# 07. eBPF, bcc и bpftrace: вопросы прямо к ядру

> Блок → Deep Linux Troubleshooting & Performance → тема 07. Опирается на
> [../Linux/12_kernel.md](/linux/12-kernel) (syscalls, strace, sysctl),
> [02_cpu_memory.md](/performance/02-cpu-memory) (perf, flame graphs), [03_disk_io.md](/performance/03-disk-io),
> [04_network_deep.md](/performance/04-network-deep) и [05_strace_hung_processes.md](/performance/05-strace-hung-processes):
> здесь те же вопросы, но с ответом из ядра и почти без оверхеда. Классический BPF ты уже
> видел в фильтрах tcpdump — [../Network/10_tcpdump_wireshark.md](/network/10-tcpdump-wireshark).
>
> **После темы ты умеешь:** объяснить, что такое eBPF и почему он безопасен для прода;
> выбрать bcc-инструмент под вопрос (кто запускает процессы, какие файлы не находятся,
> какая латентность диска и run queue, куда ходят TCP-соединения, кого убил OOM); написать
> bpftrace one-liner с агрегацией; проверить требования (ядро, BTF, права); ориентироваться
> в eBPF-экосистеме DevOps (Cilium, Falco, Tetragon, Parca, Pixie).

---

## 🗺️ Карта темы

```text
 USER SPACE                                              KERNEL
 ┌──────────────────────────┐   bpf() syscall   ┌──────────────────────────────────────────┐
 │ bcc (Python, *-bpfcc)     │ ────────────────► │ verifier: безопасно? конечно? в границах?│
 │ bpftrace (one-liners)     │   байткод eBPF    │        │ да                               │
 │ libbpf-tools, Cilium,     │                   │        ▼                                  │
 │ Falco, Tetragon, Parca…   │                   │ JIT → машинный код                        │
 └────────────▲─────────────┘                   │        │ подключается к событию:           │
              │ читает агрегаты                  │        ▼                                  │
              │ (гистограммы, счётчики)          │ kprobe · tracepoint · fentry · uprobe ·   │
              │                                  │ USDT · perf event · XDP/tc · LSM          │
              └──────────── maps ◄───────────────│ программа пишет в maps (hash, array,      │
                                                 │ per-CPU, ring buffer)                     │
                                                 └──────────────────────────────────────────┘
```text
---

## 1. Что такое eBPF — с точки зрения пользователя

**eBPF** — маленькие программы, которые ядро выполняет по событию: вызов функции ядра,
syscall, отправка пакета, сэмпл профайлера. Программа считает, фильтрует и складывает
результат в **maps** (структуры данных в ядре), а user space забирает готовые агрегаты.

| | strace (тема 05) | perf (тема 02) | eBPF (bcc/bpftrace) |
|---|------------------|----------------|----------------------|
| Механизм | ptrace: остановка процесса на каждом syscall | Сэмплирование и счётчики PMU | Программа в ядре на событии |
| Оверхед | Большой: процесс замедляется в разы, до десятков раз | Малый при 99 Гц | Малый, если агрегировать в ядре |
| Что видит | Syscalls одного процесса | Где CPU (on-CPU) | Почти что угодно: syscalls, I/O, сеть, планировщик, off-CPU, функции приложений |
| Данные | Каждое событие в текст | Сэмплы в perf.data | Гистограммы и счётчики прямо из ядра |

**Почему это безопасно для прода:**
- **Verifier** проверяет программу до загрузки: нет бесконечных циклов (только ограниченные),
  нет обращений к памяти мимо разрешённого, ограничен размер и сложность. Не прошла — не загрузится.
- Программа не может уронить ядро, как сломанный модуль: она работает в песочнице и
  вызывает только разрешённые helper-функции.
- **JIT** превращает байткод в машинный код — поэтому быстро.

> ⭐ Главная идея производительности: «посчитай в ядре, отдай итог». Гистограмма латентности
> диска за 10 секунд — это несколько сотен байт в user space, а не миллион строк, как у strace.

---

## 2. К чему можно подключиться

| Тип | Что это | Стабильность | Пример |
|-----|---------|--------------|--------|
| **tracepoint** | Статические точки, заложенные в ядро | ⭐ Стабильный ABI — предпочтительно | `tracepoint:syscalls:sys_enter_openat`, `sched:sched_process_exec`, `block:block_rq_issue`, `tcp:tcp_retransmit_skb` |
| **kprobe / kretprobe** | Вход/выход любой функции ядра | Нестабильно: функции меняются между версиями | `kprobe:tcp_connect`, `kprobe:oom_kill_process` |
| **fentry / fexit** (`kfunc`) | Как kprobe, но через BTF: дешевле, с типами аргументов | Нужен BTF (ядро 5.5+) | `kfunc:tcp_reset` |
| **uprobe / uretprobe** | Функции в user space: библиотеки, бинарники | Зависит от версии программы | `uprobe:/bin/bash:readline`, `uretprobe:libc:malloc` |
| **USDT** | Статические точки внутри приложений | Стабильно, если собрано с поддержкой | PostgreSQL, JVM, Python, собранные с `--enable-dtrace` |
| **perf event** | Таймер или счётчик PMU | Стабильно | `profile:hz:99` (профилирование), `hardware:cache-misses` |
| **XDP / tc** | Обработка пакетов в сетевом стеке | Для сетевых продуктов | Cilium, балансировщики, DDoS-фильтры |
| **LSM** | Хуки безопасности | Для security-инструментов | Tetragon, KRSI |

```bash
sudo bpftrace -l 'tracepoint:syscalls:sys_enter_open*'   # поиск точек
sudo bpftrace -l 'kprobe:tcp_*' | wc -l                   # сколько функций TCP можно трассировать
sudo bpftrace -lv tracepoint:syscalls:sys_exit_read       # аргументы tracepoint (ret и др.)
```text
---

## 3. Требования и права

```bash
uname -r                                  # ядро: минимум 4.9 для большинства bcc-утилит, лучше 5.8+
ls -l /sys/kernel/btf/vmlinux             # ⭐ BTF: типы ядра → CO-RE и bpftrace без заголовков
sysctl kernel.unprivileged_bpf_disabled   # Ubuntu: 2 → без привилегий eBPF не загрузить
sudo bpftool prog list | head             # какие eBPF-программы УЖЕ загружены (systemd, Cilium…)
sudo bpftool map list | head
```text
| Что | Зачем |
|-----|-------|
| **root** или `CAP_BPF` + `CAP_PERFMON` (ядро 5.8+) | Загрузка программ и трассировка; для сетевых хуков ещё `CAP_NET_ADMIN`. До 5.8 — только `CAP_SYS_ADMIN` |
| **BTF** (`CONFIG_DEBUG_INFO_BTF`, в Ubuntu с 20.10) | Типы структур ядра без заголовков; основа CO-RE и `kfunc` |
| **Заголовки ядра** для bcc | Python-bcc компилирует программу на лету (LLVM); нужен `linux-headers-$(uname -r)` или модуль `kheaders` (`CONFIG_IKHEADERS`) |
| **CO-RE** (Compile Once — Run Everywhere) | libbpf-программа собрана один раз и подстраивается под ядро по BTF: не нужны ни clang, ни заголовки на сервере |

| Семейство | Где взять | Особенность |
|-----------|-----------|-------------|
| **bcc** (Python) | `bpfcc-tools` — в Ubuntu все утилиты с суффиксом `-bpfcc` | Самый полный набор, но тяжёлый: LLVM, заголовки, компиляция при старте |
| **libbpf-tools** | Пакет `libbpf-tools` (Ubuntu 24.04) | Те же утилиты на CO-RE: маленькие бинарники без LLVM; пока подмножество bcc |
| **bpftrace** | Пакет `bpftrace`; готовые скрипты в `/usr/sbin/*.bt` | Язык one-liners в стиле awk; для ad-hoc вопросов |

> В контейнере eBPF-инструменту нужны привилегии (`--privileged` или нужные capabilities)
> и доступ к `/sys/kernel/debug`/`/sys/kernel/tracing`: программы грузятся в **общее ядро
> хоста** и видят всю ноду, а не только свой контейнер.

---

## 4. bcc: готовые инструменты под типовые вопросы

```text
                        ┌───────────── приложения ─────────────┐
   execsnoop (кто стартует)   opensnoop (какие файлы)   profile / offcputime (где CPU / где ждёт)
                        ├──────── syscalls · VFS ──────────────┤
       syscount  statsnoop        cachestat (page cache)   memleak · oomkill (память)
                        ├──── сеть ─────────┬──── блочный I/O ─┤
   tcpconnect tcpaccept tcplife         biolatency biosnoop biotop
   tcpretrans tcpdrop gethostlatency    ext4slower / xfsslower
                        ├──────── планировщик ─────────────────┤
                 runqlat  runqlen  cpudist  offcputime
                        └──────────────────────────────────────┘
```text
| Вопрос | Инструмент (Ubuntu) | Запуск |
|--------|---------------------|--------|
| Кто плодит короткоживущие процессы (их не видно в top)? | `execsnoop-bpfcc` | `sudo execsnoop-bpfcc -T` (`-x` — и неудачные exec) |
| Какие файлы процесс открывает и какие не находит? | `opensnoop-bpfcc` | `sudo opensnoop-bpfcc -x -p PID` (`-x` — только ошибки) |
| Распределение латентности диска | `biolatency-bpfcc` | `sudo biolatency-bpfcc -D 10 1` (`-D` по дискам, `-m` в мс, `-Q` с очередью ОС) |
| Каждый I/O: кто, куда, сколько ждал | `biosnoop-bpfcc` | `sudo biosnoop-bpfcc -Q` |
| Куда процессы подключаются по TCP | `tcpconnect-bpfcc` | `sudo tcpconnect-bpfcc -t -p PID` (`-d` — с DNS-запросом) |
| Жизнь соединений: длительность и объём | `tcplife-bpfcc` | `sudo tcplife-bpfcc -T` |
| Ретрансмиты: с кем и в каком состоянии | `tcpretrans-bpfcc` | `sudo tcpretrans-bpfcc -l` (`-l` — и tail loss probe, `-c` — счётчики) |
| Сколько задачи ждут CPU в очереди | `runqlat-bpfcc` | `sudo runqlat-bpfcc -m 10 1` (`-P` — по PID) |
| Хватает ли page cache | `cachestat-bpfcc` | `sudo cachestat-bpfcc 1` |
| Кого и когда убил OOM | `oomkill-bpfcc` | `sudo oomkill-bpfcc` |
| CPU-профиль для flame graph | `profile-bpfcc` | `sudo profile-bpfcc -F 99 -f 30 > out.folded` |
| Где процесс спит (off-CPU) | `offcputime-bpfcc` | `sudo offcputime-bpfcc -f -p PID 30 > off.folded` |
| Утечка памяти в C/C++ | `memleak-bpfcc` | `sudo memleak-bpfcc -p PID 30` |

### Как это выглядит

```text
# пример вывода: sudo execsnoop-bpfcc -T — cron-скрипт каждую секунду форкает curl и grep
TIME     PCOMM            PID     PPID    RET ARGS
14:02:11 check.sh         8120    8119      0 /opt/check.sh
14:02:11 curl             8121    8120      0 /usr/bin/curl -s http://localhost:8080/health
14:02:11 grep             8122    8120      0 /usr/bin/grep -q ok
```text
Классика: `top` показывает 30% `%sys` и ни одного тяжёлого процесса, потому что процессы
живут миллисекунды. execsnoop видит каждый.

```text
# пример вывода: sudo opensnoop-bpfcc -x -p 2210 — сервис не видит конфиг
PID    COMM               FD ERR PATH
2210   app                -1   2 /etc/app/config.yaml
2210   app                -1   2 /etc/app/conf.d/local.yaml
```text
`ERR 2` = `ENOENT` (нет файла), `13` = `EACCES` (нет прав). То же, что `strace -e trace=openat -Z`,
но без остановки процесса и по всей системе, если убрать `-p`.

```text
# пример вывода: sudo biolatency-bpfcc -D 10 1 — диск vdb с периодическими «залипаниями»
disk = vdb
     usecs               : count     distribution
       128 -> 255        : 1840     |****************************************|
       256 -> 511        : 1402     |******************************          |
       512 -> 1023       : 210      |****                                    |
      1024 -> 2047       : 12       |                                        |
    262144 -> 524287     : 38       |                                        |   ← хвост 0,26–0,5 с
```text
Среднее `await` в `iostat` было бы «~5 мс» и не насторожило бы. Гистограмма показывает
бимодальность: большинство I/O быстрые, но 38 запросов ждали полсекунды ([03_disk_io.md](/performance/03-disk-io)).

```text
# пример вывода: sudo runqlat-bpfcc -m 10 1 — CPU-насыщенная VM 2 vCPU
     msecs               : count     distribution
         0 -> 1          : 18210    |****************************************|
         2 -> 3          : 2104     |****                                    |
         4 -> 7          : 1630     |***                                     |
         8 -> 15         : 941      |**                                      |
        16 -> 31         : 212      |                                        |
```text
Задачи ждут ядро до 16–31 мс — прямая цена CPU saturation в латентности запросов.

```text
# пример вывода: sudo tcplife-bpfcc — короткие соединения к БД без пула
PID   COMM       LADDR           LPORT RADDR           RPORT TX_KB RX_KB MS
3301  gunicorn   10.0.0.5        51022 10.0.0.9        5432      0     1 3.12
3301  gunicorn   10.0.0.5        51024 10.0.0.9        5432      0     1 2.98
```text
Сотни соединений по 3 мс — нет пула соединений: растут TIME_WAIT и нагрузка на БД ([04_network_deep.md](/performance/04-network-deep)).

```text
# пример вывода: sudo tcpretrans-bpfcc
TIME     PID     IP LADDR:LPORT          T> RADDR:RPORT          STATE
14:05:02 0       4  10.0.0.5:44310       R> 10.0.0.9:5432        ESTABLISHED
```text
`PID 0` — нормально: ретрансмит по таймеру выполняет ядро в softirq, а не процесс.

```text
# пример вывода: sudo oomkill-bpfcc
Tracing OOM kills... Ctrl-C to stop.
14:10:33 Triggered by PID 4312 ("python3"), OOM kill of PID 4312 ("python3"), 1015806 pages, loadavg: 1.02 0.61 0.30 3/211 4390
```text
`Triggered by` — кто попросил память, `OOM kill of` — жертва; `pages` — объём памяти системы
(totalpages), а не размер жертвы. Подробности — OOM-отчёт в `dmesg` ([02_cpu_memory.md](/performance/02-cpu-memory)).

---

## 5. bpftrace: свой вопрос одной строкой

```text
 probe                                /filter/             { action }
 tracepoint:syscalls:sys_enter_read   /pid == 2210/        { @[comm] = count(); }
 tracepoint:syscalls:sys_exit_read    /args.ret > 0/       { @h = hist(args.ret); }
 kretprobe:vfs_read                   /comm == "nginx"/    { @bytes = hist(retval); }
 profile:hz:99                        /pid == 2210/        { @[ustack] = count(); }
```text
| Встроенное | Значение |
|------------|----------|
| `pid`, `tid`, `comm`, `uid` | Процесс/поток, имя, пользователь |
| `nsecs` | Время в наносекундах — для латентности (разность enter/exit) |
| `kstack`, `ustack` | Стек ядра / пользовательский стек |
| `args` | Аргументы tracepoint: `args.filename`, `args.ret` (в bpftrace 0.20 — через точку) |
| `arg0…argN`, `retval` | Аргументы kprobe/uprobe, возвращаемое значение kretprobe/uretprobe |
| `@имя[ключ]` | Map; при выходе (Ctrl-C) bpftrace печатает все maps сам |
| `count()`, `sum()`, `avg()`, `hist()`, `lhist()` | Агрегации прямо в ядре |

### One-liners, которые стоит знать наизусть

```bash
# 1. Кто делает больше всего syscalls
sudo bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); }'

# 2. Какие файлы открываются (и кем)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { printf("%-16s %s\n", comm, str(args.filename)); }'

# 3. Гистограмма размеров успешных read() по процессам
sudo bpftrace -e 'tracepoint:syscalls:sys_exit_read /args.ret > 0/ { @[comm] = hist(args.ret); }'

# 4. Латентность read() в микросекундах (enter/exit через map по tid)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_read { @start[tid] = nsecs; }
  tracepoint:syscalls:sys_exit_read /@start[tid]/ {
    @us = hist((nsecs - @start[tid]) / 1000); delete(@start[tid]); }'

# 5. TCP connect по процессам (функция ядра) и через syscall connect()
sudo bpftrace -e 'kprobe:tcp_connect { @[comm] = count(); }'
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_connect { @[comm] = count(); }'

# 6. Новые процессы: кто что запускает
sudo bpftrace -e 'tracepoint:sched:sched_process_exec { printf("%d %s\n", pid, str(args.filename)); }'

# 7. CPU-профиль процесса по стекам (сырьё для flame graph)
sudo bpftrace -e 'profile:hz:99 /comm == "python3"/ { @[ustack] = count(); }'

# 8. Размеры блочных I/O по процессам
sudo bpftrace -e 'tracepoint:block:block_rq_issue { @[comm] = hist(args.bytes); }'

# 9. Ретрансмиты по порту назначения
sudo bpftrace -e 'tracepoint:tcp:tcp_retransmit_skb { @[args.dport] = count(); }'

# 10. Печать раз в секунду вместо итога в конце
sudo bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); }
  interval:s:1 { print(@); clear(@); }'
```text
```text
# пример вывода one-liner 1 (Ctrl-C через 5 секунд)
@[sshd]: 212
@[systemd-journal]: 1804
@[python3]: 948211              ← 190 тысяч syscalls в секунду у одного процесса

# пример вывода one-liner 3
@[python3]:
[1]                    6 |                                                    |
[2, 4)                 0 |                                                    |
[4, 8)             41203 |@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@|   ← читает по 4–7 байт!
[4K, 8K)              12 |                                                    |
```text
Второй вывод — диагноз «читаем файл/сокет крошечными порциями без буферизации»: огромное
число syscalls и высокий `%sys` при малом объёме данных.

```bash
sudo bpftrace -c 'curl -s example.com' -e 'tracepoint:syscalls:sys_enter_connect /pid == cpid/ { @ = count(); }'
sudo bpftrace -p 2210 -e 'usdt:… { … }'           # -p: USDT/uprobe конкретного процесса
ls /usr/sbin/*.bt                                 # готовые скрипты: biolatency.bt, tcpretrans.bt, oomkill.bt…
sudo /usr/sbin/tcpconnect.bt
```text
`cpid` — PID команды, запущенной через `-c`.

---

## 6. Оверхед и правила применения на проде

| Фактор | Влияние |
|--------|---------|
| Частота события | `raw_syscalls:sys_enter` на нагруженном сервере — миллионы событий в секунду: даже дешёвая программа заметна |
| Агрегация vs `printf` на каждое событие | `count()`/`hist()` в ядре дёшевы; `printf` на миллион событий переполняет буфер и грузит CPU (bpftrace сообщит о потерянных событиях) |
| kprobe на горячей функции ядра | Дороже tracepoint; `kfunc`/fentry дешевле kprobe |
| uprobe | Каждый вызов = переход в ядро: `uprobe:libc:malloc` на аллокационно-тяжёлом сервисе может замедлить его заметно |
| Сборка bcc-программы | Секунды CPU и сотни МБ памяти на старте (LLVM) — на маленькой ноде это ощутимо; libbpf-tools легче |

Правила:
1. Сначала простые инструменты (темы 01–05), eBPF — когда они не отвечают на вопрос.
2. Ограничивай по времени (`duration`, `interval` + `exit()`), по процессу (`-p`, `/pid == …/`).
3. Агрегируй в ядре, печатай итог.
4. Незнакомый one-liner — сначала на стенде: kprobe-скрипты ломаются при смене версии ядра.

---

## 7. eBPF-экосистема в DevOps

Ты будешь встречать eBPF чаще в продуктах, чем в one-liners:

| Проект | Что делает | Где встретишь |
|--------|-----------|---------------|
| **Cilium** | CNI для Kubernetes на eBPF: сеть, NetworkPolicy, замена kube-proxy, балансировка; Hubble — наблюдаемость потоков | Managed Kubernetes (многие облака предлагают Cilium как dataplane), проект CNCF graduated |
| **Tetragon** | Security observability и enforcement: какие процессы запускаются, какие файлы и сети трогают, с блокировкой по политике | Подпроект Cilium, runtime security в кластерах |
| **Falco** | Обнаружение подозрительного поведения по правилам («shell в контейнере», «чтение /etc/shadow») | CNCF graduated; драйвер на eBPF (modern eBPF probe) |
| **Pixie** | Автоматическая телеметрия Kubernetes без правок кода: HTTP/gRPC/SQL-запросы, flame graphs | CNCF sandbox |
| **Parca** | Continuous profiling: eBPF-агент на ноде постоянно снимает CPU-профили всех процессов | Сравнение flame graphs между релизами |
| **Grafana Beyla / OBI** | Автоинструментация: RED-метрики и трейсы HTTP/gRPC из ядра, без SDK в приложении | Beyla в 2025 г. передана в OpenTelemetry как OpenTelemetry eBPF Instrumentation (OBI) — проверь актуальное название |
| **Inspektor Gadget** | bcc-подобные «гаджеты» с контекстом Kubernetes (под, namespace) через `kubectl gadget` | CNCF sandbox, ad-hoc дебаг в кластере |

```bash
sudo bpftool prog list | awk '{print $2, $4}' | sort | uniq -c | sort -rn | head
# на ноде с Cilium увидишь десятки программ типа sched_cls / xdp; systemd сам грузит cgroup_skb/cgroup_device
```text
> 💡 Для дебага в Kubernetes: eBPF-инструменты запускают на **ноде** (`kubectl debug node/…
> --profile=sysadmin` или привилегированный DaemonSet, тема 06), а фильтруют по cgroup
> контейнера — у многих bcc-утилит есть `--cgroupmap`, у bpftrace — встроенный `cgroup`.

---

## 8. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Искать `biolatency` в Ubuntu | Команда называется `biolatency-bpfcc` | `ls /usr/sbin/*-bpfcc` |
| `args->filename` из старых статей | В bpftrace 0.20+ синтаксис `args.filename` | Смотри `bpftrace -lv` и версию |
| kprobe-скрипт из блога «не видит функцию» | Функцию переименовали/заинлайнили в твоём ядре | tracepoint или `kfunc`, проверка `bpftrace -l 'kprobe:…'` |
| bcc падает с ошибкой про заголовки | Нет `linux-headers-$(uname -r)` | Поставить заголовки или взять libbpf-tools/bpftrace |
| `printf` на каждый syscall на проде | Потерянные события, нагрузка | Агрегации, фильтр по `pid`/`comm`, ограничение времени |
| eBPF в непривилегированном контейнере | `Operation not permitted` | root/`CAP_BPF`+`CAP_PERFMON`, запуск на ноде |
| Думать, что контейнерный eBPF видит только контейнер | Ядро общее — видна вся нода | Фильтровать по cgroup/PID; учитывать доступ к данным соседей |
| Сразу eBPF вместо `iostat`/`ss`/`dmesg` | Долго и сложно там, где хватило бы минуты | Метод USE сначала, eBPF — для «почему» |
| `PID 0` в tcpretrans считать ошибкой | Ретрансмит по таймеру — работа ядра | Смотреть адреса и порты |

---

## 💼 Как это в DevOps

- На дежурстве: `execsnoop` за 10 секунд находит cron/healthcheck, который форкает сотни
  процессов; `opensnoop -x` — сервис, ищущий конфиг не там; `biolatency` — хвост латентности
  диска, который усредняет `iostat`.
- «Сеть тормозит» проверяют `tcpretrans` и `tcplife`: видно, с какими хостами ретрансмиты
  и где соединения живут миллисекунды без пула.
- В кластерах eBPF уже работает у тебя под ногами: Cilium как CNI, Falco/Tetragon как runtime
  security, Parca/Pyroscope как continuous profiling, Beyla/OBI как автоинструментация.
- Для security-команды eBPF — инструмент аудита («кто запустил shell в поде»), для SRE —
  наблюдаемость без правок кода, для платформы — сеть без iptables.
- Требования (ядро, BTF, привилегии) — часть выбора образа нод: старое ядро без BTF отрезает
  половину инструментов.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить поддержку | `uname -r`, `ls /sys/kernel/btf/vmlinux`, `sudo bpftool prog list` |
| Короткоживущие процессы | `sudo execsnoop-bpfcc -T` |
| Файлы, которые не открылись | `sudo opensnoop-bpfcc -x [-p PID]` |
| Латентность диска гистограммой | `sudo biolatency-bpfcc -D 10 1` |
| Каждый I/O | `sudo biosnoop-bpfcc -Q` |
| TCP-подключения / жизнь соединений | `sudo tcpconnect-bpfcc -t`, `sudo tcplife-bpfcc -T` |
| Ретрансмиты | `sudo tcpretrans-bpfcc -l` |
| Ожидание в run queue | `sudo runqlat-bpfcc -m 10 1` |
| Page cache hit ratio | `sudo cachestat-bpfcc 1` |
| OOM-убийства | `sudo oomkill-bpfcc` |
| CPU / off-CPU flame graph | `sudo profile-bpfcc -F 99 -f 30`, `sudo offcputime-bpfcc -f -p PID 30` |
| Найти точку трассировки | `sudo bpftrace -l 'tracepoint:syscalls:*open*'`, `-lv` — аргументы |
| Syscalls по процессам | `bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); }'` |
| Гистограмма read() | `bpftrace -e 'tracepoint:syscalls:sys_exit_read /args.ret > 0/ { @[comm] = hist(args.ret); }'` |
| TCP connect | `bpftrace -e 'kprobe:tcp_connect { @[comm] = count(); }'` |
| Готовые bpftrace-скрипты | `ls /usr/sbin/*.bt` |

---

## 🧠 Что запомнить

1. eBPF — программы в ядре по событию; verifier гарантирует безопасность, JIT — скорость.
2. Сила eBPF — агрегация в ядре: гистограммы и счётчики вместо потока событий.
3. Предпочитай tracepoints (стабильны); kprobes мощнее, но ломаются между версиями ядра.
4. Требования: свежее ядро (5.8+ комфортно), BTF для CO-RE и bpftrace, root или `CAP_BPF` + `CAP_PERFMON`.
5. В Ubuntu bcc-утилиты называются `*-bpfcc`; bpftrace-скрипты лежат в `/usr/sbin/*.bt`.
6. Базовый набор: execsnoop, opensnoop, biolatency, biosnoop, tcpconnect, tcplife, tcpretrans,
   runqlat, cachestat, oomkill, profile, offcputime.
7. bpftrace: `probe /filter/ { action }`, `@map[key] = count()/hist()`, `args.field`, `nsecs` для латентности.
8. Оверхед зависит от частоты события: фильтруй, агрегируй, ограничивай по времени.
9. eBPF-инструмент в контейнере видит всё общее ядро ноды.
10. В DevOps eBPF чаще встречается в продуктах: Cilium, Tetragon, Falco, Pixie, Parca, Beyla/OBI.

➡️ Дальше: [08_practice_labs.md](/softskills/08-practice-labs) · задачи: 07_ebpf_bpftrace_tasks.md


---

### Блок A. Теория


**A1.** Что такое eBPF своими словами? Что такое maps и почему главный принцип — «посчитай
в ядре, отдай итог»?

<details><summary>Ответ</summary>

Небольшие программы, которые ядро выполняет по событию (вызов функции ядра, syscall,
пакет, тик профайлера). Maps — структуры данных в ядре (hash, array, per-CPU, ring buffer),
куда программа пишет результат, а user space читает. Агрегация в ядре (счётчик, гистограмма)
отдаёт в user space сотни байт вместо миллионов событий — отсюда низкий оверхед.

</details>

**A2.** ⭐ Почему eBPF-программу можно запускать на проде, а самописный модуль ядра — страшно?
Что делают verifier и JIT?

<details><summary>Ответ</summary>

Verifier до загрузки проверяет программу: циклы только ограниченные, доступ к памяти
только разрешённый, ограничены размер и сложность, вызывать можно лишь разрешённые helper-функции;
не прошла — не загрузится. Модуль ядра — произвольный код с полными правами: ошибка роняет
ядро. JIT компилирует проверенный байткод в машинный код, поэтому программа быстрая.

</details>

**A3.** Сравни strace, perf и eBPF: механизм, оверхед, что каждый видит.

<details><summary>Ответ</summary>

strace — ptrace, останавливает процесс на каждом syscall: большой оверхед, видит syscalls
одного процесса. perf — сэмплирование и счётчики PMU: малый оверхед при 99 Гц, отвечает «где
CPU». eBPF — программа в ядре на событии: малый оверхед при агрегации, видит syscalls, I/O,
сеть, планировщик, off-CPU, функции приложений, сразу по всей системе.

</details>

**A4.** ⭐ Чем отличаются tracepoint, kprobe, fentry (`kfunc`), uprobe и USDT? Что из этого
стабильно между версиями ядра и приложения?

<details><summary>Ответ</summary>

Tracepoint — статические точки в ядре, стабильный интерфейс (предпочтительно). Kprobe/
kretprobe — вход/выход любой функции ядра: мощно, но функции меняются и инлайнятся между версиями.
Fentry/fexit (`kfunc`) — как kprobe, но через BTF: дешевле и с типами, нужен BTF (5.5+). Uprobe —
функции в user space (библиотеки, бинарники): зависит от версии программы. USDT — статические
точки внутри приложения: стабильно, если приложение собрано с поддержкой. Стабильны tracepoint
и USDT.

</details>

**A5.** Какие требования у eBPF-инструментов: версия ядра, BTF, права? Что изменилось в ядре 5.8?
Что значит `kernel.unprivileged_bpf_disabled = 2`?

<details><summary>Ответ</summary>

Для большинства bcc-утилит — ядро 4.9+, комфортно 5.8+. BTF (`/sys/kernel/btf/vmlinux`,
в Ubuntu с 20.10) нужен для CO-RE, `kfunc` и bpftrace без заголовков. Права: root или, с ядра 5.8,
`CAP_BPF` + `CAP_PERFMON` (для сетевых хуков ещё `CAP_NET_ADMIN`); до 5.8 — `CAP_SYS_ADMIN`.
`unprivileged_bpf_disabled=2` — непривилегированным пользователям `bpf()` запрещён, но root может
переключить значение на 0 или 1; значение 1 — тоже запрет, и его уже не снять без перезагрузки.

</details>

**A6.** Чем bcc отличается от libbpf-tools и bpftrace? Что такое CO-RE и зачем bcc заголовки ядра?

<details><summary>Ответ</summary>

bcc — Python-фронтенд: программа на C компилируется LLVM на лету, поэтому нужны заголовки
ядра (`linux-headers-$(uname -r)` или модуль `kheaders`), старт тяжёлый; набор утилит самый полный.
libbpf-tools — те же утилиты, собранные заранее по CO-RE: маленькие бинарники без LLVM и заголовков,
пока подмножество. bpftrace — язык one-liners для ad-hoc вопросов. CO-RE: программа собрана один
раз и при загрузке подстраивается под структуры конкретного ядра по BTF.

</details>

**A7.** ⭐ Какой bcc-инструмент возьмёшь, чтобы найти: короткоживущие процессы; файлы, которые
не открываются; хвост латентности диска; ожидание CPU в очереди; куда процесс подключается
по TCP; ретрансмиты; кого убил OOM; где процесс спит?

<details><summary>Ответ</summary>

`execsnoop-bpfcc`; `opensnoop-bpfcc -x`; `biolatency-bpfcc` (и `biosnoop-bpfcc` по каждому
I/O); `runqlat-bpfcc`; `tcpconnect-bpfcc`; `tcpretrans-bpfcc`; `oomkill-bpfcc`; `offcputime-bpfcc`.

</details>

**A8.** Почему `execsnoop` находит нагрузку, которую не видно в `top`?

<details><summary>Ответ</summary>

`top` делает снимки раз в несколько секунд: процесс, живущий миллисекунды, между снимками
рождается и умирает. execsnoop ловит каждый `exec()` через трассировку ядра — видно всех,
кого запускают, с родителем и аргументами.

</details>

**A9.** Что показывает `biolatency`, чего не покажет `iostat -x`?

<details><summary>Ответ</summary>

iostat даёт среднее `await` за интервал, которое прячет хвост. biolatency — гистограмму
латентности каждого I/O: видно бимодальность и редкие запросы по сотням миллисекунд при
«нормальном» среднем.

</details>

**A10.** Почему в выводе `tcpretrans-bpfcc` у многих строк `PID 0`?

<details><summary>Ответ</summary>

Ретрансмит по таймеру RTO выполняет ядро в softirq/таймере, вне контекста процесса,
поэтому текущий PID — 0. Смотреть надо на адреса, порты и состояние соединения.

</details>

**A11.** ⭐ Объясни синтаксис bpftrace: probe, filter, action, maps, агрегации. Когда используют
`args.…`, а когда `arg0` и `retval`?

<details><summary>Ответ</summary>

`probe /filter/ { action }`: probe — событие (`tracepoint:…`, `kprobe:…`, `profile:hz:99`,
`interval:s:1`), filter — условие (`/pid == 2210/`), action — код. `@name[key]` — map, агрегации
`count()`, `sum()`, `avg()`, `hist()`, `lhist()` считаются в ядре; при выходе maps печатаются
сами. Встроенные: `pid`, `tid`, `comm`, `nsecs`, `kstack`, `ustack`. `args.field` — аргументы
tracepoint (и `kfunc`) по именам; `arg0…argN` — аргументы kprobe/uprobe по позиции; `retval` —
возвращаемое значение в kretprobe/uretprobe.

</details>

**A12.** Как в bpftrace измерить латентность syscall? Зачем для этого map по `tid`?

<details><summary>Ответ</summary>

На входе в syscall сохранить время `@start[tid] = nsecs`, на выходе посчитать
`nsecs - @start[tid]`, положить в `hist()` и удалить ключ. Ключ — `tid`, потому что один поток
в каждый момент выполняет один syscall, а разные потоки процесса — параллельно; с ключом `pid`
времена потоков перепутались бы.

</details>

**A13.** От чего зависит оверхед eBPF? Сформулируй четыре правила применения на проде.

<details><summary>Ответ</summary>

От частоты события (миллионы в секунду — заметно даже для дешёвой программы), от
`printf` на событие против агрегации, от типа точки (kprobe дороже tracepoint и `kfunc`,
uprobe — переход в ядро на каждый вызов), от компиляции bcc на старте. Правила: сначала простые
инструменты; ограничивать по времени и процессу; агрегировать в ядре; незнакомое — сначала на стенде.

</details>

**A14.** Что видит eBPF-инструмент, запущенный в контейнере? Какие права ему нужны и как
отфильтровать события одного контейнера?

<details><summary>Ответ</summary>

Ядро общее, поэтому программа видит события всей ноды, а не только своего контейнера.
Нужны привилегии (`--privileged` или `CAP_BPF`, `CAP_PERFMON`, иногда `CAP_SYS_ADMIN`/`CAP_NET_ADMIN`)
и доступ к `/sys/kernel/tracing`, `/sys/kernel/debug`. Фильтровать по PID (`-p`, `/pid == …/`)
или по cgroup контейнера: `--cgroupmap` у многих bcc-утилит, встроенная переменная `cgroup`
в bpftrace.

</details>

**A15.** Одной фразой: Cilium, Tetragon, Falco, Pixie, Parca, Beyla/OBI, Inspektor Gadget.

<details><summary>Ответ</summary>

Cilium — CNI на eBPF: сеть, NetworkPolicy, замена kube-proxy, Hubble для потоков.
Tetragon — наблюдаемость и блокировка на уровне процессов, файлов и сети по политикам.
Falco — обнаружение подозрительного поведения по правилам. Pixie — автоматическая телеметрия
Kubernetes без правок кода. Parca — continuous profiling всех процессов ноды. Beyla/OBI —
RED-метрики и трейсы HTTP/gRPC из ядра без SDK. Inspektor Gadget — bcc-подобные гаджеты
с контекстом подов через `kubectl gadget`.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ sudo biolatency -D 10 1
```text
<details><summary>Ответ</summary>

В Ubuntu утилиты bcc называются с суффиксом: `sudo biolatency-bpfcc -D 10 1`
(`ls /usr/sbin/*-bpfcc`). Либо bpftrace-версия `/usr/sbin/biolatency.bt`.

</details>

```text:no-line-numbers
     sudo: biolatency: command not found
```text
```text:no-line-numbers
B2.  # one-liner из статьи 2019 года, bpftrace 0.20
```text
<details><summary>Ответ</summary>

Старый синтаксис `args->filename`: в bpftrace 0.20 правильно `args.filename`; стрелка
устарела и в зависимости от версии даёт предупреждение или ошибку. Переписать:
`printf("%s\n", str(args.filename))`, аргументы смотреть через `bpftrace -lv`.

</details>

```text:no-line-numbers
     sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { printf("%s\n", str(args->filename)); }'
```text
```text:no-line-numbers
B3.  # top: %sys 28%, тяжёлых процессов нет
```text
<details><summary>Ответ</summary>

Healthcheck-скрипт, который кто-то (PPID 1 — systemd-таймер или цикл) запускает ~100 раз
в секунду, и каждый запуск форкает curl и jq. Процессы живут миллисекунды, `top` их не видит,
а fork/exec дают `%sys`. Найти источник (юнит/таймер, `systemctl status`), сделать проверку
реже или встроить её в сам сервис.

</details>

```text:no-line-numbers
     $ sudo execsnoop-bpfcc -T
```text
```text:no-line-numbers
     TIME     PCOMM            PID     PPID    RET ARGS
```text
```text:no-line-numbers
     10:01:00 healthcheck.sh   9120    1       0   /opt/healthcheck.sh
```text
```text:no-line-numbers
     10:01:00 curl             9121    9120    0   /usr/bin/curl -sf http://127.0.0.1:8080/health
```text
```text:no-line-numbers
     10:01:00 jq               9122    9120    0   /usr/bin/jq -e .status
```text
```text:no-line-numbers
     10:01:00 healthcheck.sh   9123    1       0   /opt/healthcheck.sh
```text
```text:no-line-numbers
     …                                             (≈ 300 строк в секунду)
```text
```text:no-line-numbers
B4.  $ sudo opensnoop-bpfcc -x -n app
```text
<details><summary>Ответ</summary>

`ERR 13` = `EACCES`: у процесса `app` нет прав на базу и её WAL (владелец/права каталога,
AppArmor). Проверить `ls -l /var/lib/app`, пользователя сервиса (`ps -o user= -p 4410`),
`namei -l /var/lib/app/data.db`, `journalctl -k | grep -i apparmor`.

</details>

```text:no-line-numbers
     PID    COMM               FD ERR PATH
```text
```text:no-line-numbers
     4410   app                -1  13 /var/lib/app/data.db
```text
```text:no-line-numbers
     4410   app                -1  13 /var/lib/app/data.db-wal
```text
```text:no-line-numbers
B5.  # iostat: vdb r_await 4,8 мс — «диск в норме»; пользователи жалуются на редкие зависания
```text
<details><summary>Ответ</summary>

Бимодальность: большинство I/O быстрые, но 70 запросов за 30 с ждали 0,26–1 с — эти
редкие зависания пользователи и видят; среднее 4,8 мс их прячет. Дальше: `biosnoop-bpfcc -Q`
(какие процессы, какие операции, чтение или запись/flush), время — совпадает ли с writeback,
бэкапом, compaction; облачный диск — не упирается ли в burst/лимит IOPS.

</details>

```text:no-line-numbers
     $ sudo biolatency-bpfcc -D -m 30 1
```text
```text:no-line-numbers
     disk = vdb
```text
```text:no-line-numbers
          msecs               : count     distribution
```text
```text:no-line-numbers
              0 -> 1          : 9120     |****************************************|
```text
```text:no-line-numbers
              2 -> 3          : 1210     |*****                                   |
```text
```text:no-line-numbers
              4 -> 7          : 402      |*                                       |
```text
```text:no-line-numbers
            256 -> 511        : 61       |                                        |
```text
```text:no-line-numbers
            512 -> 1023       : 9        |                                        |
```text
```text:no-line-numbers
B6.  # 4 vCPU, mpstat all: 60% usr — «CPU не узкое место»
```text
<details><summary>Ответ</summary>

Среднее 60% прячет saturation: заметная доля пробуждений ждёт CPU 8–127 мс, то есть
на пиках задачи стоят в run queue десятки миллисекунд — это прямо добавляется к latency.
Смотреть `runqlat -P` (кто страдает), `mpstat -P ALL` (дисбаланс ядер), throttling контейнеров;
лечить — больше ядер/подов, меньше потоков, убрать соседей.

</details>

```text:no-line-numbers
     $ sudo runqlat-bpfcc -m 10 1
```text
```text:no-line-numbers
          msecs               : count     distribution
```text
```text:no-line-numbers
              0 -> 1          : 40210    |****************************************|
```text
```text:no-line-numbers
              2 -> 3          : 6120     |******                                  |
```text
```text:no-line-numbers
              4 -> 7          : 3302     |***                                     |
```text
```text:no-line-numbers
              8 -> 15         : 1840     |*                                       |
```text
```text:no-line-numbers
             16 -> 31         : 920      |                                        |
```text
```text:no-line-numbers
             32 -> 63         : 310      |                                        |
```text
```text:no-line-numbers
             64 -> 127        : 42       |                                        |
```text
```text:no-line-numbers
B7.  $ sudo tcplife-bpfcc | head -4
```text
<details><summary>Ответ</summary>

Каждый запрос php-fpm открывает новое соединение к Redis на ~2 мс и закрывает: 4000
соединений в секунду — TIME_WAIT, эфемерные порты, нагрузка на Redis и лишние RTT на хендшейк.
Нужны persistent-соединения (`pconnect`) или пул.

</details>

```text:no-line-numbers
     PID   COMM       LADDR           LPORT RADDR           RPORT TX_KB RX_KB MS
```text
```text:no-line-numbers
     2210  php-fpm    10.0.0.5        40112 10.0.0.12       6379      0     0 1.85
```text
```text:no-line-numbers
     2211  php-fpm    10.0.0.5        40114 10.0.0.12       6379      0     0 1.91
```text
```text:no-line-numbers
     2212  php-fpm    10.0.0.5        40116 10.0.0.12       6379      0     0 1.77
```text
```text:no-line-numbers
     # …и так 4000 строк в секунду
```text
```text:no-line-numbers
B8.  $ sudo tcpconnect-bpfcc
```text
<details><summary>Ответ</summary>

bcc не нашёл заголовков ядра: нет ни модуля `kheaders`, ни каталога `build`.
Поставить `linux-headers-$(uname -r)` или использовать libbpf-tools/bpftrace, которым хватает BTF.

</details>

```text:no-line-numbers
     modprobe: FATAL: Module kheaders not found in directory /lib/modules/6.8.0-45-generic
```text
```text:no-line-numbers
     chdir(/lib/modules/6.8.0-45-generic/build): No such file or directory
```text
```text:no-line-numbers
B9.  # тот же скрипт работал на старой ноде, на новой — предупреждение и нет событий
```text
<details><summary>Ответ</summary>

Функции с таким именем в новом ядре нет (переименована, заинлайнена или помечена
`notrace`) — kprobe-скрипты ломаются между версиями. Найти замену через
`bpftrace -l 'kprobe:tcp_v4*'`, а лучше перейти на tracepoint (`tcp:*`, `sock:*`) или `kfunc`.

</details>

```text:no-line-numbers
     $ sudo bpftrace -e 'kprobe:tcp_v4_do_rcv_old { @ = count(); }'
```text
```text:no-line-numbers
     WARNING: tcp_v4_do_rcv_old is not traceable (either non-existing, inlined, or marked as "notrace"); attaching to it will likely fail
```text
```text:no-line-numbers
B10.  # внутри обычного (непривилегированного) контейнера
```text
<details><summary>Ответ</summary>

Загрузка eBPF требует привилегий: в непривилегированном контейнере нет `CAP_BPF`/
`CAP_PERFMON` (и Ubuntu запрещает непривилегированный `bpf()`). Запускать на ноде
(`kubectl debug node/… --profile=sysadmin`, привилегированный DaemonSet) или дать контейнеру
нужные capabilities осознанно.

</details>

```text:no-line-numbers
     $ bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); }'
```text
```text:no-line-numbers
     ERROR: … Operation not permitted
```text
```text:no-line-numbers
B11.  # нагруженный прод, 200 тыс. syscalls в секунду
```text
<details><summary>Ответ</summary>

`printf` на каждое из сотен тысяч событий в секунду: буфер переполнился (потеряно 1,8 млн
событий), CPU уходит на вывод, сервис замедляется. Нужно агрегировать в ядре
(`@[comm, args.id] = count();`), фильтровать по процессу и ограничить время (`interval:s:10 { exit(); }`).

</details>

```text:no-line-numbers
     $ sudo bpftrace -e 'tracepoint:raw_syscalls:sys_enter { printf("%s %d\n", comm, args.id); }'
```text
```text:no-line-numbers
     …
```text
```text:no-line-numbers
     Lost 1834112 events
```text
```text:no-line-numbers
B12.  $ sudo oomkill-bpfcc
```text
<details><summary>Ответ</summary>

Память попросил nginx (PID 991), а убит java (PID 4312) — у него максимальный badness.
Инициатор OOM не обязательно виновник. `pages` — общий объём памяти системы (totalpages), не
размер жертвы. Детали — в OOM-отчёте `dmesg` (таблица задач, `constraint`).

</details>

```text:no-line-numbers
     03:12:44 Triggered by PID 991 ("nginx"), OOM kill of PID 4312 ("java"), 1015806 pages, loadavg: 7.80 3.10 1.20 9/412 5021
```text
---

### Блок C. Практика


### C1. 🔑 Проверка стенда
**1.** `uname -r`, `ls -l /sys/kernel/btf/vmlinux`, `sysctl kernel.unprivileged_bpf_disabled`.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** `sudo bpftool prog list | head -20` и подсчёт по типам:
   `sudo bpftool prog list | grep -oE '^[0-9]+: [a-z_]+' | awk '{print $2}' | sort | uniq -c`.
   Кто уже загрузил программы (systemd, Docker)?

<details><summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

**3.** Убедись, что без sudo eBPF не работает: `bpftrace -e 'BEGIN { exit(); }'`.

<details><summary>Ответ</summary>

) Латентность read у fio — сотни мкс–мс (прямой I/O ждёт диск), у прочих процессов — единицы мкс.

</details>

### C2. 🔑 Невидимый «форкальщик»
**1.** Запусти скрытую нагрузку: `while true; do /usr/bin/date >/dev/null; /usr/bin/id >/dev/null; done &`.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** Посмотри `top` 10 секунд: видно ли виновника? Сколько `%sys`?

<details><summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

**3.** `sudo execsnoop-bpfcc -T` — кто запускается и кто родитель. Посчитай exec в секунду:
   `sudo timeout 5 execsnoop-bpfcc | wc -l`. Убери нагрузку (`kill %1`).

<details><summary>Ответ</summary>

) Латентность read у fio — сотни мкс–мс (прямой I/O ждёт диск), у прочих процессов — единицы мкс.

</details>

### C3. 🔑 Файлы, которых нет
**1.** `while true; do python3 -c "open('/etc/app/config.yaml')" 2>/dev/null; sleep 1; done &`.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** `sudo opensnoop-bpfcc -x` — найди ошибку и её код.

<details><summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

**3.** То же через strace: `strace -f -e trace=openat -Z python3 -c "open('/etc/app/config.yaml')"`.
   Чем подходы отличаются для работающего сервиса?

<details><summary>Ответ</summary>

) Латентность read у fio — сотни мкс–мс (прямой I/O ждёт диск), у прочих процессов — единицы мкс.

</details>

### C4. 🔑 Хвост латентности диска
```text:no-line-numbers
mkdir -p ~/perf/t07
```text
```text:no-line-numbers
fio --name=rr --filename=/var/tmp/fio.dat --size=512M --rw=randread --bs=4k --direct=1 \
```text
```text:no-line-numbers
    --ioengine=libaio --iodepth=16 --runtime=40 --time_based --group_reporting &
```text
Во время теста: `sudo biolatency-bpfcc -D 10 1`, `sudo biosnoop-bpfcc -Q | head -20`, `iostat -xz 1 3`.
Сравни среднее `r_await` из iostat с гистограммой и перцентилями `clat` из вывода fio.

### C5. Цена CPU saturation в миллисекундах
**1.** `sudo runqlat-bpfcc -m 10 1` на спокойной VM.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** `stress-ng --cpu 4 --timeout 60s &` и снова `runqlat`. Как сдвинулась гистограмма?

<details><summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

**3.** Добавь `-P` — у каких PID хвост длиннее?

<details><summary>Ответ</summary>

) Латентность read у fio — сотни мкс–мс (прямой I/O ждёт диск), у прочих процессов — единицы мкс.

</details>

### C6. Жизнь TCP-соединений
**1.** `python3 -m http.server 8000 &` и `for i in $(seq 200); do curl -s -o /dev/null localhost:8000/; done`.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** Параллельно `sudo tcplife-bpfcc -T` и `sudo tcpconnect-bpfcc -t`. Сколько живёт соединение,
   сколько байт передано? Как бы ты объяснил разработчику, зачем пул соединений?

<details><summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

### C7. 🔑 bpftrace one-liners на живой нагрузке
**1.** Кто делает больше всего syscalls: запусти `dd if=/dev/zero of=/dev/null bs=1 count=2000000 &`
   и one-liner 1 из конспекта на 5 секунд.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** Гистограмма read(): `dd if=/etc/services of=/dev/null bs=1 &` (в цикле) и one-liner 3 —
   что видно у `dd`?

<details><summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

**3.** Латентность read() (one-liner 4) во время C4: какие значения у fio?

<details><summary>Ответ</summary>

) Латентность read у fio — сотни мкс–мс (прямой I/O ждёт диск), у прочих процессов — единицы мкс.

</details>

**4.** One-liner 10 (печать раз в секунду) — останови через 5 секунд.

<details><summary>Ответ</summary>

) Раз в секунду печатается и очищается таблица счётчиков.

</details>

### C8. Flame graph из eBPF
Повтори профилирование лабы 1 ([08_practice_labs.md](/softskills/08-practice-labs)) через
`sudo profile-bpfcc -F 99 -f -p PID 30 > bpf.folded` и `~/FlameGraph/flamegraph.pl bpf.folded > bpf.svg`.
Затем снимите off-CPU профиль того же процесса: `sudo offcputime-bpfcc -f -p PID 30 > off.folded`.
Чем отличаются картинки?

### C9. OOM глазами eBPF
**1.** В одном окне `sudo oomkill-bpfcc`.

<details><summary>Ответ</summary>

Ядро 6.x (у GA-ядра Ubuntu 24.04 — 6.8), файл BTF на месте, `unprivileged_bpf_disabled = 2`. В списке
программ — `cgroup_device` и `cgroup_skb` от systemd, после установки Docker — ещё программы
для cgroups контейнеров. Без sudo bpftrace завершается ошибкой прав.

</details>

**2.** В другом: `sudo systemd-run --unit=oomt -p MemoryMax=100M python3 -c "x=[b'x'*(10<&lt;20) for _ in range(50)]"`.

<details&gt;<summary>Ответ</summary>

В `top` виновника почти не видно (процессы живут миллисекунды), `%sys` заметно вырос.
execsnoop показывает непрерывный поток `date` и `id` с одним PPID — PID нашего шелла; `wc -l`
за 5 с — тысячи exec (сотни–тысяча в секунду).

</details>

**3.** Сравни строку oomkill с отчётом в `sudo dmesg -T | tail -20`. `sudo systemctl reset-failed oomt`.

<details><summary>Ответ</summary>

) Латентность read у fio — сотни мкс–мс (прямой I/O ждёт диск), у прочих процессов — единицы мкс.

</details>

### C10. Свой bpftrace-скрипт
Напиши `~/perf/t07/openat_lat.bt`: гистограмма латентности `openat()` в микросекундах по имени
процесса, сам завершается через 10 секунд. Запусти и прогони что-нибудь, что открывает много
файлов (`find /usr -name '*.py' > /dev/null`).

---

### Блок D. Инциденты


**D1.** Сервер: 25% `%sys`, в `top` ничего тяжёлого, LA умеренный. Что предполагаешь и чем проверишь?

<details><summary>Ответ</summary>

Много короткоживущих процессов (fork/exec) или процесс с огромным числом мелких syscalls.
Проверка: `execsnoop-bpfcc` (поток exec и их родитель), bpftrace one-liner 1 (syscalls по
процессам), гистограмма размеров read/write; `pidstat -w` (переключения контекста), `perf top`
(функции ядра).

</details>

**D2.** После выкатки конфига приложение стартует, но работает с настройками по умолчанию.
В логах тишина. Как быстро найти причину на живом процессе?

<details><summary>Ответ</summary>

`sudo opensnoop-bpfcc -x -p PID` (или без `-p` при рестарте) — какие пути приложение
пробует и получает `ENOENT`/`EACCES`: конфиг лежит не там, куда смотрит сервис, или нет прав.
Альтернатива — `strace -f -e trace=openat -Z` на старте.

</details>

**D3.** База: p99 запросов периодически прыгает до секунды, а `iostat` показывает `await` 3–5 мс.

<details><summary>Ответ</summary>

Среднее прячет хвост: `biolatency-bpfcc -D` покажет редкие I/O по сотням мс, `biosnoop -Q`
— какие процессы и операции (часто `fsync`/flush WAL, writeback, чужой бэкап). Дальше — сопоставить
по времени с пиками p99 и развести нагрузку (ionice, отдельный диск, лимиты IOPS облака).

</details>

**D4.** 16 ядер, CPU в среднем 60%. Под пиками растёт latency API. Команда: «CPU не узкое место».
Как проверить?

<details><summary>Ответ</summary>

Проверить saturation, а не utilization: `runqlat-bpfcc` на пике (сколько мс задачи ждут CPU),
`mpstat -P ALL` (горячие ядра), `vmstat` r, PSI `cpu some`, throttling контейнеров. Хвост
runqlat в десятки мс = CPU узкое место на пиках, даже при 60% среднего.

</details>

**D5.** Безопасность спрашивает: «кто вчера запускал shell в продовом поде?» Что можно ответить
сейчас и что внедрить, чтобы в следующий раз ответ был?

<details><summary>Ответ</summary>

Сейчас: если не было инструмента — только косвенно (аудит Kubernetes API на `pods/exec`,
логи рантайма). Ad hoc на будущее — `execsnoop` на ноде. Правильно — внедрить runtime security:
Falco (правило «shell в контейнере») или Tetragon (события exec с контекстом пода) и аудит-лог
API-сервера для `kubectl exec`.

</details>

**D6.** После релиза Go-сервис стал есть на 20% больше CPU. Хочется сравнить профили «до» и «после»
на всех нодах, не трогая код.

<details><summary>Ответ</summary>

Continuous profiling на eBPF: Parca-агент или Grafana Pyroscope (через Alloy) DaemonSet'ом
на нодах собирает CPU-профили всех процессов постоянно; сравнить flame graphs версий «до» и «после»
(diff) и найти выросшие функции. Для Go ещё помогает pprof самого сервиса.

</details>

**D7.** bcc-утилиты не запускаются на старой ноде (CentOS 7, ядро 3.10).

<details><summary>Ответ</summary>

Ядро 3.10 не поддерживает eBPF-трассировку в нужном объёме (bcc требует 4.x+, BTF нет).
На такой ноде — perf, strace, ftrace/sysstat; решение — обновить образ ноды/ОС (это давно EOL),
тогда появятся BTF и все инструменты.

</details>

**D8.** Инженер запустил на проде one-liner `uprobe:/lib/x86_64-linux-gnu/libc.so.6:malloc { @[comm] = count(); }`,
и сервис заметно замедлился. Почему? Какие правила нарушены?

<details><summary>Ответ</summary>

uprobe на `malloc` срабатывает на каждом вызове — миллионы переходов в ядро в секунду
у аллокационно-тяжёлого сервиса, оверхед огромный. Нарушены правила: не проверено на стенде,
нет фильтра по процессу, нет ограничения по времени; стоило начать с сэмплирования
(`profile`, `perf`) или `memleak` с ограничением и на короткое время.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое eBPF и почему он безопасен?

<details><summary>Ответ</summary>

Технология выполнения небольших программ в ядре по событиям (функции ядра, syscalls, пакеты,
   профайлер) с агрегацией в maps. Безопасна, потому что verifier до загрузки проверяет
   ограниченность циклов, доступ к памяти и разрешённые вызовы; ядро не уронить, как модулем.
   JIT делает её быстрой.

</details>

**2.** Чем eBPF лучше strace для диагностики на проде?

<details><summary>Ответ</summary>

strace останавливает процесс на каждом syscall и замедляет его в разы; eBPF считает в ядре
   и отдаёт агрегаты — оверхед маленький, можно смотреть всю систему сразу, и видно не только
   syscalls, но и диск, сеть, планировщик, off-CPU.

</details>

**3.** Какие bcc-инструменты знаешь и для чего?

<details><summary>Ответ</summary>

execsnoop (короткоживущие процессы), opensnoop (открытие файлов, ошибки), biolatency/biosnoop
   (латентность диска), runqlat (ожидание CPU), tcpconnect/tcplife/tcpretrans (TCP), cachestat
   (page cache), oomkill (OOM), profile/offcputime (on/off-CPU flame graphs).

</details>

**4.** Чем kprobe отличается от tracepoint?

<details><summary>Ответ</summary>

Tracepoint — статическая точка в ядре со стабильным форматом аргументов; kprobe — динамическая
   точка на любой функции ядра: гибче, но зависит от версии и может сломаться.
   По возможности — tracepoint.

</details>

**5.** Что нужно, чтобы запустить eBPF-инструменты на ноде?

<details><summary>Ответ</summary>

Достаточно свежее ядро (5.8+), BTF (`/sys/kernel/btf/vmlinux`) для CO-RE и bpftrace, права root
   или `CAP_BPF` + `CAP_PERFMON`, для bcc — заголовки ядра; в Kubernetes — привилегированный под
   на ноде или `kubectl debug node/… --profile=sysadmin`.

</details>

**6.** Как найти короткоживущие процессы, которые грузят систему?

<details><summary>Ответ</summary>

`execsnoop-bpfcc` показывает каждый exec с родителем и аргументами; дополнительно — счётчик
   exec в секунду и `%sys` в mpstat.

</details>

**7.** Как посмотреть распределение латентности диска?

<details><summary>Ответ</summary>

`biolatency-bpfcc -D` — гистограмма по дискам; `biosnoop-bpfcc` — каждый I/O с процессом
   и задержкой; в fio — перцентили `clat`.

</details>

**8.** Напиши bpftrace one-liner: число syscalls по процессам.

<details><summary>Ответ</summary>

`sudo bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); }'`.

</details>

**9.** Где eBPF применяется в Kubernetes?

<details><summary>Ответ</summary>

Сеть и NetworkPolicy (Cilium, замена kube-proxy), наблюдаемость потоков (Hubble), runtime
   security (Falco, Tetragon), continuous profiling (Parca, Pyroscope), автоинструментация (Beyla/OBI,
   Pixie), ad-hoc дебаг (Inspektor Gadget, bcc на ноде).

</details>

**10.** Какие риски у eBPF на проде?

<details><summary>Ответ</summary>

Оверхед при частых событиях, `printf` на событие и uprobe на горячих функциях; kprobe-скрипты
    ломаются между версиями ядра; привилегированные инструменты видят всю ноду (данные соседей,
    секреты в аргументах); bcc тяжёлый на старте. Поэтому — фильтры, агрегация, ограничение по
    времени, проверка на стенде, контроль доступа.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю eBPF, maps, verifier и JIT и почему это безопасно для прода
- [ ] ⭐ Отличаю tracepoint, kprobe, `kfunc`, uprobe, USDT и знаю, что стабильно
- [ ] Проверяю требования: ядро, BTF, права, `bpftool prog list`
- [ ] Знаю разницу bcc / libbpf-tools / bpftrace и что такое CO-RE
- [ ] ⭐ Подбираю bcc-инструмент под вопрос и запустил execsnoop, opensnoop, biolatency, runqlat, tcplife
- [ ] Читаю гистограммы и объясняю, чем они лучше средних
- [ ] ⭐ Пишу bpftrace one-liners с `count()`/`hist()` и свой скрипт с `interval` и `exit()`
- [ ] Меряю латентность syscall через map по `tid`
- [ ] Снял on-CPU и off-CPU flame graph через bcc
- [ ] Соблюдаю правила оверхеда: фильтр, агрегация, лимит времени, сначала стенд
- [ ] Ориентируюсь в экосистеме: Cilium, Tetragon, Falco, Pixie, Parca, Beyla/OBI
