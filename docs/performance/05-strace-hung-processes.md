---
title: "05. strace и зависшие процессы"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 05. Опирается на"
---

# 05. strace и зависшие процессы

> Блок → Deep Linux Troubleshooting & Performance → тема 05. Опирается на
> [../Linux/07_processes.md](/linux/07-processes) (состояния R/S/D/T/Z, сигналы, `/proc/PID`),
> [../Linux/12_kernel.md](/linux/12-kernel) (syscalls и базовый `strace`) и
> [../Linux/15_logging.md](/linux/15-logging) (`dmesg`).
>
> **После темы ты умеешь:** по состоянию процесса выбрать инструмент; снять strace с живого
> процесса с таймингами и сводкой и прочитать типовые syscalls; найти, где именно висит процесс
> в D-state (`wchan`, `/proc/PID/stack`, sysrq-w, hung_task); разобраться с зомби; снять стек
> через gdb, py-spy, jstack или pprof — без перезапуска.

---

## 🗺️ Карта темы

```text
                   «процесс завис / тормозит / не отвечает»
                                   │
                    ps -o pid,stat,wchan:32 -p PID
                                   │
     ┌──────────────┬──────────────┼──────────────┬──────────────┬──────────────┐
     ▼              ▼              ▼              ▼              ▼              ▼
     R              S              D              Z              T         много потоков
 жжёт CPU      спит и ждёт     ждёт в ядре     умер, не        остановлен   разные state
     │         события          (I/O, NFS)     прибран         (SIGSTOP,    у TID
     ▼              │              │              │            отладчик)       │
 perf top, py-spy   ▼              ▼              ▼              │              ▼
 (тема 02)   strace -p: на     wchan, stack,  чинить         TracerPid,   /proc/PID/task/
             каком syscall?    sysrq-w, dmesg РОДИТЕЛЯ       kill -CONT   TID/{stat,stack}
                    │              │
                    ▼              ▼
             futex → стек потоков (gdb, py-spy dump, jstack, pprof)
             read/connect → сеть (тема 04) · fsync/io_schedule → диск (тема 03)
```text
---

## 1. Состояние — первая развилка

Таблица состояний и базовые правила про зомби и D — в [../Linux/07_processes.md](/linux/07-processes).
Здесь — **что каждое состояние значит для отладки**:

| State | Что происходит | Что это говорит | Первый инструмент |
|-------|----------------|-----------------|-------------------|
| `R` | На CPU или в run queue | Проблема в вычислениях или в нехватке CPU | `perf top -p`, `pidstat -u -p` ([02](/performance/02-cpu-memory)) |
| `S` | Спит, ждёт события; будится сигналом | Ждёт сеть, лок, таймер, дочерний процесс | `strace -p`, `wchan`, стек потоков |
| `D` | Непрерываемое ожидание в ядре | Ждёт I/O, NFS, замороженную ФС, драйвер | `wchan`, `/proc/PID/stack`, sysrq-w, `dmesg` |
| `Z` | Завершился, родитель не сделал `wait()` | Баг в родителе | `ps -o ppid=`, strace родителя |
| `T` / `t` | Остановлен сигналом / отладчиком | Кто-то послал SIGSTOP или держит ptrace | `grep TracerPid /proc/PID/status` |
| `I` | Idle-поток ядра | Норма, в load average не входит | — |

```bash
ps -o pid,stat,wchan:32,etime,cmd -p 4242            # состояние + где спит в ядре
ps -eo stat= | cut -c1 | sort | uniq -c              # сколько процессов в каждом состоянии
ps -eLo pid,tid,stat,wchan:30,comm -p 4242           # по потокам (у каждого свой state!)
grep -E 'State|Threads|ctxt_switches' /proc/4242/status
```text
```text
# пример вывода: процесс «висит», но не на CPU
State:  S (sleeping)
Threads:        12
voluntary_ctxt_switches:        18423      ← смотри дважды с паузой: не растёт —
nonvoluntary_ctxt_switches:     311           процесс стоит, а не «медленно работает»
```text
> 💡 В `ps` буква `D` покрывает два разных ожидания: настоящий `TASK_UNINTERRUPTIBLE`
> (не убивается ничем) и `TASK_KILLABLE` (например, hard-mount NFS) — его SIGKILL прерывает.
> Попробовать `kill -9` на D-процессе не вредно: не убился — значит, ждёт по-настоящему.

---

## 2. strace на живом процессе: флаги, которые реально нужны

Базовые `-c`, `-e`, `-f -p`, `-T`, `-o` — в [../Linux/12_kernel.md](/linux/12-kernel).
Боевая команда для «что он сейчас делает»:

```bash
sudo strace -f -p 4242 -tt -T -s 200 -y -e trace=%net,%file -o /tmp/app.strace
# Ctrl+C — отцепиться (процесс продолжит работу)
```text
| Флаг | Что даёт | Зачем |
|------|----------|-------|
| `-f` | Все потоки и дочерние процессы | Без него увидишь только главный поток — а работают воркеры |
| `-p PID` | Прицепиться к живому процессу | Можно несколько `-p` |
| `-tt` | Время с микросекундами | Сопоставить с логами, найти паузы между вызовами |
| `-T` | Длительность вызова `&lt;0.000035&gt;` | Главное: **какой syscall долгий** |
| `-r` | Время от предыдущего вызова | Видно «тишину» — время в user space |
| `-s 200` | Длина строк (по умолчанию 32) | Видеть пути, SQL, HTTP-заголовки целиком |
| `-y` / `-yy` | fd → путь / + адреса сокетов | `read(7</var/lib/app.db>…)`, `connect(5&lt;TCP:[…]&gt;…)` |
| `-e trace=%file` | Группы: `%file %net %process %signal %memory %desc` | Отсечь шум |
| `-e trace=/^sock` | Регулярка по имени | Гибкий фильтр |
| `-P /etc/app.yaml` | Только вызовы с этим путём | «Кто и как трогает файл» |
| `-Z` / `-z` | Только неуспешные / только успешные | `-Z` — быстрый поиск ENOENT/EACCES |
| `-k` | Стек в user space на каждый вызов | Откуда в коде вызов (нужны символы) |
| `-o file` | В файл (с `-f` — строки с PID) | Не мешать выводу приложения |

```text
# пример вывода: sudo strace -f -tt -T -y -p 4242
4242  14:20:23.736175 openat(AT_FDCWD, "/etc/app/app.yaml", O_RDONLY|O_CLOEXEC) = 3</etc/app/app.yaml> &lt;0.000011&gt;
4250  14:20:23.739397 openat(AT_FDCWD, "/etc/app/local.yaml", O_RDONLY|O_CLOEXEC) = -1 ENOENT (No such file or directory) &lt;0.000035&gt;
4250  14:20:23.739535 connect(5&lt;TCP:[10.0.2.15:41822]&gt;, {sa_family=AF_INET, sin_port=htons(5432), sin_addr=inet_addr("10.0.0.20")}, 16) = -1 EINPROGRESS (Operation now in progress) &lt;0.000067&gt;
4250  14:20:23.739611 poll([{fd=5, events=POLLOUT}], 1, 5000 &lt;unfinished ...&gt;
4242  14:20:24.101002 futex(0x7f3a1c0012a8, FUTEX_WAIT_BITSET_PRIVATE|FUTEX_CLOCK_REALTIME, 0, NULL, FUTEX_BITSET_MATCH_ANY &lt;unfinished ...&gt;
4250  14:20:28.744702 <... poll resumed>) = 0 (Timeout) &lt;5.005091&gt;
 │         │           │                                                                        │
 PID    время        вызов(аргументы) = результат                                     длительность
```text
Как читать: `&lt;unfinished ...&gt;` / `<... poll resumed>` — вызов начался в одном потоке и
завершился позже (между ними печатались другие потоки). Здесь поток 4250 пять секунд ждал
неблокирующий `connect` к 10.0.0.20:5432 и получил таймаут — база недоступна.

---

## 3. `strace -c`: сводка и ловушка «system time»

```text
# пример вывода: sudo strace -c -f -p 4242   (Ctrl+C через 10 секунд)
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 41.20    0.018344          12      1489           read
 22.73    0.010121           6      1611           write
 11.02    0.004907           3      1402       118 openat
  8.90    0.003962          24       162           futex
  ...
------ ----------- ----------- --------- --------- ----------------
100.00    0.044525           9      5021       131 total
```text
| Колонка | Смысл |
|---------|-------|
| `% time`, `seconds` | Доля и сумма времени в вызове |
| `usecs/call` | Среднее на вызов |
| `calls` / `errors` | Число вызовов и ошибок (118 ENOENT у openat — часто норма: поиск по путям) |

⚠️ **Ловушка:** по умолчанию `-c` считает **system time** — CPU, потраченный ядром. Вызов,
который 5 секунд *ждал* сеть или лок, почти не тратит CPU и в сводке выглядит копеечным.
Для вопроса «где проходит время» нужен **`-w`** (wall clock):

```bash
sudo strace -c -w -f -p 4242          # время «от входа до выхода» из вызова
sudo strace -c -w -S calls -f -p 4242 # сортировка по числу вызовов (-S time|calls|errors|name)
sudo strace -C -f -p 4242             # сводка + обычный вывод
```text
```text
# пример: тот же процесс, но -c -w
% time     seconds  usecs/call     calls    errors syscall
 88.14    8.846113      54605       162           futex        ← потоки ждут лок
  9.97    1.000712    1000712         1           poll         ← ожидание сети
```text
> 💡 Много `futex` с большим wall-временем — потоки ждут друг друга (лок, очередь,
> пул соединений). strace дальше не поможет: нужен стек потоков (раздел 10).

---

## 4. Как читать типовые syscalls

| Что видишь | Что это значит | Куда дальше |
|------------|----------------|-------------|
| `openat(...) = -1 ENOENT` | Файла нет. Сотни подряд при старте Python/Java — поиск модулей, норма | Последний ENOENT перед падением — настоящая причина |
| `openat(...) = -1 EACCES` | Нет прав | [../Linux/06_permissions.md](/linux/06-permissions) |
| `openat(...) = -1 EMFILE` | Кончились fd у процесса | `ulimit -n`, утечка fd ([04](/performance/04-network-deep)) |
| `connect(...) = -1 ECONNREFUSED` | Порт закрыт — ответили RST | Сервис не слушает / REJECT |
| `connect(...) = -1 ETIMEDOUT &lt;127.2&gt;` | Блокирующий connect: SYN без ответа, ~127 с при `tcp_syn_retries=6` | DROP в firewall, хост недоступен |
| `connect(...) = -1 EINPROGRESS` + `poll(…) = 0 (Timeout)` | Неблокирующий connect, таймаут задан в приложении | То же, но таймаут короче |
| `sendto(…:53…)` + `recvfrom` долгий / повторы | DNS отвечает медленно | [04](/performance/04-network-deep), DNS-латентность |
| `read(5&lt;TCP:…&gt;, …)` на секунды | Ждём ответ апстрима | Смотреть апстрим, а не своё приложение |
| `epoll_wait(…, 1000) = 0` в цикле | Event loop простаивает — **норма** | Искать проблему в другом потоке |
| `futex(… FUTEX_WAIT …)` долгий | Ожидание лока/condition variable | Стек потоков |
| `fsync(3) = 0 &lt;2.8&gt;` | Сброс на диск 2,8 с | [03](/performance/03-disk-io): `w_await`, dirty pages |
| `write(1, …) = -1 EPIPE` / `EAGAIN` | Читатель закрыл pipe / неблокирующий сокет полон | Смотреть потребителя |
| `clock_nanosleep` / `nanosleep` | Сон в коде: ретраи, backoff, `sleep()` | Логика приложения |
| `wait4(-1, …` долгий | Ждёт дочерний процесс | strace ребёнка |
| `mmap`/`brk` растут без `munmap` | Выделяет память | Утечка? ([02](/performance/02-cpu-memory)) |

Типичный сценарий «приложение стартует 40 секунд»:
```bash
sudo strace -f -tt -T -e trace=%net,%file -o /tmp/start.strace ./app
awk -F'<' '{t=$NF; sub(/>.*/,"",t); if (t+0 > 1) print}' /tmp/start.strace   # вызовы дольше 1 с
```text
```text
# пример находки
3121  10:02:11.402133 recvfrom(4, …, 2048, 0, {…sin_port=htons(53), sin_addr=inet_addr("10.0.0.2")}, …) = -1 EAGAIN …
3121  10:02:11.402201 poll([{fd=4, events=POLLIN}], 1, 5000) = 0 (Timeout) &lt;5.005008&gt;      ← ×8 раз
```text
Восемь таймаутов DNS по 5 секунд — первый резолвер в `/etc/resolv.conf` мёртв.

---

## 5. Цена strace в проде

```text
без strace:   app ──syscall──► kernel ──► app
со strace:    app ──syscall──► STOP ─► strace читает аргументы ─► kernel ─► STOP ─► strace ─► app
              два переключения контекста на КАЖДЫЙ вызов (ptrace-stop на входе и выходе)
```text
- Syscall-тяжёлый процесс (прокси, БД) под strace может замедлиться в **десятки раз**.
  Фильтр `-e trace=` почти не помогает: остановки всё равно на каждом вызове.
- `--seccomp-bpf` останавливает только на отслеживаемых вызовах — но работает лишь с `-f`
  и **не работает при `-p`** (только для процессов, запущенных под strace).
- Альтернативы с малым оверхедом: `sudo perf trace -p PID` (и `perf trace -s` — сводка)
  и eBPF-инструменты `syscount-bpfcc`, `opensnoop-bpfcc` ([07](/performance/07-ebpf-bpftrace)).
- Трейсер у процесса может быть только один: если уже прицеплен gdb, strace получит
  `Operation not permitted`. Проверка: `grep TracerPid /proc/PID/status`.
- В Ubuntu `kernel.yama.ptrace_scope = 1`: без sudo прицепиться можно только к своим
  потомкам. В контейнере нужна capability `SYS_PTRACE` (в `kubectl debug` её даёт профиль
  `general`, тема [06](/performance/06-cgroups-containers)).

**Правило:** strace в проде — коротко (секунды), с `-o` в файл, на одном процессе
и с пониманием, что ты его тормозишь.

---

## 6. ltrace — кратко

`ltrace` показывает вызовы функций разделяемых библиотек (`malloc`, `getaddrinfo`, `SSL_read`).

```bash
sudo ltrace -c -p 4242                    # сводка по библиотечным вызовам
ltrace -e getaddrinfo+connect curl -s example.com >/dev/null
ltrace -S -T ./app                        # + syscalls, + время
```text
Ограничения: не видит статически слинкованные бинари (Go), на современных бинарях
с full RELRO/BIND_NOW часто показывает мало или ничего, оверхед ещё больше, чем у strace.
Современная замена — uprobes через bpftrace ([07](/performance/07-ebpf-bpftrace)).

---

## 7. Процесс висит: где именно он стоит

```bash
PID=4242
cat /proc/$PID/wchan; echo                 # функция ядра, в которой спит
sudo cat /proc/$PID/stack                  # полный стек ядра (только root)
sudo cat /proc/$PID/syscall                # номер текущего syscall и аргументы
for t in /proc/$PID/task/*; do echo "$(basename $t) $(cat $t/wchan)"; done   # по потокам
sudo lsof -nP -p $PID                      # что открыто: файлы, сокеты, pipe
```text
```text
# пример вывода: процесс в D, ждёт NFS
$ ps -o pid,stat,wchan:32,cmd -p 5120
    PID STAT WCHAN                            CMD
   5120 D    rpc_wait_bit_killable            ls /mnt/nfs

$ sudo cat /proc/5120/stack
[&lt;0&gt;] rpc_wait_bit_killable+0x11/0x80 [sunrpc]
[&lt;0&gt;] __rpc_execute+0x122/0x480 [sunrpc]
[&lt;0&gt;] rpc_execute+0xd6/0x100 [sunrpc]
[&lt;0&gt;] nfs4_call_sync_sequence+0x74/0xb0 [nfsv4]
[&lt;0&gt;] nfs4_proc_getattr+0x7a/0x130 [nfsv4]
[&lt;0&gt;] __nfs_revalidate_inode+0xd4/0x2c0 [nfs]
[&lt;0&gt;] vfs_statx+0xa0/0x180
[&lt;0&gt;] __x64_sys_newfstatat+0x55/0xa0
```text
Стек читается **снизу вверх**: `newfstatat` (syscall `stat`) → NFS getattr → ожидание RPC.

`wchan` → подсистема (ориентиры; точные имена зависят от версии ядра):

| wchan / вершина стека | Где стоит процесс |
|-----------------------|-------------------|
| `futex_wait_queue`, `futex_wait` | Лок/condition в user space → стек потоков |
| `do_epoll_wait`, `ep_poll`, `do_sys_poll` | Ждёт событий (часто норма) |
| `rpc_wait_bit_killable`, `nfs_*` | NFS-сервер не отвечает |
| `io_schedule`, `folio_wait_bit*`, `blk_mq_*`, `jbd2_*` | Диск / журнал ФС ([03](/performance/03-disk-io)) |
| `percpu_rwsem_wait` | Часто — замороженная ФС (`fsfreeze`, `dmsetup suspend`) |
| `pipe_read`, `pipe_write` | Pipe: вторая сторона не читает/не пишет |
| `unix_stream_read_generic`, `inet_csk_accept`, `tcp_recvmsg` | Сокеты |
| `do_wait` | Ждёт завершения дочернего |
| `hrtimer_nanosleep` | Спит по таймеру |

---

## 8. D-state: NFS, диск, заморозка ФС

**Почему `kill -9` не помогает:** сигнал доставляется, когда процесс возвращается из ядра
в user space. В `TASK_UNINTERRUPTIBLE` ядро не будит процесс ради сигналов — SIGKILL
ляжет в очередь и сработает, только когда закончится I/O. Такие процессы входят в load
average (почему «LA 30 при idle CPU» — в [01](/performance/01-methodology)).

Типовые причины:

| Причина | Признак |
|---------|---------|
| NFS/CIFS-сервер недоступен | `wchan` `rpc_*`/`nfs_*`, в dmesg `nfs: server … not responding, still trying` |
| Диск умирает или перегружен | `iostat -x`: огромный `await`; в dmesg `I/O error`, `blk_update_request`, `reset` |
| ФС заморожена | `fsfreeze -f`, снапшот LVM/облака, `dmsetup suspend` |
| Облачный диск «подвис» / throttling IOPS | `await` секунды при малом `r/s`/`w/s` |
| Баг драйвера | Стек уходит в модуль драйвера, помогает только ребут |

### hung_task — ядро само сообщит о зависших

Если задача в `TASK_UNINTERRUPTIBLE` не получала CPU дольше `kernel.hung_task_timeout_secs`
(по умолчанию 120 с), в `dmesg` появится:

```text
# пример вывода dmesg -T
[Sun Sep 27 14:31:07 2026] INFO: task dd:6021 blocked for more than 120 seconds.
[Sun Sep 27 14:31:07 2026]       Not tainted 6.8.0-45-generic #45-Ubuntu
[Sun Sep 27 14:31:07 2026] "echo 0 > /proc/sys/kernel/hung_task_timeout_secs" disables this message.
[Sun Sep 27 14:31:07 2026] task:dd    state:D stack:0  pid:6021  ppid:5980  flags:0x00004002
[Sun Sep 27 14:31:07 2026] Call Trace:
[Sun Sep 27 14:31:07 2026]  &lt;TASK&gt;
[Sun Sep 27 14:31:07 2026]  __schedule+0x27c/0x6b0
[Sun Sep 27 14:31:07 2026]  schedule+0x33/0x110
[Sun Sep 27 14:31:07 2026]  percpu_rwsem_wait+0x118/0x140
[Sun Sep 27 14:31:07 2026]  __percpu_down_read+0x5c/0x70
[Sun Sep 27 14:31:07 2026]  vfs_write+0x3b1/0x420
[Sun Sep 27 14:31:07 2026]  ksys_write+0x6d/0xf0
```text
- После `kernel.hung_task_warnings` сообщений (по умолчанию 10) они подавляются — первые
  отчёты самые ценные, ищи их в `journalctl -k`.
- Детектор **пропускает `TASK_KILLABLE`**: зависший NFS hard-mount hung_task не даст —
  смотри сообщения NFS.
- `kernel.hung_task_panic=1` превращает зависание в панику — только осознанно (кластеры с
  fencing), не «на всякий случай».

### sysrq-w — стеки всех D-процессов сразу

```bash
echo w | sudo tee /proc/sysrq-trigger       # ⚠️ только на VM или осознанно на проде
sudo dmesg -T | tail -60                    # «sysrq: Show Blocked State» + стек каждой D-задачи
```text
> ⚠️ `/proc/sysrq-trigger` работает от root **независимо** от `kernel.sysrq` (эта маска
> влияет только на клавиатуру). Читающие команды: `w` (заблокированные), `l` (стеки CPU),
> `t` (все задачи — огромный вывод). **Никогда** «на пробу»: `c` (crash), `b` (мгновенный
> reboot без sync), `o` (poweroff), `e`/`i` (SIGTERM/SIGKILL всем процессам).
> `sudo echo w > /proc/sysrq-trigger` не сработает: редирект выполняет твой shell без root.

### Воспроизвести D-state на стенде (⚠️ только VM `perf-lab`)

```bash
sudo modprobe dm-delay
SZ=$(sudo blockdev --getsz /dev/vdb)
echo "0 $SZ delay /dev/vdb 0 100" | sudo dmsetup create slow    # +100 мс на каждый запрос
sudo mkfs.ext4 -q /dev/mapper/slow && sudo mkdir -p /mnt/slow && sudo mount /dev/mapper/slow /mnt/slow
sudo dmsetup suspend slow                        # заморозить устройство (и ФС на нём)
sudo dd if=/dev/zero of=/mnt/slow/f bs=1M count=10 oflag=direct &   # повиснет в D
sleep 2; ps -o pid,stat,wchan:32,cmd -C dd
sudo kill -9 $(pgrep -x dd); sleep 1; ps -o pid,stat,cmd -C dd       # всё ещё D
sudo dmsetup resume slow                         # «починили хранилище» — dd завершится/умрёт
```text
Полный сценарий с hung_task и strace медленного приложения — лаба 6 в
[08_practice_labs.md](/softskills/08-practice-labs).

**Как выходят из D:** чинят причину (поднимают NFS-сервер, `dmsetup resume`, меняют диск).
Для NFS — `umount -f` (принудительно) или `umount -l` (lazy: отцепить от дерева сразу).
`soft`-mount вместо `hard` убирает вечное зависание ценой ошибок I/O и риска потери данных.
Умер диск или драйвер — только перезагрузка.

---

## 9. Зомби: глубже, чем «чини родителя»

База — в [../Linux/07_processes.md](/linux/07-processes). Практика расследования:

```bash
ps -eo pid,ppid,stat,etime,cmd | awk '$3 ~ /^Z/'                      # все зомби
ps -eo ppid=,stat= | awk '$2 ~ /^Z/ {print $1}' | sort | uniq -c | sort -rn   # зомби по родителям
ps -o pid,stat,cmd -p &lt;PPID&gt;                                           # кто родитель и что он делает
sudo strace -f -p &lt;PPID&gt; -e trace=wait4,waitid,%signal                 # вызывает ли он wait вообще
```text
```text
# пример: учебный генератор зомби (⚠️ VM)
python3 -c 'import os,time; [os.fork() or os._exit(0) for _ in range(5)]; time.sleep(600)' &
ps -eo pid,ppid,stat,cmd | awk '$3 ~ /^Z/'
   7311    7310 Z    [python3] &lt;defunct&gt;
   7312    7310 Z    [python3] &lt;defunct&gt;
   ...
```text
- `kill -9 &lt;зомби&gt;` бессмысленен: процесса уже нет, осталась запись с кодом возврата.
- `kill -CHLD &lt;PPID&gt;` помогает, только если у родителя есть обработчик SIGCHLD, который
  зовёт `wait()`, и он просто «пропустил» сигнал.
- Рабочий способ — перезапустить/завершить родителя: зомби переходят к PID 1 (или к
  subreaper) и сразу прибираются.
- **Чем опасны:** каждый зомби держит PID. Упрёшься в `pids.max` cgroup (лимит PID пода/контейнера)
  или `kernel.pid_max` → `fork: Resource temporarily unavailable` (EAGAIN) у всех в этом cgroup.
- В контейнере PID 1 — твоё приложение: если оно не прибирает «внуков», зомби копятся →
  `docker run --init` (tini), `tini` в образе или `shareProcessNamespace: true` в поде
  (тогда PID 1 — pause, и он прибирает).

---

## 10. Стек изнутри: gdb, py-spy, jstack, pprof

strace говорит «ждёт futex», но не говорит **чего ждёт код**. Нужен стек в user space.

**gdb** (C/C++/Rust, любые нативные процессы):
```bash
sudo gdb -p 4242 -batch -ex 'thread apply all bt' > /tmp/bt.txt 2>&1   # стеки всех потоков
sudo gcore -o /tmp/core 4242                                          # core dump без убийства
```text
⚠️ На время снятия процесс **остановлен** (ptrace). Символы: в Ubuntu 22.10+ gdb сам
подтягивает их с `debuginfod.ubuntu.com` (переменная `DEBUGINFOD_URLS`).

**py-spy** (Python, без перезапуска и изменения кода; сэмплирует, на каждый сэмпл лишь
мгновенно приостанавливает процесс, `--nonblocking` — совсем без пауз ценой точности):
```bash
sudo ~/.local/bin/py-spy dump --pid 4242              # стек каждого потока прямо сейчас
sudo ~/.local/bin/py-spy dump --pid 4242 --locals     # + локальные переменные
sudo ~/.local/bin/py-spy top --pid 4242               # «top» по функциям Python
sudo ~/.local/bin/py-spy record -o /tmp/prof.svg --pid 4242 --duration 30   # flame graph
```text
```text
# пример вывода py-spy dump
Process 4242: python3 app.py
Python v3.12.3 (/usr/bin/python3.12)

Thread 0x7F3A2C5B8740 (idle): "MainThread"
    wait (threading.py:355)
    get (queue.py:171)
    worker (app.py:41)
Thread 0x7F3A1B7FE6C0 (active): "db-pool-1"
    _execute (psycopg/cursor.py:737)
    slow_report (app.py:88)          ← вот кто держит единственное соединение пула
```text
**Другие рантаймы** (только ссылки, суть та же — дамп потоков по живому процессу):
- Java: `jcmd &lt;PID&gt; Thread.print` или `jstack &lt;PID&gt;` —
  [jcmd](https://docs.oracle.com/en/java/javase/21/docs/specs/man/jcmd.html).
- Go: `net/http/pprof`, дамп горутин `curl 'localhost:6060/debug/pprof/goroutine?debug=2'` —
  [pprof](https://pkg.go.dev/net/http/pprof). ⚠️ `SIGQUIT` Go-процессу печатает стеки горутин,
  **но завершает процесс**.
- Python: [py-spy](https://github.com/benfred/py-spy).

---

## 11. Алгоритм «процесс завис»

```text
1. ps -o pid,stat,wchan:32,etime -p PID   состояние, где спит
2. /proc/PID/status дважды                 ctxt_switches растут? (медленно работает vs стоит)
3. R  → perf top -p PID / py-spy top       (тема 02)
   S  → strace -f -tt -T -p PID            на каком вызове ждёт и сколько
        futex → стек потоков (gdb/py-spy/jstack)
        read/connect/poll на сокете → куда подключён (lsof -p, ss -tnp) → тема 04
   D  → wchan, sudo cat /proc/PID/stack, dmesg -T | tail, sysrq-w
        nfs/rpc → сеть до NFS · io_schedule/jbd2 → iostat -x (тема 03)
   Z  → родитель: ps -o ppid=, strace родителя, перезапуск родителя
   T  → TracerPid, kill -CONT
4. Зафиксировать доказательство (вывод команды) ДО перезапуска
5. Смягчение: рестарт/failover; потом — причина и постмортем
```text
---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `strace -p PID` без `-f` | Видишь только главный поток, а висят воркеры | Всегда `-f` для многопоточных |
| `strace -c` показал «ничего долгого» | По умолчанию считается CPU-время ядра, ожидания не видны | `-c -w` (wall clock) |
| strace на нагруженном проде надолго | Замедление в разы, таймауты у клиентов | Секунды, `-o`, или `perf trace`/eBPF |
| `kill -9` D-процессу в цикле | Не поможет: ждёт ядро | Чинить I/O-причину, sysrq-w для диагностики |
| `kill -9` зомби | Он уже мёртв | Родитель: wait/рестарт |
| Перезапустили, не сняв стек | Причина потеряна | Сначала `wchan`, `stack`, dump потоков, strace на 10 с |
| `sudo echo w > /proc/sysrq-trigger` | Редирект без root | `echo w \| sudo tee /proc/sysrq-trigger` |
| Нажать sysrq-букву «посмотреть» | `c`/`b`/`o`/`e`/`i` уронят систему | Только `w`, `l`, `t` |
| gdb на проде «надолго» | Процесс стоит, пока стоит gdb | `-batch`, один `bt`, сразу отцепиться |
| ltrace на Go-бинаре | Статическая линковка — вызовов не видно | pprof / uprobes |
| ENOENT в strace = «вот причина» | Сотни ENOENT при поиске модулей — норма | Смотреть последнюю ошибку перед сбоем |

---

## 💼 Как это в DevOps

- «Сервис завис, логи молчат» — самый частый повод для strace: за 10 секунд видно, что
  процесс 5 секунд ждёт `connect` к базе или бесконечно ретраит DNS.
- Перед рестартом зависшего сервиса дежурный снимает доказательства: `ps`/`wchan`,
  `/proc/PID/stack`, дамп потоков (`py-spy dump`, `jcmd Thread.print`). Без них постмортем
  превращается в «перезапустили — прошло».
- Всплеск load average при пустом CPU на ноде Kubernetes → D-state → зависший NFS/EBS-том
  или сетевое хранилище. `dmesg` и `wchan` дают ответ за минуту.
- Зомби в контейнерах лечат на уровне образа и манифеста: `tini`/`--init`,
  `shareProcessNamespace`, а не «рестартом раз в сутки».
- В проде strace постепенно вытесняют eBPF-инструменты: тот же ответ почти без оверхеда
  ([07](/performance/07-ebpf-bpftrace)).

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Состояние и где спит | `ps -o pid,stat,wchan:32,etime,cmd -p PID` |
| Состояния по потокам | `ps -eLo pid,tid,stat,wchan:30,comm -p PID` |
| Стоит или работает | `grep ctxt_switches /proc/PID/status` (дважды) |
| Что делает сейчас | `sudo strace -f -tt -T -s 200 -y -p PID -o /tmp/t.log` |
| Где проходит время | `sudo strace -c -w -f -p PID` |
| Только ошибки | `sudo strace -f -Z -p PID` |
| Кто трогает файл | `strace -f -P /path ./app` |
| Сеть/файлы | `-e trace=%net` / `-e trace=%file` |
| Низкий оверхед | `sudo perf trace -s -p PID`, `syscount-bpfcc` |
| Стек ядра | `sudo cat /proc/PID/stack` |
| Все D-задачи | `echo w \| sudo tee /proc/sysrq-trigger; dmesg -T \| tail` |
| Порог hung_task | `sysctl kernel.hung_task_timeout_secs` |
| Зомби по родителям | `ps -eo ppid=,stat= \| awk '$2~/^Z/{print $1}' \| sort \| uniq -c` |
| Стеки нативного процесса | `sudo gdb -p PID -batch -ex 'thread apply all bt'` |
| Стек Python | `sudo ~/.local/bin/py-spy dump --pid PID` |
| Стек Java / Go | `jcmd PID Thread.print` / `…/debug/pprof/goroutine?debug=2` |
| Открытые файлы/сокеты | `sudo lsof -nP -p PID` |

---

## 🧠 Что запомнить

1. Первый вопрос — состояние: R → профайлер, S → strace, D → стек ядра, Z → родитель.
2. `strace -f -tt -T -p` — «что делает и сколько ждёт»; без `-f` видишь не те потоки.
3. `strace -c` по умолчанию считает CPU-время ядра; ожидания видны только с `-w`.
4. strace тормозит процесс на каждом syscall — в проде коротко или `perf trace`/eBPF.
5. `EINPROGRESS` + `poll … Timeout` и `ETIMEDOUT` — сеть; `futex` — локи; `fsync` — диск.
6. D-процесс не убивается, пока ядро не дождётся I/O; `TASK_KILLABLE` (NFS) — убивается.
7. hung_task пишет `blocked for more than 120 seconds`, sysrq-w даёт стеки всех D-задач.
8. `/proc/sysrq-trigger` работает от root всегда — пользуйся только `w`, `l`, `t`.
9. Зомби опасны исчерпанием PID; лечится родителем, в контейнерах — init-процессом.
10. Перед рестартом зависшего процесса сохрани доказательства: wchan, stack, дамп потоков.

➡️ Дальше: [06_cgroups_containers.md](/performance/06-cgroups-containers) · задачи: 05_strace_hung_processes_tasks.md


---

### Блок A. Теория


**A1.** Почему диагностику зависшего процесса начинают с его состояния? Какой инструмент
берёшь для R, S, D, Z, T?

<details><summary>Ответ</summary>

Состояние сразу сужает область поиска: R — процесс считает (perf top, py-spy top,
тема 02); S — ждёт события (strace -p: какой syscall; потом стек потоков); D — ждёт ядро
(wchan, `/proc/PID/stack`, dmesg, sysrq-w); Z — чинить родителя (ppid, strace родителя);
T — кто остановил (TracerPid, SIGSTOP → `kill -CONT`).

</details>

**A2.** Чем `TASK_UNINTERRUPTIBLE` отличается от `TASK_KILLABLE`? Как это выглядит в `ps`
и как отличить на практике?

<details><summary>Ответ</summary>

Оба показываются в `ps` как `D` и входят в load average. `TASK_UNINTERRUPTIBLE`
не будится ничем, кроме завершения ожидания. `TASK_KILLABLE` = uninterruptible + реакция на
фатальные сигналы: SIGKILL его прерывает. Практически: `kill -9` — умер, значит killable
(например, hard-mount NFS, `wchan` `rpc_wait_bit_killable`); не умер — настоящее
uninterruptible-ожидание (диск, замороженная ФС).

</details>

**A3.** ⭐ Почему `kill -9` не убивает процесс в D-state?

<details><summary>Ответ</summary>

Сигналы обрабатываются при возврате из ядра в user space. Процесс в
`TASK_UNINTERRUPTIBLE` ядро ради сигналов не будит: SIGKILL ставится в очередь и сработает,
когда закончится I/O. Прервать ожидание на полпути небезопасно для структур ядра/данных.

</details>

**A4.** ⭐ Процесс явно тормозит, а `strace -c` показывает доли миллисекунд. Почему и что делать?

<details><summary>Ответ</summary>

По умолчанию `-c` суммирует system time — CPU, потраченный в ядре. Блокирующие вызовы
(futex, poll, read сокета) ждут, почти не тратя CPU, и выглядят копеечными. Нужен `-c -w`
(wall clock) — тогда видно, в каком вызове проходит реальное время.

</details>

**A5.** Что дают флаги `-f`, `-tt`, `-T`, `-y`, `-s 200`? Какой из них самый важный для
поиска «где ждёт»?

<details><summary>Ответ</summary>

`-f` — все потоки и дети; `-tt` — абсолютное время с микросекундами; `-T` —
длительность каждого вызова; `-y` — путь/адрес вместо номера fd; `-s 200` — не обрезать
строки на 32 символах. Для «где ждёт» главный — `-T` (вместе с `-f`).

</details>

**A6.** ⭐ Почему strace дорог в проде? Помогает ли `-e trace=connect`? Что такое
`--seccomp-bpf` и когда он не работает? Какие есть альтернативы?

<details><summary>Ответ</summary>

ptrace останавливает процесс на входе и выходе **каждого** syscall и переключает
контекст в strace — syscall-тяжёлый процесс замедляется в разы и в десятки раз.
`-e trace=connect` только фильтрует вывод, остановки остаются. `--seccomp-bpf` ставит
seccomp-фильтр, чтобы стоп был только на отслеживаемых вызовах, но работает лишь с `-f`
и не применяется к процессам, подключённым через `-p`. Альтернативы: `perf trace`,
eBPF (`syscount-bpfcc`, `opensnoop-bpfcc`, bpftrace).

</details>

**A7.** Что означает `connect(...) = -1 EINPROGRESS`, за которым идёт `poll(...) = 0 (Timeout)`?
Чем это отличается от `connect(...) = -1 ETIMEDOUT &lt;127.2&gt;`?

<details><summary>Ответ</summary>

Неблокирующий connect: ядро отправило SYN и вернуло управление (`EINPROGRESS`),
приложение ждёт готовности сокета в `poll` со своим таймаутом — и не дождалось (хост не
ответил). `ETIMEDOUT &lt;127.2&gt;` — блокирующий connect без таймаута в приложении: ядро само
повторяло SYN (`tcp_syn_retries=6` ≈ 127 с) и сдалось. В обоих случаях SYN без ответа —
DROP в firewall или недоступный хост; во втором ещё и нет таймаута в коде.

</details>

**A8.** В strace сотни долгих `futex(... FUTEX_WAIT ...)`. Что это значит и что делать дальше?

<details><summary>Ответ</summary>

Потоки ждут друг друга: мьютекс, condition variable, очередь, пул соединений,
GC-safepoint. Сам strace дальше не покажет — нужен стек в user space: `py-spy dump`,
`jcmd PID Thread.print`, goroutine dump, `gdb … thread apply all bt`. Там видно, кто держит
ресурс и кто ждёт.

</details>

**A9.** `epoll_wait(..., 1000) = 0` повторяется каждую секунду. Это проблема?

<details><summary>Ответ</summary>

Обычно нет: event loop ждёт событий с таймаутом 1 с и просыпается по таймеру —
так выглядит простаивающий поток. Проблему ищут в других потоках (`-f`) или в том, что
событий не приходит (апстрим не отвечает).

</details>

**A10.** Чем `/proc/PID/wchan` отличается от `/proc/PID/stack`? Кому они доступны?

<details><summary>Ответ</summary>

`wchan` — одна функция ядра, в которой задача спит; читается всем (как `ps -o wchan`).
`/proc/PID/stack` — полный стек ядра задачи, читается только root. Для потоков —
`/proc/PID/task/TID/{wchan,stack}`.

</details>

**A11.** Когда ядро пишет `INFO: task … blocked for more than 120 seconds`? Какие sysctl
этим управляют? Почему при зависшем NFS hard-mount этого сообщения нет?

<details><summary>Ответ</summary>

Когда задача в `TASK_UNINTERRUPTIBLE` не планировалась дольше
`kernel.hung_task_timeout_secs` (120 с по умолчанию; 0 — выключить). Сообщений не больше
`kernel.hung_task_warnings` (10), `kernel.hung_task_panic` превращает в панику. Детектор
пропускает `TASK_KILLABLE`, а NFS hard-mount ждёт именно так — вместо hung_task будет
`nfs: server … not responding, still trying`.

</details>

**A12.** ⭐ Что делает `echo w | sudo tee /proc/sysrq-trigger`? Почему работает при
`kernel.sysrq = 176`? Какие буквы нельзя нажимать «посмотреть»?

<details><summary>Ответ</summary>

Ядро печатает в kernel log стеки всех задач в D-состоянии («Show Blocked State»):
сразу видно, что все ждут одного — диска, NFS, лока ФС. `kernel.sysrq` — маска только для
клавиатурных комбинаций; запись в `/proc/sysrq-trigger` от root разрешена всегда. Безопасно
читать: `w`, `l`, `t` (огромный вывод). Нельзя: `c` (crash), `b` (reboot без sync),
`o` (poweroff), `e`/`i` (SIGTERM/SIGKILL всем), `s`/`u` тоже меняют состояние системы.

</details>

**A13.** Чем опасны зомби, если они не едят ни CPU, ни память? Как их убрать?
Почему в контейнерах их больше?

<details><summary>Ответ</summary>

Каждый зомби держит PID. Исчерпание `pids.max` cgroup (лимит PID контейнера/пода)
или `kernel.pid_max` → никто в этом cgroup не может сделать fork (`EAGAIN`). Лечение —
родитель: исправить `wait()`, дать `SIGCHLD`, если он умеет, или перезапустить родителя
(зомби перейдут к PID 1 и будут прибраны). В контейнере PID 1 — приложение, которое не
умеет прибирать осиротевших потомков → `--init`/tini, `shareProcessNamespace`.

</details>

**A14.** Чем снятие стека через gdb отличается по влиянию на процесс от py-spy dump?

<details><summary>Ответ</summary>

gdb прицепляется через ptrace и **останавливает** процесс на всё время работы
(а без `-batch` — пока ты в сессии): прод-процесс замирает целиком. py-spy читает память
процесса снаружи: `dump` — один снимок, `top`/`record` — сэмплирование; по умолчанию на
каждый сэмпл процесс приостанавливается на очень короткое время ради согласованного стека,
а с `--nonblocking` — вообще без пауз (ценой возможных неточностей). Влияние несравнимо меньше.

</details>

**A15.** Почему ltrace часто ничего не показывает на современных бинарях и на Go?

<details><summary>Ответ</summary>

ltrace перехватывает вызовы через PLT динамических библиотек. У Go-бинарей статическая
линковка и свой рантайм — PLT-вызовов нет. Бинари с full RELRO/BIND_NOW (`-z now`) резолвят
символы при старте, и ltrace на них часто не срабатывает. Замена — uprobes (bpftrace).

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ ps -o pid,stat,wchan:32,cmd -p 5120
```text
<details><summary>Ответ</summary>

`rpc_wait_bit_killable` — ожидание ответа NFS-сервера, состояние `TASK_KILLABLE`:
поэтому SIGKILL сработал. Проблема не в `du`, а в NFS: проверить сервер, сеть до него,
`dmesg` (`not responding, still trying`), `mount | grep nfs` (hard/soft, timeo).

</details>

```text:no-line-numbers
         PID STAT WCHAN                            CMD
```text
```text:no-line-numbers
        5120 D    rpc_wait_bit_killable            du -sh /mnt/share
```text
```text:no-line-numbers
     $ sudo kill -9 5120; sleep 1; ps -p 5120     → процесса больше нет
```text
```text:no-line-numbers
B2.  # сервис отвечает по 3 секунды
```text
<details><summary>Ответ</summary>

⚠️ Сводка без `-w` считает CPU-время ядра — ожидания в futex и epoll_wait там не видны.
Сделать `strace -c -w -f -p 2210`: скорее всего наверху окажется `futex` с секундами —
потоки ждут лок/пул; дальше — дамп стеков.

</details>

```text:no-line-numbers
     $ sudo strace -c -f -p 2210    (10 секунд)
```text
```text:no-line-numbers
     % time     seconds  usecs/call     calls    errors syscall
```text
```text:no-line-numbers
      62.10    0.000912           3       301           futex
```text
```text:no-line-numbers
      21.40    0.000314           2       144           epoll_wait
```text
```text:no-line-numbers
     100.00    0.001468           2       521        12 total
```text
```text:no-line-numbers
B3.  2210  10:14:03.101122 connect(9, {sa_family=AF_INET, sin_port=htons(6379),
```text
<details><summary>Ответ</summary>

Блокирующий connect к Redis 10.0.3.7:6379 ждал 127 с: SYN без ответа (DROP или хост
лёг), а в клиенте нет connect-таймаута. Два фикса: сеть/Redis и обязательный таймаут
в клиенте (сотни мс — секунда).

</details>

```text:no-line-numbers
           sin_addr=inet_addr("10.0.3.7")}, 16) = -1 ETIMEDOUT (Connection timed out) &lt;127.301220&gt;
```text
```text:no-line-numbers
B4.  3301  openat(AT_FDCWD, "/usr/lib/python3.12/json/__init__.cpython-312-x86_64-linux-gnu.so", …) = -1 ENOENT
```text
<details><summary>Ответ</summary>

Сотни ENOENT — поиск модулей Python, норма. Причина — последняя ошибка перед
Traceback: нет прав на чтение `/etc/app/tls.key` (EACCES). Проверить владельца/права,
пользователя сервиса (`User=` в юните), AppArmor.

</details>

```text:no-line-numbers
     … (ещё 214 строк ENOENT)
```text
```text:no-line-numbers
     3301  openat(AT_FDCWD, "/etc/app/tls.key", O_RDONLY|O_CLOEXEC) = -1 EACCES (Permission denied)
```text
```text:no-line-numbers
     3301  write(2, "Traceback (most recent call last"…, 35) = 35
```text
```text:no-line-numbers
     3301  exit_group(1)                           = ?
```text
```text:no-line-numbers
B5.  $ grep -E 'State|ctxt' /proc/4242/status; sleep 10; grep -E 'ctxt' /proc/4242/status
```text
<details><summary>Ответ</summary>

Счётчики не растут за 10 секунд — процесс не «медленно работает», а стоит.
`futex_wait_queue` — главный поток ждёт лок/condition. Нужны `-f` и `wchan` по потокам
и стек потоков (py-spy/jcmd/gdb): кто держит ресурс или кто должен разбудить (deadlock?).

</details>

```text:no-line-numbers
     State:  S (sleeping)
```text
```text:no-line-numbers
     voluntary_ctxt_switches:        90211
```text
```text:no-line-numbers
     nonvoluntary_ctxt_switches:     44
```text
```text:no-line-numbers
     voluntary_ctxt_switches:        90211
```text
```text:no-line-numbers
     nonvoluntary_ctxt_switches:     44
```text
```text:no-line-numbers
     $ cat /proc/4242/wchan  → futex_wait_queue
```text
```text:no-line-numbers
B6.  $ sudo echo w > /proc/sysrq-trigger
```text
<details><summary>Ответ</summary>

⚠️ `sudo` применяется к `echo`, а редирект `>` выполняет твой shell без root.
Правильно: `echo w | sudo tee /proc/sysrq-trigger` (или `sudo sh -c 'echo w > …'`).

</details>

```text:no-line-numbers
     bash: /proc/sysrq-trigger: Permission denied
```text
```text:no-line-numbers
B7.  # в контейнере: PID 1 = python app.py
```text
<details><summary>Ответ</summary>

Приложение — PID 1 в контейнере и не прибирает завершившихся детей → тысячи зомби,
каждый держит PID, упёрлись в `pids.max` → `fork` получает EAGAIN. Фикс: исправить
`wait`/`subprocess` в коде, запускать через `tini`/`docker run --init`, в k8s
`shareProcessNamespace: true` (PID 1 — pause).

</details>

```text:no-line-numbers
     $ ps -eo stat= | cut -c1 | sort | uniq -c
```text
```text:no-line-numbers
        4 S
```text
```text:no-line-numbers
     1987 Z
```text
```text:no-line-numbers
     app.log: OSError: [Errno 11] Resource temporarily unavailable (os.fork)
```text
```text:no-line-numbers
B8.  $ strace -p 4242
```text
<details><summary>Ответ</summary>

ptrace запрещён: без sudo при `kernel.yama.ptrace_scope=1` можно трейсить только своих
потомков; процесс уже трейсится другим (`grep TracerPid /proc/4242/status` ≠ 0 — gdb, другой
strace); в контейнере нет capability `SYS_PTRACE`. Решение: `sudo`, отцепить другой трейсер,
в k8s — `kubectl debug` с профилем `general`/`sysadmin`.

</details>

```text:no-line-numbers
     strace: attach: ptrace(PTRACE_SEIZE, 4242): Operation not permitted
```text
```text:no-line-numbers
B9.  [Sun Sep 27 03:12:44 2026] INFO: task postgres:2211 blocked for more than 120 seconds.
```text
<details><summary>Ответ</summary>

Postgres висит в `fdatasync`, ожидая коммита журнала ext4 (jbd2), а диск перегружен:
`w_await` 4 с, очередь 58, `%util` 100%. Причина — хранилище (соседняя нагрузка, IOPS-лимит
облачного диска, умирающий диск), а не Postgres. Дальше — тема 03: кто пишет (`iotop`,
`pidstat -d`), лимиты диска, `dmesg` на I/O errors.

</details>

```text:no-line-numbers
     … Call Trace: … jbd2_log_wait_commit … ext4_sync_file … __x64_sys_fdatasync
```text
```text:no-line-numbers
     $ iostat -xz 1 → vdb … w_await 4120.33 … aqu-sz 58.10 … %util 100.00
```text
```text:no-line-numbers
B10.  5110  11:02:10.300101 read(7&lt;TCP:[10.0.1.5:51234-&gt;10.0.2.9:443]>, …, 16384) = 512 &lt;29.998113&gt;
```text
<details><summary>Ответ</summary>

Каждый `read` из TLS-сокета к 10.0.2.9:443 длится ~30 с: наш процесс ждёт апстрим,
который отвечает медленно (или шлёт данные порциями раз в 30 с — keepalive/стриминг). Смотреть
апстрим и таймауты чтения в клиенте, `ss -ti` к этому адресу (rtt, retrans).

</details>

```text:no-line-numbers
     5110  11:02:40.299911 read(7&lt;TCP:[10.0.1.5:51234-&gt;10.0.2.9:443]>, …, 16384) = 498 &lt;29.999402&gt;
```text
```text:no-line-numbers
B11.  6001  fsync(12</var/lib/app/wal.log>) = 0 &lt;1.812440&gt;      # на каждую транзакцию
```text
<details><summary>Ответ</summary>

Каждая транзакция ждёт fsync 1,8 с — диск не держит sync-запись (облачный HDD, общий
том, writeback-шторм). Проверить `iostat -x` (`w_await`, `f_await`), dirty pages, тип диска;
в приложении — group commit/батчинг, если допустимо.

</details>

```text:no-line-numbers
B12.  # «Я запустил strace -f --seccomp-bpf -e trace=connect -p 4242 — теперь оверхед нулевой,
```text
<details><summary>Ответ</summary>

⚠️ `--seccomp-bpf` не применяется к процессам, подключённым через `-p`, — остановки
по-прежнему на каждом syscall, оверхед тот же. Для долгого наблюдения в проде — eBPF
(`tcpconnect-bpfcc -p 4242`) или `perf trace -e connect -p 4242`.

</details>

```text:no-line-numbers
     #  можно держать на проде весь день»
```text
---

### Блок C. Практика


### C1. 🔑 Найти, на чём ждёт медленное приложение
```text:no-line-numbers
cat > slow.py <<'EOF'
```text
```text:no-line-numbers
import socket, time, threading
```text
```text:no-line-numbers
def db():
```text
```text:no-line-numbers
    while True:
```text
```text:no-line-numbers
        s = socket.socket(); s.settimeout(3)
```text
```text:no-line-numbers
        try: s.connect(("10.255.255.1", 5432))      # «база» не отвечает
```text
```text:no-line-numbers
        except OSError: pass
```text
```text:no-line-numbers
        s.close()
```text
```text:no-line-numbers
def work():
```text
```text:no-line-numbers
    while True:
```text
```text:no-line-numbers
        open("/etc/hostname").read(); time.sleep(0.5)
```text
```text:no-line-numbers
threading.Thread(target=db, daemon=True).start()
```text
```text:no-line-numbers
work()
```text
```text:no-line-numbers
EOF
```text
```text:no-line-numbers
python3 slow.py &
```text
Сними `strace -f -tt -T -y` с процесса, найди поток, который ждёт, и назови: какой syscall,
сколько длится, куда подключается. Затем повтори без `-f` и объясни разницу.

### C2. 🔑 `-c` против `-c -w`
Запусти скрипт, где 4 потока соревнуются за один лок и держат его по 200 мс
(`threading.Lock` + `time.sleep(0.2)` внутри). Сними `strace -c -f` и `strace -c -w -f`
по 10 секунд. Сравни верхние строки и объясни, почему `futex` меняет место.

### C3. Какие файлы читает программа
Выясни, какой файл с корневыми сертификатами открывает `curl https://example.com`
и какие конфиги читает `ssh -G localhost`, используя `-e trace=%file` и `-Z`/`-z`.

### C4. 🔑 D-state через dm-delay (⚠️ VM)
**1.** Создай `/dev/mapper/slow` поверх `/dev/vdb` (задержка 100 мс), ext4, смонтируй в `/mnt/slow`.

<details><summary>Ответ</summary>

```bash
P=$(pgrep -f slow.py)
sudo strace -f -tt -T -y -p $P 2>&1 | head -30
# поток db: connect(3&lt;TCP:[…]&gt;, {…htons(5432)…"10.255.255.1"…}) = -1 EINPROGRESS
#           poll([{fd=3, events=POLLOUT}], 1, 3000) = 0 (Timeout) &lt;3.003…&gt;
# главный поток: openat(…"/etc/hostname"…) … clock_nanosleep(…) &lt;0.500…&gt;
sudo strace -tt -T -p $P 2>&1 | head     # без -f: только главный поток, poll/connect не видно
kill $P
```text
Вывод: поток db каждые 3 с ждёт неблокирующий connect к 10.255.255.1:5432 и получает таймаут.
Без `-f` strace цепляется только к указанному TID (главный поток) и показывает безобидные
`openat` + `sleep`.

</details>

**2.** Понизь порог: `sudo sysctl kernel.hung_task_timeout_secs=30`.

<details><summary>Ответ</summary>

```bash
cat > lock.py <<'EOF'
import threading, time
L = threading.Lock()
def w():
    while True:
        with L: time.sleep(0.2)
for _ in range(4): threading.Thread(target=w, daemon=True).start()
time.sleep(3600)
EOF
python3 lock.py & P=$!
sudo timeout -s INT 10 strace -c -f -p $P
sudo timeout -s INT 10 strace -c -w -f -p $P
```text
Без `-w` времена крошечные (CPU ядра), наверху может оказаться что угодно. С `-w` наверху
`futex` (потоки ждут лок) и `clock_nanosleep` (держатель лока спит) — секунды. `futex`
поднимается, потому что учитывается время ожидания, а не CPU.

</details>

**3.** `sudo dmsetup suspend slow`, затем запись с `oflag=direct` в фоне.

<details><summary>Ответ</summary>

```bash
strace -f -e trace=%file -z -o c.log curl -s -o /dev/null https://example.com
grep -E '\.(pem|crt)|certs' c.log      # /etc/ssl/certs/ca-certificates.crt (Ubuntu)
strace -e trace=%file -o s.log ssh -G localhost >/dev/null
grep -E 'ssh_config|\.ssh' s.log       # /etc/ssh/ssh_config, /etc/ssh/ssh_config.d/*.conf, ~/.ssh/config
```text
`-z` оставляет только успешные открытия (реально прочитанные файлы), `-Z` — только
неудачные (что искалось, но не нашлось).

</details>

**4.** Сними: `ps` с `wchan`, `/proc/PID/stack`, `vmstat 1 3` (колонка `b`), `cat /proc/loadavg`.

<details><summary>Ответ</summary>

```bash
sudo modprobe dm-delay
SZ=$(sudo blockdev --getsz /dev/vdb)
echo "0 $SZ delay /dev/vdb 0 100" | sudo dmsetup create slow
sudo mkfs.ext4 -q /dev/mapper/slow; sudo mkdir -p /mnt/slow; sudo mount /dev/mapper/slow /mnt/slow
sudo sysctl kernel.hung_task_timeout_secs=30
sudo dmsetup suspend slow
sudo dd if=/dev/zero of=/mnt/slow/f bs=1M count=10 oflag=direct &
sleep 2; D=$(pgrep -x dd)
ps -o pid,stat,wchan:32,cmd -p $D          # D, percpu_rwsem_wait (ФС заморожена)
sudo cat /proc/$D/stack                     # … percpu_rwsem_wait … vfs_write … ksys_write
vmstat 1 3                                  # b = 1; cat /proc/loadavg — LA растёт к 1+
sudo kill -9 $D; sleep 1; ps -o stat= -p $D # всё ещё D
sleep 35; sudo dmesg -T | grep -A12 'blocked for more than'
echo w | sudo tee /proc/sysrq-trigger; sudo dmesg -T | tail -30
sudo dmsetup resume slow; sleep 1; ps -p $D || echo "dd завершился"
sudo sysctl kernel.hung_task_timeout_secs=120
sudo umount /mnt/slow; sudo dmsetup remove slow
```text
Ожидаемо: D-state без реакции на SIGKILL, `b` в vmstat, hung_task через ~30 с,
sysrq-w показывает dd; после resume процесс умирает от отложенного SIGKILL.

</details>

**5.** Попробуй `kill -9`. Дождись hung_task в `dmesg`, сделай sysrq-w.

<details><summary>Ответ</summary>

```bash
sudo mkdir -p /srv/nfs /mnt/nfs && echo hi | sudo tee /srv/nfs/a >/dev/null
echo '/srv/nfs 127.0.0.1(rw,sync,no_subtree_check)' | sudo tee /etc/exports
sudo exportfs -ra && sudo systemctl start nfs-server
sudo mount -t nfs 127.0.0.1:/srv/nfs /mnt/nfs && mount | grep /mnt/nfs    # видно hard
sudo systemctl stop nfs-server
ls /mnt/nfs & sleep 5
ps -o pid,stat,wchan:32,cmd -C ls           # D, rpc_wait_bit_killable (или nfs_*)
kill -9 %1; sleep 1; jobs                   # убился — TASK_KILLABLE
sudo dmesg -T | grep -i nfs                 # nfs: server 127.0.0.1 not responding, still trying
sudo systemctl start nfs-server; ls /mnt/nfs; sudo umount /mnt/nfs
```text
Если `ls` успел закэшироваться и не повис — обратись к новому пути (`stat /mnt/nfs/a`)
или подожди истечения кэша атрибутов. hung_task при этом не сработает (killable).

</details>

**6.** `sudo dmsetup resume slow`, верни `hung_task_timeout_secs=120`, убери за собой.

<details><summary>Ответ</summary>

```bash
python3 -c 'import os,time; [os.fork() or os._exit(0) for _ in range(5)]; time.sleep(600)' & PP=$!
ps -eo ppid=,stat= | awk '$2 ~ /^Z/ {print $1}' | sort | uniq -c    # "5 $PP"
Z=$(ps -eo pid=,stat= | awk '$2 ~ /^Z/ {print $1; exit}'); kill -9 $Z; ps -o pid,stat -p $Z  # Z остался
kill $PP; sleep 1; ps -eo stat= | grep -c '^Z'                       # 0: прибрал PID 1
sudo systemd-run --scope -p TasksMax=20 python3 -c \
  'import os,time; [os.fork() or os._exit(0) for _ in range(50)]; time.sleep(5)'
```text
Последняя команда падает с `BlockingIOError: [Errno 11] Resource temporarily unavailable`:
зомби держат PID, и на 20-м упираемся в `pids.max` scope.

</details>

### C5. NFS hard-mount и TASK_KILLABLE (⚠️ VM)
Подними NFS-экспорт на самой VM (`/srv/nfs` → `127.0.0.1`), смонтируй в `/mnt/nfs`
(hard по умолчанию), останови `nfs-server` и выполни `ls /mnt/nfs &`. Посмотри state и
`wchan`, попробуй `kill -9`, найди сообщения ядра. Верни сервер и размонтируй.

### C6. 🔑 Зомби и лимит PID
**1.** Запусти генератор зомби из конспекта, найди родителя и число зомби у него.

<details><summary>Ответ</summary>

```bash
P=$(pgrep -f slow.py)
sudo strace -f -tt -T -y -p $P 2>&1 | head -30
# поток db: connect(3&lt;TCP:[…]&gt;, {…htons(5432)…"10.255.255.1"…}) = -1 EINPROGRESS
#           poll([{fd=3, events=POLLOUT}], 1, 3000) = 0 (Timeout) &lt;3.003…&gt;
# главный поток: openat(…"/etc/hostname"…) … clock_nanosleep(…) &lt;0.500…&gt;
sudo strace -tt -T -p $P 2>&1 | head     # без -f: только главный поток, poll/connect не видно
kill $P
```text
Вывод: поток db каждые 3 с ждёт неблокирующий connect к 10.255.255.1:5432 и получает таймаут.
Без `-f` strace цепляется только к указанному TID (главный поток) и показывает безобидные
`openat` + `sleep`.

</details>

**2.** `kill -9` одному зомби — что изменилось?

<details><summary>Ответ</summary>

```bash
cat > lock.py <<'EOF'
import threading, time
L = threading.Lock()
def w():
    while True:
        with L: time.sleep(0.2)
for _ in range(4): threading.Thread(target=w, daemon=True).start()
time.sleep(3600)
EOF
python3 lock.py & P=$!
sudo timeout -s INT 10 strace -c -f -p $P
sudo timeout -s INT 10 strace -c -w -f -p $P
```text
Без `-w` времена крошечные (CPU ядра), наверху может оказаться что угодно. С `-w` наверху
`futex` (потоки ждут лок) и `clock_nanosleep` (держатель лока спит) — секунды. `futex`
поднимается, потому что учитывается время ожидания, а не CPU.

</details>

**3.** Убери зомби правильно.

<details><summary>Ответ</summary>

```bash
strace -f -e trace=%file -z -o c.log curl -s -o /dev/null https://example.com
grep -E '\.(pem|crt)|certs' c.log      # /etc/ssl/certs/ca-certificates.crt (Ubuntu)
strace -e trace=%file -o s.log ssh -G localhost >/dev/null
grep -E 'ssh_config|\.ssh' s.log       # /etc/ssh/ssh_config, /etc/ssh/ssh_config.d/*.conf, ~/.ssh/config
```text
`-z` оставляет только успешные открытия (реально прочитанные файлы), `-Z` — только
неудачные (что искалось, но не нашлось).

</details>

**4.** Запусти генератор на 50 форков внутри `sudo systemd-run --scope -p TasksMax=20 …`
   и объясни ошибку.

<details><summary>Ответ</summary>

```bash
sudo modprobe dm-delay
SZ=$(sudo blockdev --getsz /dev/vdb)
echo "0 $SZ delay /dev/vdb 0 100" | sudo dmsetup create slow
sudo mkfs.ext4 -q /dev/mapper/slow; sudo mkdir -p /mnt/slow; sudo mount /dev/mapper/slow /mnt/slow
sudo sysctl kernel.hung_task_timeout_secs=30
sudo dmsetup suspend slow
sudo dd if=/dev/zero of=/mnt/slow/f bs=1M count=10 oflag=direct &
sleep 2; D=$(pgrep -x dd)
ps -o pid,stat,wchan:32,cmd -p $D          # D, percpu_rwsem_wait (ФС заморожена)
sudo cat /proc/$D/stack                     # … percpu_rwsem_wait … vfs_write … ksys_write
vmstat 1 3                                  # b = 1; cat /proc/loadavg — LA растёт к 1+
sudo kill -9 $D; sleep 1; ps -o stat= -p $D # всё ещё D
sleep 35; sudo dmesg -T | grep -A12 'blocked for more than'
echo w | sudo tee /proc/sysrq-trigger; sudo dmesg -T | tail -30
sudo dmsetup resume slow; sleep 1; ps -p $D || echo "dd завершился"
sudo sysctl kernel.hung_task_timeout_secs=120
sudo umount /mnt/slow; sudo dmsetup remove slow
```text
Ожидаемо: D-state без реакции на SIGKILL, `b` в vmstat, hung_task через ~30 с,
sysrq-w показывает dd; после resume процесс умирает от отложенного SIGKILL.

</details>

### C7. Дамп Python-потоков py-spy
Возьми скрипт из C2, сделай `py-spy dump --pid` и `py-spy top --pid`. Найди поток,
держащий лок, и потоки, которые ждут. Сравни с тем, что показывал strace.

### C8. gdb: стек и пауза
Запусти `sleep 300 &`, сними стек `gdb -p … -batch -ex 'thread apply all bt'`.
Затем запусти `ping 127.0.0.1` в одном терминале и сними с него gdb в другом (без `-batch`,
подожди 5 секунд перед `quit`). Что увидел в выводе ping?

### C9. Цена strace в цифрах
Сравни время `dd if=/dev/zero of=/dev/null bs=1 count=500000`: без трассировки,
под `strace -c`, под `strace -c -e trace=write`, под `sudo perf trace -s`. Сведи в таблицу.

---

### Блок D. Инциденты


**D1.** Нода Kubernetes: LA 40 на 4 vCPU, CPU idle 85%, `kubectl exec` в под с общим томом
висит на `ls /mnt/shared`. Твой план?

<details><summary>Ответ</summary>

LA при простое CPU — D-state. `ps -eo pid,stat,wchan:32,cmd | awk '$2 ~ /^D/'` на ноде:
если wchan `rpc_*`/`nfs_*` — сетевое хранилище общего тома. `dmesg -T | grep -iE 'nfs|blocked'`,
`mount | grep /mnt/shared` (hard?), связь с сервером (`ping`, `rpcinfo`, `nc -zv srv 2049`).
Смягчение: чинить/переключать хранилище; поды с этим томом переносить; `umount -l` как
крайняя мера. После — алерт на число D-процессов и на доступность хранилища.

</details>

**D2.** Сервис перестал отвечать: CPU 0%, память стабильна, в логах тишина с 14:02.
Что делаешь по шагам до рестарта?

<details><summary>Ответ</summary>

1) `ps -o pid,stat,wchan:32 -p PID` и `ctxt_switches` дважды — стоит или работает.

</details>

**D3.** После переезда в новую подсеть приложение стартует 40 секунд вместо 2. В логах
ничего. Как найти причину за 5 минут?

<details><summary>Ответ</summary>

`strace -f -tt -T -e trace=%net -o start.log ./app`, отфильтровать вызовы дольше 1 с.
Типично: повторные таймауты `poll` по 5 с на сокете к порту 53 — первый DNS-сервер
в `/etc/resolv.conf` из старой сети недоступен; или `connect` к старому адресу
конфиг-сервера/LDAP. Исправить resolv.conf/адреса, добавить таймауты.

</details>

**D4.** В поде падают воркеры с `fork: Resource temporarily unavailable`, `ps` в контейнере
показывает тысячи `&lt;defunct&gt;`. Причина и исправление на уровне образа/манифеста?

<details><summary>Ответ</summary>

PID 1 в контейнере — приложение без обработки SIGCHLD; дети (shell-обёртки,
subprocess) становятся зомби, исчерпывают `pids.max` пода. Исправление: `tini` как ENTRYPOINT
(или `docker run --init`), в k8s `shareProcessNamespace: true`, в коде — `wait()`/`communicate()`
для каждого subprocess. Проверка: `ps -eo stat= | grep -c ^Z` после деплоя = 0.

</details>

**D5.** Каждую ночь в 03:10 зависает скрипт бэкапа: state D, `wchan` = `percpu_rwsem_wait`,
днём всё нормально. В 03:00 запускается агент снапшотов облака. Гипотеза и проверка?

<details><summary>Ответ</summary>

Агент снапшотов делает `fsfreeze` (или snapshot с заморозкой ФС) и иногда не
размораживает/делает это долго — все записи в ФС ждут в `percpu_rwsem_wait`. Проверить:
логи агента, `journalctl` около 03:00, `dmesg` hung_task со стеком `__percpu_down_read`,
воспроизвести `sudo fsfreeze -f /mnt; echo x > /mnt/t &` на VM. Фикс: развести окна бэкапа
и снапшота, таймаут/`fsfreeze -u` в агенте, алерт на D-процессы.

</details>

**D6.** Инженер на пике трафика прицепил `strace -f` к nginx на 10 минут «посмотреть» —
p99 вырос в 8 раз, пошли таймауты. Что в постмортем и какие action items?

<details><summary>Ответ</summary>

Влияние: p99 ×8, таймауты, сколько бюджета SLO съедено. Contributing factors: strace
замедляет каждый syscall, а nginx syscall-тяжёлый; нет правил для отладки на проде; нет
безопасного инструмента. Action items: runbook «отладка на проде» (strace — только секунды,
`-o`, один воркер, вне пика); eBPF-инструменты на нодах (`syscount-bpfcc`, `tcplife-bpfcc`,
bpftrace); отладочный стенд/канарейка для экспериментов; blameless — система позволила.

</details>

**D7.** Java-сервис: запросы висят, strace показывает у всех потоков `futex` и ничего больше.
Что дальше?

<details><summary>Ответ</summary>

Снять дамп потоков: `jcmd PID Thread.print` (или `jstack PID`) 2–3 раза с паузой

</details>

**D8.** Процесс после `kill -9` 10 минут остаётся в D, менеджер требует перезагрузить сервер.
Как принять решение?

<details><summary>Ответ</summary>

Сначала понять, чего ждёт процесс: `wchan`, `/proc/PID/stack`, `dmesg` (I/O error,
NFS, reset контроллера), `iostat -x`. Если хранилище можно починить (вернуть NFS, resume
устройства, переподключить том) — процесс «отомрёт» сам. Если диск/драйвер мёртв и влияние
значимое — перезагрузка оправдана, но после сохранения доказательств (стеки, dmesg) и
failover трафика. Ребут «вслепую» не лечит умирающий диск и стирает улики.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Процесс завис. Твои действия?

<details><summary>Ответ</summary>

Состояние (`ps -o stat,wchan`), растут ли context switches; дальше по состоянию:
   R — профайлер, S — `strace -f -tt -T -p`, D — стек ядра и dmesg, Z — родитель.
   Сохранить доказательства, потом рестарт/failover, потом первопричина.

</details>

**2.** Что такое D-state и почему такой процесс нельзя убить?

<details><summary>Ответ</summary>

Ожидание в ядре в `TASK_UNINTERRUPTIBLE` — чаще всего I/O: диск, NFS, замороженная ФС.
   Сигналы обрабатываются при возврате в user space, а ядро не будит такую задачу, поэтому
   SIGKILL ждёт конца I/O. Входит в load average. Лечится устранением причины I/O.

</details>

**3.** Что такое зомби-процесс и как от него избавиться?

<details><summary>Ответ</summary>

Завершившийся процесс, код возврата которого не забрал родитель (`wait`). Убить нельзя —
   он мёртв. Чинить родителя: `wait`/SIGCHLD или перезапуск (зомби перейдут к PID 1).
   Опасность — исчерпание PID.

</details>

**4.** Как пользоваться strace и почему с ним осторожно в проде?

<details><summary>Ответ</summary>

`strace -f -tt -T -y -p PID -o file`, `-c -w` для сводки. Осторожно: ptrace останавливает
   процесс на каждом syscall — замедление в разы; в проде — секунды, или perf trace/eBPF.

</details>

**5.** Как по strace понять, что проблема в сети, в диске или в локах?

<details><summary>Ответ</summary>

Сеть: `connect`/`poll` на сокетах с таймаутами, ECONNREFUSED/ETIMEDOUT, долгие `read`
   из TCP, запросы на порт 53. Диск: долгие `fsync`/`fdatasync`/`write` в файлы. Локи:
   `futex` с большим wall-временем.

</details>

**6.** Что такое hung task и sysrq?

<details><summary>Ответ</summary>

Hung task — встроенный детектор задач в D-состоянии дольше `hung_task_timeout_secs`
   (120 с), пишет стек в dmesg. SysRq — «магические» команды ядра; через `/proc/sysrq-trigger`
   `w` показывает все заблокированные задачи; опасные буквы (`c`, `b`, `o`, `e`, `i`) — нельзя.

</details>

**7.** Высокий load average при простаивающем CPU — что это?

<details><summary>Ответ</summary>

В Linux LA = R + D. Если CPU простаивает — много D: I/O, NFS, замороженная ФС.
   Проверить `vmstat` (колонка `b`), `ps` с wchan, `iostat -x`, `dmesg`.

</details>

**8.** Как снять стек потоков у Java/Python/Go-процесса без перезапуска?

<details><summary>Ответ</summary>

Java — `jcmd PID Thread.print`/`jstack`; Python — `py-spy dump --pid`; Go — pprof
   (`/debug/pprof/goroutine?debug=2`); нативное — `gdb -p PID -batch -ex 'thread apply all bt'`
   (останавливает процесс на время снятия).

</details>

**9.** Чем strace отличается от ltrace и perf trace?

<details><summary>Ответ</summary>

strace — системные вызовы через ptrace (дорого); ltrace — вызовы библиотек через PLT
   (ещё дороже, не видит статические бинари); perf trace — syscalls через tracepoints
   ядра с малым оверхедом.

</details>

**10.** Почему в контейнерах бывают зомби и как с этим борются?

<details><summary>Ответ</summary>

PID 1 в контейнере — приложение, которое не прибирает осиротевших потомков и не
    обрабатывает сигналы как init. Решения: tini/`--init`, `shareProcessNamespace` в поде,
    правильный `wait` в коде.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] По состоянию процесса выбираю инструмент: R/S/D/Z/T
- [ ] Отличаю «стоит» от «медленно работает» по `ctxt_switches`
- [ ] Снимаю `strace -f -tt -T -y -p` и нахожу долгий вызов и поток
- [ ] ⭐ Помню, что `strace -c` без `-w` не показывает ожидания
- [ ] Читаю типовые syscalls: ENOENT/EACCES, EINPROGRESS+poll, ETIMEDOUT, futex, fsync
- [ ] Знаю цену strace и когда брать `perf trace`/eBPF
- [ ] Для D-процесса нахожу `wchan`, стек ядра, hung_task и делаю sysrq-w
- [ ] Отличаю `TASK_KILLABLE` (NFS) от настоящего uninterruptible
- [ ] Нахожу родителя зомби и убираю зомби без перезагрузки
- [ ] Снимаю стек через gdb `-batch`, py-spy dump, знаю jcmd и pprof
