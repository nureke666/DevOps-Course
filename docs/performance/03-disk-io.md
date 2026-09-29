---
title: "03. Диск и I/O: latency, page cache и «куда делось место»"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 03. Опирается на"
---

# 03. Диск и I/O: latency, page cache и «куда делось место»

> Блок → Deep Linux Troubleshooting & Performance → тема 03. Опирается на
> [../Linux/10_the_filesystem.md](/linux/10-the-filesystem) (ФС, inodes, алгоритм «диск заполнен»),
> [../Linux/09_devices.md](/linux/09-devices) (блочные устройства, `/sys`),
> [../Linux/14_process_utilization.md](/linux/14-process-utilization) (основы `iostat`, `iotop`, `lsof +L1`)
> и [01_methodology.md](/performance/01-methodology) (USE для диска).
>
> **После темы ты умеешь:** читать `iostat -x` по каждой колонке и не верить `%util` на SSD,
> находить процесс, который грузит диск, смотреть latency гистограммой, честно мерить диск
> fio, объяснять dirty pages и writeback-штормы, находить «съеденное» место (deleted-файлы,
> inodes, reserved blocks, файлы под точкой монтирования) и освобождать его без рестарта.

---

## 🗺️ Карта темы

```text
 приложение: read()/write()/fsync()          ◄── pidstat -d, iotop, /proc/PID/io  (КТО)
        │
        ▼
 VFS + page cache ── чтение из кэша: диск не трогаем     ◄── free, cachestat, /proc/meminfo
        │            запись: страница стала dirty и write() уже вернулся
        │   flusher (kworker/…flush) по dirty_* таймерам и порогам
        ▼
 ФС (ext4/xfs) + журнал (jbd2)               ◄── dmesg: EXT4-fs error, remount ro
        │
        ▼
 block layer: планировщик (none/mq-deadline/bfq), очередь   ◄── iostat -x (СКОЛЬКО и КАК ДОЛГО)
        │                                                    ◄── biolatency, biosnoop (РАСПРЕДЕЛЕНИЕ)
        ▼
 устройство: HDD / SSD / NVMe / облачный том (лимиты IOPS и MB/s)   ◄── fio (ПРЕДЕЛ)
```text
Главный вывод схемы: **latency приложения ≠ latency диска**. Буферизованная запись
возвращается за микросекунды (в page cache), а платит за неё потом `fsync()` или flusher.
Чтение из кэша вообще не видно в `iostat`.

---

## 1. USE для диска: что именно мерить

| | Метрика | Команда |
|---|---------|---------|
| **U**tilization | Доля времени, когда в устройстве была хотя бы одна операция | `iostat -x` → `%util` (⚠️ см. раздел 3) |
| **S**aturation | Очередь и ожидание | `aqu-sz`, `r_await`/`w_await`, процессы в `D`, `/proc/pressure/io` |
| **E**rrors | Ошибки устройства и ФС | `dmesg -T \| grep -iE 'I/O error\|EXT4-fs\|XFS'`, `smartctl -a`, `nvme smart-log` |

Для диска saturation почти всегда важнее utilization: пользователь чувствует `await`,
а не проценты. Откуда брать «норму» — из замера fio (раздел 6) и из истории
`sar -d -f /var/log/sysstat/saDD`.

---

## 2. `iostat -x` по колонкам

Основы — в [../Linux/14_process_utilization.md](/linux/14-process-utilization). Здесь — каждая колонка
(sysstat 12.6, Ubuntu 24.04) и что из неё следует.

```bash
iostat -xz 1            # -x расширенно, -z скрыть простаивающие устройства; 1 с
iostat -dxz vdb 1       # только отчёт по устройствам и только vdb
iostat -xz -p vdb 1     # плюс разделы (vdb1, vdb2…)
iostat -xz 1 --human    # размеры в k/M/G
```text
> ⚠️ Первый отчёт — средние **с момента загрузки**. Смотри со второго.

```text
# пример вывода: fio randread 4k, iodepth=32 на /dev/vdb (VM, колонки d/s…dareq-sz скрыты)
Device     r/s     rkB/s  rrqm/s %rrqm r_await rareq-sz  w/s  wkB/s … f/s f_await  aqu-sz  %util
vdb   18950.00  75800.00    0.00  0.00    1.68     4.00 0.00   0.00 … 0.00    0.00   31.84 100.00
```text
| Колонка | Что это | Как читать |
|---------|---------|-----------|
| `r/s`, `w/s` | Завершённые запросы чтения/записи в секунду (IOPS) — **после** слияния | Сравнивай с пределом из fio / лимитом облачного тома |
| `rkB/s`, `wkB/s` | Пропускная способность | Упёрлась в предел при низких IOPS → узкое место — MB/s |
| `rrqm/s`, `wrqm/s` | Сколько запросов в секунду **слили** с соседними до отправки в устройство | Много слияний → поток последовательный |
| `%rrqm`, `%wrqm` | Доля слитых запросов | ≈ 0% на random 4k — норма |
| `rareq-sz`, `wareq-sz` | Средний размер запроса, КБ (раньше `avgrq-sz` в секторах) | 4 КБ → random, 128–1024 КБ → sequential |
| `r_await`, `w_await` | Среднее время запроса, мс: **очередь + обслуживание** | Главная колонка «насколько больно». Сравнивай с базой устройства |
| `d/s`, `dkB/s`, `d_await` … | То же для discard (TRIM) | Всплески при `fstrim` по расписанию |
| `f/s`, `f_await` | Flush-запросы (сброс кэша устройства: `fsync`, журнал) | Высокий `f_await` → медленный `fsync` → тормозят БД и etcd |
| `aqu-sz` | Средняя длина очереди (раньше `avgqu-sz`) | Устойчиво ≫ 1 на HDD или ≫ глубины, которую держит устройство → насыщение |
| `%util` | Доля времени, когда была **хотя бы одна** операция в полёте | Для HDD 100% = полка. Для SSD/NVMe/RAID — нет (раздел 3) |

Колонки `svctm` больше нет — sysstat убрал её как недостоверную: время обслуживания
из этих счётчиков честно не вычисляется.

**Проверка на честность — закон Литтла:** `aqu-sz ≈ (r/s + w/s) × await / 1000`.
В примере: 18 950 × 1,68 / 1000 ≈ 31,8 — совпадает с `aqu-sz` и с `iodepth=32` у fio.
Если числа не сходятся — ты неправильно понял, что меряешь (например, смотришь не то устройство).

Типовые картины:

| Картина в `iostat -x` | Что это |
|------------------------|---------|
| `w/s` 800, `wareq-sz` 128, `w_await` 40, `aqu-sz` 35, `%util` 99 | Writeback-шторм или бэкап: крупная последовательная запись забила очередь |
| `r/s` 3000, `rareq-sz` 4, `r_await` 0,3 | Здоровый random read с SSD |
| `r/s` 150, `rareq-sz` 4, `r_await` 12, `%util` 100 | HDD в полке на random read (≈ 150 IOPS — предел шпинделя) |
| IOPS ровно 3000 минуту подряд, `await` растёт | Упёрлись в лимит облачного тома (например, базовые 3000 IOPS у gp3) |
| `f/s` 200, `f_await` 25 | Приложение делает много `fsync` на медленном носителе |
| Всё по нулям, а приложение «ждёт диск» | Чтения попадают в кэш, либо ждёт сеть/NFS/блокировку — смотри тему 05 |

---

## 3. Почему `%util` врёт на SSD, NVMe и RAID

`%util` считается из счётчика «время, когда в устройстве был хотя бы один запрос».
Он не знает, **сколько** запросов устройство обслуживает параллельно.

```text
 HDD: одна головка                         NVMe: десятки параллельных очередей
 ┌─────────────────────────┐               ┌─────────────────────────┐
 │ ███ ███ ███ ███ ███ ███ │  util 100%    │ ███                     │  util 100% (всегда был ≥1 запрос)
 └─────────────────────────┘  = предел     │ ██                      │  но занята малая часть «полос»
                                           │ █                       │  → запас ещё в разы
                                           └─────────────────────────┘
```text
Это прямо написано в `man iostat`: насыщение наступает при `%util` около 100% для устройств,
обслуживающих запросы последовательно, а для параллельных (RAID, современные SSD) это число
**не отражает** предела производительности.

Что смотреть вместо `%util` на SSD/NVMe:
1. `r_await`/`w_await` против базы (свой замер fio при низкой нагрузке).
2. `aqu-sz` против глубины, при которой в fio latency начинала резко расти.
3. IOPS и MB/s против предела устройства или лимита облачного тома.
4. `some`/`full` в `/proc/pressure/io` — сколько времени задачи реально ждали I/O (PSI, тема 06).

---

## 4. Кто грузит диск: `pidstat -d`, `iotop`, `/proc/PID/io`

```bash
pidstat -d 1                 # по процессам, раз в секунду
sudo iotop -oPa              # только активные, по процессам, накопительно
sudo cat /proc/1234/io       # счётчики конкретного процесса
```text
```text
# пример вывода pidstat -d 1
02:18:15 PM   UID       PID   kB_rd/s   kB_wr/s kB_ccwr/s iodelay  Command
02:18:16 PM   999      1811      0.00  48212.00      0.00     187  postgres
02:18:16 PM     0       412      0.00    512.00      0.00       0  jbd2/vda1-8
```text
| Колонка | Смысл |
|---------|-------|
| `kB_rd/s` | Чтение, которое реально ушло на устройство (промах кэша) |
| `kB_wr/s` | Запись, которую процесс **вызвал** (учитывается при загрязнении страницы, даже если на диск её потом отнёс flusher) |
| `kB_ccwr/s` | Отменённая запись: процесс загрязнил страницы, а потом удалил/обрезал файл до сброса |
| `iodelay` | Сколько тактов процесс ждал синхронный block I/O и swap-in. ⚠️ Нужен `kernel.task_delayacct=1` (на стенде включён), иначе всегда 0 |

`/proc/PID/io`: `rchar`/`wchar` — все байты через `read`/`write`, **включая кэш и сокеты**;
`read_bytes`/`write_bytes` — то, что дошло до блочного слоя. Большой `rchar` при нулевом
`read_bytes` = процесс читает из page cache, диск ни при чём.

`jbd2/vda1-8` в топе `iotop` — это журнал ext4. Его много, когда приложение часто делает
`fsync`/`O_SYNC` мелкими порциями: каждая синхронная запись — коммит журнала.
`kworker/u…:flush-252:16` — flusher пишет dirty-страницы (раздел 7).

> 💡 Колонка `IO>` в `iotop` («сколько процентов времени поток ждал I/O») тоже требует
> `kernel.task_delayacct=1`. Без неё `iotop` честно предупредит, что считать её не может.

---

## 5. Latency распределением: `biolatency` и `biosnoop` (превью темы 07)

`iostat` даёт среднее, а среднее прячет хвост: 99% запросов по 0,2 мс и 1% по 200 мс
в среднем дают «нормальные» 2 мс. Гистограмма показывает правду.

```bash
sudo biolatency-bpfcc -D 10 1      # гистограмма latency по каждому диску, 10 с, один отчёт
sudo biolatency-bpfcc -m -D        # в миллисекундах, до Ctrl+C
sudo biosnoop-bpfcc                # каждый запрос отдельной строкой
sudo biosnoop-bpfcc -Q             # + время в очереди ОС (QUE(ms))
```text
```text
# пример вывода biolatency-bpfcc -D 10 1 (часть запросов к vdb медленная; пустые корзины опущены)
disk = vdb
     usecs               : count     distribution
       128 -> 255        : 1812     |****************************************|
       256 -> 511        : 903      |*******************                     |
       512 -> 1023       : 64       |*                                       |
     32768 -> 65535      : 97       |**                                      |
     65536 -> 131071     : 41       |                                        |
```text
Два горба: основная масса — сотни микросекунд, а ~5% запросов — десятки миллисекунд.
Среднее из `iostat` (≈ 3 мс) такого не покажет.

```text
# пример вывода biosnoop-bpfcc
TIME(s)     COMM           PID     DISK      T SECTOR     BYTES   LAT(ms)
0.000000    postgres       1811    vdb       W 4196352    8192       0.41
0.001270    jbd2/vda1-8    412     vda       W 20981760   4096       0.62
0.013842    postgres       1811    vdb       R 1053184    8192      51.03
```text
`T` — тип (R/W), `LAT(ms)` — от отправки в устройство до завершения. Так находишь,
**какой процесс** получает медленные запросы и к какому диску. Подробно — [07_ebpf_bpftrace.md](/performance/07-ebpf-bpftrace).

---

## 6. fio: мерить диск, а не гадать

`dd` меряет одну последовательную запись через кэш и почти ничего не говорит о реальной
нагрузке ([../Linux/09_devices.md](/linux/09-devices)). fio задаёт профиль: тип доступа,
размер блока, глубину очереди и обход кэша.

> ⚠️ Тест — **на файле** (`--filename=… --size=…`) или на пустом выделенном устройстве
> стенда. Никогда не запускай fio с записью на устройство с данными или смонтированной ФС —
> это перезапишет их. На проде — только чтение или файл в свободном каталоге и вне пиковых часов.

```bash
mkdir -p ~/perf/fio && cd ~/perf/fio

# 1. Latency случайного чтения (одна операция в полёте) — «как быстро отвечает диск»
fio --name=lat --filename=fio.test --size=1G --rw=randread --bs=4k \
    --iodepth=1 --ioengine=libaio --direct=1 --runtime=30 --time_based --group_reporting

# 2. Предел IOPS случайного чтения — очередь глубокая
fio --name=iops --filename=fio.test --size=1G --rw=randread --bs=4k \
    --iodepth=32 --ioengine=libaio --direct=1 --runtime=30 --time_based --group_reporting

# 3. Предел последовательного чтения, MB/s
fio --name=seq --filename=fio.test --size=1G --rw=read --bs=1M \
    --iodepth=8 --ioengine=libaio --direct=1 --runtime=30 --time_based --group_reporting

# 4. «Как etcd/БД»: мелкая запись + fdatasync после каждой (профиль из документации etcd)
fio --name=fsync --directory=. --size=22m --bs=2300 --rw=write \
    --ioengine=sync --fdatasync=1
```text
| Параметр | Зачем |
|----------|-------|
| `--rw=randread/randwrite/read/write/randrw` | Random или sequential — у дисков это разные миры |
| `--bs` | 4k — БД и мелкие файлы; 1M — бэкапы, стриминг |
| `--iodepth` | Сколько запросов держим в полёте. Работает только с асинхронным движком |
| `--ioengine=libaio` / `io_uring` | Асинхронный I/O; `sync`/`psync` — по одному запросу |
| `--direct=1` | Мимо page cache. Без него меряешь RAM, а не диск |
| `--time_based --runtime` | Фиксированное время вместо «прочитать файл один раз» |

```text
# пример вывода (фрагмент), профиль 2 на VM
iops: (groupid=0, jobs=1): err= 0: pid=2412: Sun Sep 27 10:12:01 2026
  read: IOPS=19.8k, BW=77.4MiB/s (81.2MB/s)(2322MiB/30001msec)
    slat (usec): min=2, max=812, avg= 6.10, stdev= 4.02
    clat (usec): min=112, max=48211, avg=1608.33, stdev=902.14
     lat (usec): min=118, max=48219, avg=1614.43, stdev=902.40
    clat percentiles (usec):
     |  1.00th=[  420],  5.00th=[  644], 10.00th=[  799], 20.00th=[ 1004],
     | 50.00th=[ 1500], 90.00th=[ 2573], 95.00th=[ 3032],
     | 99.00th=[ 4555], 99.50th=[ 5538], 99.90th=[ 9896], 99.99th=[27395]
  IO depths    : 1=0.1%, 2=0.1%, 4=0.1%, 8=0.1%, 16=0.1%, 32=100.0%, >=64=0.0%
```text
Как читать: `IOPS`/`BW` — итог; `slat` — время подачи запроса, `clat` — от подачи до
завершения (это и есть latency устройства + очередь), `lat = slat + clat`. Смотри на
**p99 и p99.9**, а не на `avg`. В профиле 4 главное — перцентили `fdatasync`: etcd
рекомендует p99 < 10 мс.

⭐ Связь глубины и IOPS: `IOPS ≈ iodepth / latency`. При `iodepth=1` и latency 0,5 мс
потолок — 2000 IOPS, какой бы быстрый ни был диск. Поэтому однопоточное приложение с
синхронным I/O «не может разогнать NVMe», а fio с `iodepth=32` — может.

---

## 7. Page cache и dirty pages: почему запись «то летает, то встаёт»

```bash
grep -E '^(Dirty|Writeback):' /proc/meminfo     # сколько грязного и сколько пишется сейчас
sysctl vm.dirty_background_ratio vm.dirty_ratio vm.dirty_expire_centisecs vm.dirty_writeback_centisecs
sudo cachestat-bpfcc 1                          # попадания/промахи page cache в секунду (тема 07)
```text
| Параметр | По умолчанию | Смысл |
|----------|--------------|-------|
| `vm.dirty_background_ratio` | 10 | При таком % грязных страниц (от доступной памяти) flusher начинает фоновую запись |
| `vm.dirty_ratio` | 20 | Порог, после которого **сам пишущий процесс** тормозится в `write()` и помогает сбрасывать |
| `vm.dirty_expire_centisecs` | 3000 (30 с) | Грязные данные старше этого сбрасываются при следующем проходе flusher |
| `vm.dirty_writeback_centisecs` | 500 (5 с) | Как часто просыпается flusher |
| `vm.dirty_bytes`, `vm.dirty_background_bytes` | 0 | То же абсолютным числом; запись в `*_bytes` обнуляет парный `*_ratio`, и наоборот |

```text
 Dirty растёт ───────────────► 10% ─────────────────► 20%
 write() быстрый (в кэш)       flusher пишет в фоне   write() блокируется: процесс ждёт диск
                                                       ↑ «запись встала на 20 секунд»
```text
**Writeback-шторм:** на машине с 64 ГБ RAM 20% — это ~12 ГБ грязных данных. Приложение
быстро пишет гигабайты в кэш, потом упирается в `dirty_ratio`, и flusher вываливает всё
разом: `w_await` у всех соседей подскакивает до сотен мс, `fsync` базы висит секундами.
Лечение для таких машин — абсолютные пороги поменьше (например, `vm.dirty_background_bytes`
в сотни МБ), чтобы сбрасывать чаще и мельче. Меняй, только увидев шторм в `Dirty`/`Writeback`
и `iostat`, и проверяй эффект.

> 💡 `echo 3 | sudo tee /proc/sys/vm/drop_caches` (после `sync`) — сбросить чистый кэш перед
> тестом «холодного» чтения. На проде так не лечат: после сброса всё читается с диска заново.

---

## 8. Место: `df` против `du`

Алгоритм «диск заполнен» и inodes — в [../Linux/10_the_filesystem.md](/linux/10-the-filesystem).
Здесь — почему `df` и `du` показывают разное.

```bash
df -hT /var                  # размер/занято/доступно по ФС
df -i /var                   # inodes: IUse% 100% → «No space left», хотя байты есть
sudo du -xsh /var            # сумма размеров видимых файлов (-x: не выходить на другие ФС)
```text
| `df` больше, чем `du` — почему | Как проверить |
|--------------------------------|---------------|
| **Удалённые, но открытые файлы**: места нет, имени нет | `sudo lsof -nP +L1` (раздел 9) |
| **Файлы под точкой монтирования**: писали в `/data` до `mount`, потом смонтировали поверх | `sudo mount --bind / /mnt/rootview && sudo du -sh /mnt/rootview/data` |
| **Reserved blocks** ext4 (по умолчанию 5% для root): `Avail` меньше, чем `Size − Used` | `sudo tune2fs -l /dev/vda1 \| grep -i 'reserved block count'` |
| Метаданные ФС, журнал, снапшоты (LVM, btrfs, ZFS) | Инструменты конкретной ФС (`btrfs filesystem usage`, `lvs`) |

| `du` больше, чем `df` — почему | |
|-------------------------------|---|
| Sparse-файлы: `du --apparent-size` считает «логический» размер | `du -sh` vs `du -sh --apparent-size` |
| Hard links посчитаны дважды разными запусками `du` | Один запуск `du` считает inode один раз |

> ⚠️ Reserved blocks — причина «у root место есть, а приложение от своего пользователя
> получает `No space left on device`». На больших data-дисках (не корень) резерв часто
> уменьшают: `sudo tune2fs -m 1 /dev/vdb1`.

---

## 9. «Диск полон, а файлов нет»: удалённые открытые файлы

Трюк восстановления через `/proc/PID/fd` — в [../Linux/07_processes.md](/linux/07-processes).
Здесь — как найти и освободить место **без рестарта**.

```bash
sudo lsof -nP +L1                                   # всё, у чего NLINK=0 (удалено, но открыто)
sudo lsof -nP +L1 | grep -v memfd                   # memfd — анонимные файлы в памяти, не диск
sudo lsof -nP -a +L1 -p 1234                        # -a: И (+L1, И PID). Без -a это ИЛИ!
sudo find /proc/[0-9]*/fd -lname '*(deleted)' -printf '%p -> %l\n' 2>/dev/null   # без lsof
```text
```text
# пример вывода sudo lsof -nP +L1
COMMAND    PID     USER   FD   TYPE DEVICE    SIZE/OFF NLINK    NODE NAME
java      2210   appsvc   27w   REG  252,1 19327352832     0  524301 /var/log/app/app.log.1 (deleted)
```text
Разбор: процесс `java` (PID 2210) держит дескриптор **27** на запись (`w`) к файлу 18 ГБ,
у которого 0 имён (`NLINK 0`). Кто-то сделал `rm app.log.1`, но процесс продолжает писать.

Освободить место, не останавливая сервис:
```bash
sudo truncate -s 0 /proc/2210/fd/27        # обрезать файл через дескриптор процесса
# или то же самое:
sudo sh -c ': > /proc/2210/fd/27'
df -h /var                                  # место вернулось сразу
```text
Правильный долгосрочный фикс — чтобы процесс переоткрыл файл: `systemctl reload`/`kill -HUP`
(если приложение умеет), либо рестарт в окно обслуживания.

> ⚠️ Если приложение пишет **без** `O_APPEND`, после обрезки оно продолжит писать со старого
> смещения: файл станет sparse того же «размера» в `ls`, но блоков на диске займёт мало.
> Не пугайся `ls -l` — смотри `du` и `df`.

Откуда берутся deleted-файлы на проде и как не допустить:

| Причина | Правильно |
|---------|-----------|
| `rm` большого лога руками | `truncate -s 0 file` (или `: > file`), а не `rm` |
| logrotate без сигнала приложению | `create` + `postrotate` c `kill -HUP`/`reload`; для приложений, которые не умеют переоткрывать, — `copytruncate` (⚠️ теряет строки, записанные между копией и обрезкой) |
| Временные файлы, удалённые сразу после открытия (так делают БД и сортировки) | Это нормально — место вернётся, когда процесс закроет файл |
| Контейнер пишет в свой слой, а файл удалили снаружи | Логи — в stdout или том; см. [../Docker/11_troubleshooting.md](/docker/11-troubleshooting) §7 |

Полный инцидент с поиском и мини-постмортемом — лаба 3 в [08_practice_labs.md](/softskills/08-practice-labs).

---

## 10. ФС и журнал: когда диск «сломался», а не «медленный»

```bash
dmesg -T | grep -iE 'I/O error|EXT4-fs|XFS|remount|blk_' | tail
findmnt -no OPTIONS /           # ro,relatime… — ФС уже только для чтения?
cat /proc/mounts | awk '$4 ~ /^ro/'
```text
| Строка в `dmesg` | Что значит | Что делать |
|------------------|-----------|-----------|
| `I/O error, dev vdb, sector 123456 op 0x1:(WRITE)` | Устройство вернуло ошибку | SMART / состояние облачного тома, не насиловать диск, бэкап |
| `EXT4-fs error (device vda1): …` | Повреждены метаданные | Плановый `fsck` на размонтированной ФС |
| `EXT4-fs (vda1): Remounting filesystem read-only` | Сработало `errors=remount-ro` (дефолт для корня в Ubuntu) | Приложения получают `Read-only file system` (EROFS) — это следствие, ищи причину выше в логе |
| `XFS (vdb1): Filesystem has been shut down due to log error` | XFS защитилась от порчи | Размонтировать, `xfs_repair` |

Запускать `fsck` можно только на размонтированной ФС — подробно в
[../Linux/10_the_filesystem.md](/linux/10-the-filesystem) (раздел Filesystem Repair).

Процессы в состоянии `D` с `wchan` вида `jbd2_log_wait_commit` или `io_schedule` —
ждут журнал или диск. Как это разбирать — [05_strace_hung_processes.md](/performance/05-strace-hung-processes).

---

## 11. Планировщики I/O

```bash
cat /sys/block/vdb/queue/scheduler          # [none] mq-deadline   ← в скобках активный
echo mq-deadline | sudo tee /sys/block/vdb/queue/scheduler    # до перезагрузки
cat /sys/block/vdb/queue/nr_requests /sys/block/vdb/queue/rotational
```text
| Планировщик | Для чего |
|-------------|----------|
| `none` | NVMe и быстрые SSD, виртуальные диски: у устройства своя умная очередь, ядру лучше не мешать |
| `mq-deadline` | Дефолт для одноочередных устройств (SATA, HDD); ограничивает голодание чтений |
| `bfq` | Справедливость между процессами, десктоп и медленные диски; дороже по CPU |
| `kyber` | Лёгкий, с целевой latency для быстрых устройств |

`bfq` и `kyber` появятся в списке, только если загружены их модули. Постоянно — через
udev-правило. Планировщик редко бывает причиной инцидента: сначала latency, очередь и
лимиты устройства, потом уже он.

---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| «`%util` 100% — диск умер» на NVMe | Параллельное устройство, `%util` не показывает предел | `await`, `aqu-sz`, IOPS против замера fio |
| Смотреть первый отчёт `iostat` | Это среднее с момента загрузки | Со второго отчёта |
| fio без `--direct=1` | Меряешь page cache, получаешь «10 ГБ/с» | `--direct=1` и размер файла больше RAM, если без direct |
| `dd if=/dev/zero of=test` как бенчмарк | Одна последовательная запись через кэш | fio с профилем, похожим на нагрузку |
| fio с записью на `/dev/sdX` с данными | Перезаписал ФС | Только файл или пустое устройство стенда |
| `rm` огромного лога | Место не освободилось, файл висит deleted | `truncate -s 0`, logrotate с HUP |
| `lsof +L1 -p PID` без `-a` | Условия объединены по ИЛИ — видишь чужие файлы | `lsof -a +L1 -p PID` |
| «`df` 100%, `du` 60%» → ищут большие файлы | Место съедено deleted-файлами или скрыто под mount | `lsof +L1`, bind mount корня |
| Приложение получает ENOSPC, `df` показывает 4% свободно | Reserved blocks для root, или кончились inodes | `tune2fs -l`, `df -i` |
| Поднять `dirty_ratio` «чтобы запись быстрее» | Больше буфер → более страшный шторм и больше потерь при сбое | Мерить `Dirty`/`Writeback`, для больших RAM — `*_bytes` поменьше |
| Средний `await` норм — «диск не виноват» | Хвост спрятан в среднем | `biolatency` — гистограмма |

---

## 💼 Как это в DevOps

- «Сервис тормозит, а CPU свободен» → первым делом `iostat -xz 1` и `vmstat 1` (колонки `b`, `wa`):
  высокий `await` и процессы в `D` закрывают вопрос за минуту.
- Облачные тома имеют лимиты IOPS и MB/s (и burst-кредиты). Ровная «полка» в IOPS при
  растущем `await` — это лимит тома, лечится классом/размером тома, а не тюнингом ядра.
- etcd, PostgreSQL, Kafka чувствительны к `fsync`: перед выбором диска под них гоняют fio-профиль
  с `fdatasync` и смотрят p99. Медленный диск у etcd = нестабильный Kubernetes.
- Алерты по диску: заполнение **и прогноз** (`predict_linear` по `node_filesystem_avail_bytes`),
  inodes, `rate(node_disk_io_time_weighted_seconds_total)` как saturation —
  см. [../Left/02_Monitoring/07_what_to_monitor.md](/monitoring/07-what-to-monitor).
- «Диск полон» — самый частый инцидент в эксплуатации. Готовая последовательность:
  `df -h` → `df -i` → `du -xh --max-depth=1 | sort -rh` → `lsof +L1` → логи/docker/журнал.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Нагрузка на устройства | `iostat -xz 1` (со второго отчёта) |
| Одно устройство | `iostat -dxz vdb 1` |
| Кто пишет/читает | `pidstat -d 1`, `sudo iotop -oPa` |
| Байты процесса на диск vs через read() | `/proc/PID/io`: `read_bytes` vs `rchar` |
| Гистограмма latency | `sudo biolatency-bpfcc -m -D 10 1` |
| Каждый запрос с latency | `sudo biosnoop-bpfcc` |
| Latency диска | `fio --rw=randread --bs=4k --iodepth=1 --direct=1 …` |
| Предел IOPS | `fio --rw=randread --bs=4k --iodepth=32 --direct=1 …` |
| Как ведёт себя `fsync` | `fio --rw=write --ioengine=sync --fdatasync=1 --bs=2300 --size=22m` |
| Сколько грязного в кэше | `grep -E '^(Dirty\|Writeback):' /proc/meminfo` |
| Inodes | `df -i` |
| Deleted-файлы | `sudo lsof -nP +L1 \| grep -v memfd` |
| Освободить место без рестарта | `sudo truncate -s 0 /proc/PID/fd/N` |
| Что под точкой монтирования | `mount --bind / /mnt/x && du -sh /mnt/x/&lt;путь&gt;` |
| Reserved blocks | `tune2fs -l DEV \| grep -i reserved`, `tune2fs -m 1 DEV` |
| ФС ушла в read-only? | `findmnt -no OPTIONS /`, `dmesg -T \| grep -i remount` |
| Планировщик | `cat /sys/block/DEV/queue/scheduler` |

---

## 🧠 Что запомнить

1. Latency приложения ≠ latency диска: буферизованная запись идёт в page cache, платит `fsync` или flusher.
2. В `iostat -x` главное — `r_await`/`w_await` и `aqu-sz`; проверка — закон Литтла `aqu-sz ≈ IOPS × await`.
3. `%util` = «был хотя бы один запрос». Для HDD 100% — предел, для SSD/NVMe/RAID — ещё нет.
4. Средние прячут хвост: для диска смотри гистограмму (`biolatency`) и p99 в fio.
5. fio: `--direct=1`, профиль как у нагрузки; `IOPS ≈ iodepth / latency`.
6. Dirty pages: 10% — фоновый сброс, 20% — писатели тормозятся; на больших RAM это штормы.
7. `df` > `du` → deleted-файлы, файлы под точкой монтирования, reserved blocks, снапшоты.
8. Deleted-файл освобождается `truncate -s 0 /proc/PID/fd/N` без рестарта; `lsof -a +L1 -p PID`.
9. Ошибки диска и ФС видно в `dmesg`; read-only ФС — следствие, причина выше в логе.
10. Облачный том с ровной «полкой» IOPS и растущим `await` упёрся в свой лимит.

➡️ Дальше: [04_network_deep.md](/performance/04-network-deep) · задачи: 03_disk_io_tasks.md


---

### Блок A. Теория


**A1.** Разложи диск по USE: какие метрики отвечают за U, S и E и какой командой их смотреть?

<details><summary>Ответ</summary>

U — `%util` (время, когда устройство было занято; для параллельных устройств условно).
S — `aqu-sz`, `r_await`/`w_await`, процессы в `D` (`vmstat` колонка `b`), `/proc/pressure/io`.
E — ошибки в `dmesg` (`I/O error`, `EXT4-fs error`), SMART/`nvme smart-log`. Команды:
`iostat -xz 1`, `vmstat 1`, `dmesg -T`, `cat /proc/pressure/io`.

</details>

**A2.** ⭐ Что показывают `r_await`/`w_await`? Из чего складывается это время?

<details><summary>Ответ</summary>

Среднее время завершения запроса в мс с момента, как он попал в блочный слой:
ожидание в очереди ОС и устройства + собственно обслуживание. Растёт и от медленного
устройства, и от длинной очереди — поэтому это главная метрика «насколько больно».

</details>

**A3.** Как по `iostat -x` отличить случайный доступ от последовательного?

<details><summary>Ответ</summary>

По размеру запроса и слияниям: `rareq-sz`/`wareq-sz` около 4–16 КБ и `%rrqm`/`%wrqm`
около 0 — случайный доступ; сотни КБ и заметные слияния — последовательный.

</details>

**A4.** ⭐ Почему `%util` 100% на NVMe ещё не значит, что диск в полке? Что смотреть вместо него?

<details><summary>Ответ</summary>

`%util` считает время, когда в устройстве был **хотя бы один** запрос, и не видит
параллелизма. NVMe и RAID обслуживают десятки запросов одновременно, поэтому при 100%
у них может быть кратный запас. Смотреть: `await` против базы из fio, `aqu-sz` против
глубины насыщения, IOPS/MB/s против предела или лимита тома, PSI io.

</details>

**A5.** Как связаны `aqu-sz`, IOPS и `await`? Зачем это знать?

<details><summary>Ответ</summary>

Закон Литтла: `aqu-sz ≈ (r/s + w/s) × await / 1000`. Позволяет проверить, что ты
правильно читаешь вывод, и понять: при фиксированной latency рост IOPS требует роста очереди,
а при упоре в предел устройства рост очереди даёт только рост `await`.

</details>

**A6.** Что значат колонки `kB_wr/s`, `kB_ccwr/s` и `iodelay` в `pidstat -d`? Что нужно включить, чтобы `iodelay` не был нулём?

<details><summary>Ответ</summary>

`kB_wr/s` — запись, которую процесс вызвал (учитывается при загрязнении страницы,
даже если на диск её отнёс flusher). `kB_ccwr/s` — запись, которая была отменена (страницы
загрязнили, но файл удалили/обрезали до сброса). `iodelay` — такты ожидания синхронного
block I/O и swap-in. Нужен `sysctl kernel.task_delayacct=1` (с ядра 5.14 по умолчанию выключен).

</details>

**A7.** Чем `rchar` отличается от `read_bytes` в `/proc/PID/io`?

<details><summary>Ответ</summary>

`rchar` — все байты, прочитанные через `read`-подобные вызовы, включая page cache,
пайпы и сокеты. `read_bytes` — байты, которые реально запрошены у блочного устройства.
Большой `rchar` при малом `read_bytes` = чтение из кэша.

</details>

**A8.** Зачем гистограмма latency (`biolatency`), если в `iostat` уже есть `await`?

<details><summary>Ответ</summary>

Среднее прячет распределение: бимодальность (кэш устройства против медленных
запросов), редкие, но огромные задержки. Пользователь страдает от хвоста; гистограмма
показывает, сколько запросов в каком диапазоне.

</details>

**A9.** ⭐ Что делают параметры fio `--rw`, `--bs`, `--iodepth`, `--direct=1`? Почему `iodepth`
бесполезен с `--ioengine=sync`?

<details><summary>Ответ</summary>

`--rw` — тип доступа (random/sequential, read/write/mixed); `--bs` — размер блока;
`--iodepth` — сколько запросов держать в полёте; `--direct=1` — `O_DIRECT`, мимо page cache.
Синхронный движок отправляет следующий запрос только после завершения предыдущего,
поэтому глубина всегда 1, что бы ни было в `--iodepth`.

</details>

**A10.** Что такое `slat`, `clat` и `lat` в выводе fio? Почему смотрят на p99, а не на `avg`?

<details><summary>Ответ</summary>

`slat` — время подачи запроса в ядро; `clat` — от подачи до завершения (очередь +
устройство); `lat = slat + clat`. Средние прячут хвост; SLO сервиса обычно по перцентилям,
а один медленный `fsync` из сотни подвешивает транзакцию.

</details>

**A11.** ⭐ Что происходит при достижении `vm.dirty_background_ratio` и `vm.dirty_ratio`?
Что такое writeback-шторм?

<details><summary>Ответ</summary>

На `dirty_background_ratio` (10%) flusher начинает фоновую запись, приложения
продолжают писать в кэш. На `dirty_ratio` (20%) процессы, которые пишут, притормаживаются
в `write()` и ждут сброса. Шторм: на машине с большой RAM копятся гигабайты грязных данных,
потом их сбрасывают разом — очередь устройства забита, `w_await` у всех на сотнях мс.

</details>

**A12.** ⭐ Назови четыре причины, по которым `df` показывает занятым больше, чем насчитал `du`.

<details><summary>Ответ</summary>

Удалённые, но открытые файлы; файлы, скрытые под точкой монтирования; reserved
blocks ext4 (5% под root); метаданные ФС/журнал и снапшоты (LVM, btrfs, ZFS).

</details>

**A13.** Почему `rm` большого лога может не освободить место? Как освободить его без рестарта процесса?

<details><summary>Ответ</summary>

Файл исчезает, когда у него 0 имён **и** его никто не держит открытым. Если процесс
пишет в файл, `rm` убирает только имя. Освободить: `sudo lsof -nP +L1` → PID и FD →
`sudo truncate -s 0 /proc/PID/fd/FD`. Потом заставить процесс переоткрыть файл (HUP/reload).

</details>

**A14.** logrotate: чем `copytruncate` отличается от `create` + `postrotate` с сигналом?

<details><summary>Ответ</summary>

`copytruncate` копирует файл и обрезает оригинал — приложению ничего не нужно
уметь, но строки между копированием и обрезкой теряются, а копия удваивает I/O.
`create` + `postrotate kill -HUP`/`reload` переименовывает файл и просит приложение открыть
новый — без потерь, но приложение должно уметь переоткрывать логи.

</details>

**A15.** Какие планировщики I/O есть в современном ядре и почему для NVMe обычно `none`?

<details><summary>Ответ</summary>

`none`, `mq-deadline`, `bfq`, `kyber` (последние два — модулями). NVMe имеет
множество аппаратных очередей и сам хорошо планирует; сортировка и задержка в ядре
только добавляют latency и CPU, поэтому `none`.

</details>

**A16.** Приложение внезапно пишет `Read-only file system`. Что произошло с ФС и где искать причину?

<details><summary>Ответ</summary>

ФС обнаружила ошибку (ошибка записи устройства или повреждение метаданных) и по
опции `errors=remount-ro` сама перемонтировалась в read-only, чтобы не испортить данные.
Причина — в `dmesg`/`journalctl -k` **выше** строки `Remounting filesystem read-only`.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # сервер с HDD, отчёт iostat -dxz 1 (фрагмент)
```text
<details><summary>Ответ</summary>

HDD на случайном чтении упёрся в физический предел (~150–200 IOPS на шпиндель):
мелкие запросы, `%util` 100%, `await` 18 мс. Для HDD это реальное насыщение. Лечится
кэшем, уменьшением случайного I/O или переездом на SSD.

</details>

```text:no-line-numbers
     Device   r/s   rkB/s  %rrqm r_await rareq-sz   w/s  aqu-sz  %util
```text
```text:no-line-numbers
     sda    158.00  632.00  0.00   18.40     4.00  2.00    2.94 100.00
```text
```text:no-line-numbers
B2.  # NVMe под нагрузкой; «%util 100%, диск умирает, срочно меняем!»
```text
<details><summary>Ответ</summary>

⚠️ Ложная тревога. 42k IOPS при latency 0,21 мс и очереди ~9 — NVMe работает
отлично и далёк от предела. `%util` для параллельных устройств не показывает насыщение.

</details>

```text:no-line-numbers
     Device       r/s     rkB/s  r_await rareq-sz   aqu-sz  %util
```text
```text:no-line-numbers
     nvme0n1 42000.00 168000.00     0.21     4.00     8.82 100.00
```text
```text:no-line-numbers
B3.  # БД «тормозит на коммитах»
```text
<details><summary>Ответ</summary>

Устройство не загружено по IOPS, но `f_await` 45 мс: каждая мелкая запись
сопровождается flush (`fsync`/`fdatasync`), и flush медленный. Коммиты ждут `fsync`.
Проверить fio-профилем с `--fdatasync=1`; решения — диск с быстрым flush (SSD с
защитой от потери питания), группировка коммитов на стороне БД.

</details>

```text:no-line-numbers
     Device    w/s   wkB/s  w_await wareq-sz    f/s f_await  aqu-sz  %util
```text
```text:no-line-numbers
     vdb     12.00   48.00     2.10     4.00  12.00   45.30    0.57  56.00
```text
```text:no-line-numbers
B4.  # облачный том, 10 отчётов подряд: r/s не меняется, r_await растёт
```text
<details><summary>Ответ</summary>

IOPS стоят ровно на лимите, очередь растёт, latency растёт — это троттлинг
облачного тома по лимиту IOPS (или кончились burst-кредиты). Смотреть лимиты тома
в консоли провайдера; лечится классом/размером тома или снижением I/O.

</details>

```text:no-line-numbers
     r/s 3000.00  r_await  2.1 → 4.8 → 9.6 → 17.9 → 25.3   aqu-sz 6 → 76
```text
```text:no-line-numbers
B5.  $ sudo cat /proc/2210/io
```text
<details><summary>Ответ</summary>

⚠️ Неверный вывод. `rchar` 50 ГБ, а `read_bytes` 12 МБ: почти всё читается из
page cache (или из сокетов/пайпов). Диск тут почти ни при чём.

</details>

```text:no-line-numbers
     rchar: 53687091200
```text
```text:no-line-numbers
     wchar: 1048576
```text
```text:no-line-numbers
     read_bytes: 12582912
```text
```text:no-line-numbers
     write_bytes: 1048576
```text
```text:no-line-numbers
     cancelled_write_bytes: 0
```text
```text:no-line-numbers
     # «приложение читает 50 ГБ с диска, диск виноват!»
```text
```text:no-line-numbers
B6.  # fio на ноутбучном SATA SSD
```text
<details><summary>Ответ</summary>

⚠️ Нет `--direct=1`: чтение идёт из page cache, это скорость RAM, а не SSD.
Нужны `--direct=1` (или файл сильно больше RAM).

</details>

```text:no-line-numbers
     $ fio --name=t --filename=f --size=1G --rw=randread --bs=4k --iodepth=32 --ioengine=libaio
```text
```text:no-line-numbers
       read: IOPS=251k, BW=981MiB/s
```text
```text:no-line-numbers
B7.  # разработчик: «NVMe обещает 500k IOPS, а наш сервис получает 2k»
```text
<details><summary>Ответ</summary>

При `iodepth=1` и latency ~0,48 мс потолок ≈ 1 / 0,000482 ≈ 2070 IOPS. 500k IOPS
достигаются только с глубокой очередью и многими потоками. Сервису нужен параллелизм
(асинхронный I/O, несколько потоков) или меньше синхронных чтений.

</details>

```text:no-line-numbers
     fio --rw=randread --bs=4k --iodepth=1 --ioengine=psync --direct=1 ...
```text
```text:no-line-numbers
       clat (usec): avg=482.10
```text
```text:no-line-numbers
B8.  $ df -h /            →  /dev/vda1  40G   40G     0  100% /
```text
<details><summary>Ответ</summary>

29 ГБ заняты, но не видны `du`. Проверить `sudo lsof -nP +L1` (deleted-файлы),
bind-mount корня на файлы под точками монтирования, reserved blocks (`df` показывает 0 доступно —
у root ещё может быть резерв).

</details>

```text:no-line-numbers
     $ sudo du -xsh /     →  11G   /
```text
```text:no-line-numbers
B9.  $ sudo lsof -nP +L1
```text
<details><summary>Ответ</summary>

⚠️ Это `memfd` — анонимные файлы в памяти (`DEVICE 0,1`, маленькие размеры), к диску
отношения не имеют. Отфильтровать `grep -v memfd` и смотреть обычные файлы с реальным `DEVICE`.

</details>

```text:no-line-numbers
     pipewire  2581 nurik  36u  REG  0,1  2312  0  2066 /memfd:pipewire-memfd:... (deleted)
```text
```text:no-line-numbers
     gnome-she 2854 nurik  35u  REG  0,1 71323  0  4106 /memfd:mutter-shared (deleted)
```text
```text:no-line-numbers
     # «вот они, удалённые файлы, съевшие диск!»
```text
```text:no-line-numbers
B10.  # сервер 64 ГБ RAM, раз в несколько минут запись встаёт на 10–20 секунд
```text
<details><summary>Ответ</summary>

Writeback-шторм: 6 ГБ грязных страниц (≈ 10% от 64 ГБ), крупная запись очередью
в 290 запросов, `w_await` 310 мс. Процессы встают на `dirty_ratio` и в `fsync`. Лечение —
абсолютные пороги поменьше (`vm.dirty_background_bytes`, `vm.dirty_bytes`), чтобы сбрасывать
чаще и мельче, плюс выяснить, кто пишет (`pidstat -d`), и развести его по дискам.

</details>

```text:no-line-numbers
     $ grep -E '^(Dirty|Writeback):' /proc/meminfo
```text
```text:no-line-numbers
     Dirty:           6291456 kB
```text
```text:no-line-numbers
     Writeback:        819200 kB
```text
```text:no-line-numbers
     $ iostat -dxz vdb 1   →   w/s 950  wareq-sz 512  w_await 310  aqu-sz 290
```text
```text:no-line-numbers
B11.  $ df -h /srv   →  /dev/vdb1   50G   19G   29G  40% /srv
```text
<details><summary>Ответ</summary>

Кончились inodes при свободных байтах. Найти каталог с миллионами мелких файлов:
`sudo find /srv -xdev -printf '%h\n' | sort | uniq -c | sort -rn | head`. Удалить мусор
(сессии, кэш); на будущее — ФС с большим числом inodes или другая структура хранения.

</details>

```text:no-line-numbers
     $ df -i /srv   →  /dev/vdb1  3.2M  3.2M     0  100% /srv
```text
```text:no-line-numbers
     $ touch /srv/x →  touch: cannot touch '/srv/x': No space left on device
```text
```text:no-line-numbers
B12.  $ sudo lsof +L1 -p 2210
```text
<details><summary>Ответ</summary>

⚠️ У `lsof` условия по умолчанию объединяются через ИЛИ: «deleted-файлы любого
процесса ИЛИ файлы PID 2210». Нужен `-a`: `sudo lsof -nP -a +L1 -p 2210`.

</details>

```text:no-line-numbers
     # в выводе десятки строк от pipewire, gnome-shell и других процессов
```text
```text:no-line-numbers
B13.  $ dmesg -T | tail -3
```text
<details><summary>Ответ</summary>

⚠️ Нельзя просто перемонтировать: устройство вернуло ошибку записи, журнал ext4
аварийно остановлен, ФС ушла в read-only для защиты данных. Сначала — состояние
диска/тома (SMART, консоль облака), бэкап данных, затем остановка сервисов, размонтирование
и `fsck`; при сбойном устройстве — замена.

</details>

```text:no-line-numbers
     [..] I/O error, dev vdb, sector 2048 op 0x1:(WRITE) flags 0x800 phys_seg 1 prio class 2
```text
```text:no-line-numbers
     [..] EXT4-fs error (device vdb1): ext4_journal_check_start:84: comm app: Detected aborted journal
```text
```text:no-line-numbers
     [..] EXT4-fs (vdb1): Remounting filesystem read-only
```text
```text:no-line-numbers
     # дежурный: «сделаю mount -o remount,rw и всё»
```text
---

### Блок C. Практика


### C1. 🔑 Читаем `iostat` под нагрузкой и проверяем закон Литтла
**1.** В одном терминале: `iostat -dxz 1` (укажи устройство, на котором лежит `~/perf/03`, — `vda`).

<details><summary>Ответ</summary>

Профиль 1 (`iodepth=1`): `aqu-sz` ≈ 1, `r/s` ≈ 1000 / `r_await`, `rareq-sz` 4, `%util`
близок к 100% уже при одной операции — наглядно, почему `%util` не предел. Профиль 2
(`iodepth=32`): `aqu-sz` ≈ 30–32, IOPS в разы больше, `r_await` выше. Литтл сходится с
точностью до округления: например, 18 950 × 1,68 / 1000 ≈ 31,8.

</details>

**2.** В другом — fio-профили 1 и 2 из конспекта (latency и IOPS) на файле `~/perf/03/fio.test`.

<details><summary>Ответ</summary>

Пример таблицы (числа свои):
```text
профиль        IOPS     MB/s   p50 clat   p99 clat   p99.9
lat (qd1)      2.1k      8.2   430us      780us      1.9ms
iops (qd32)   19.8k     77.4   1.5ms      4.6ms      9.9ms
seq 1M (qd8)   1.1k     1100   6.8ms      12ms       18ms
fdatasync      ~900      —     fdatasync p99 = 2.4ms (etcd хочет < 10ms)
```text
Без `--direct=1` IOPS и MB/s вырастут в разы, latency — в десятки микросекунд: чтение
из page cache (файл 1 ГБ помещается в RAM). Это замер памяти, а не диска.

</details>

**3.** Для каждого профиля выпиши `r/s`, `r_await`, `rareq-sz`, `aqu-sz`, `%util`.
   Проверь `aqu-sz ≈ r/s × r_await / 1000` и сравни `aqu-sz` с `--iodepth`.

<details><summary>Ответ</summary>

`pidstat -d 1` покажет `dd` с `kB_wr/s` порядка скорости диска и ненулевым `iodelay`;
`sudo iotop -oPa` — `dd` сверху с растущим `DISK WRITE` и `IO>`; в `/proc/PID/io` растут
`wchar` и `write_bytes` синхронно (из-за `oflag=direct` записи не копятся в кэше).

</details>

### C2. 🔑 Паспорт диска стенда
Прогони четыре fio-профиля (latency, IOPS, sequential, fdatasync) и заполни таблицу:
IOPS, MB/s, p50/p99/p99.9 clat. Затем повтори профиль 2 **без** `--direct=1` и объясни разницу.

### C3. Кто грузит диск
Запусти в фоне `dd if=/dev/zero of=~/perf/03/big bs=1M count=3000 oflag=direct`.
Найди его тремя способами: `pidstat -d 1`, `sudo iotop -oPa`, `/proc/PID/io`. Какие поля растут?

### C4. Гистограмма против среднего
Во время профиля 2 запусти `sudo biolatency-bpfcc -D 10 1` и `iostat -dxz 1`.
Совпадает ли среднее из `iostat` с «центром» гистограммы? Где хвост?

### C5. 🔑 Dirty pages своими глазами
**1.** `watch -n1 "grep -E '^(Dirty|Writeback):' /proc/meminfo"` в одном окне.

<details><summary>Ответ</summary>

Профиль 1 (`iodepth=1`): `aqu-sz` ≈ 1, `r/s` ≈ 1000 / `r_await`, `rareq-sz` 4, `%util`
близок к 100% уже при одной операции — наглядно, почему `%util` не предел. Профиль 2
(`iodepth=32`): `aqu-sz` ≈ 30–32, IOPS в разы больше, `r_await` выше. Литтл сходится с
точностью до округления: например, 18 950 × 1,68 / 1000 ≈ 31,8.

</details>

**2.** В другом: `dd if=/dev/zero of=~/perf/03/dirty bs=1M count=1500` (без `oflag=direct`).

<details><summary>Ответ</summary>

Пример таблицы (числа свои):
```text
профиль        IOPS     MB/s   p50 clat   p99 clat   p99.9
lat (qd1)      2.1k      8.2   430us      780us      1.9ms
iops (qd32)   19.8k     77.4   1.5ms      4.6ms      9.9ms
seq 1M (qd8)   1.1k     1100   6.8ms      12ms       18ms
fdatasync      ~900      —     fdatasync p99 = 2.4ms (etcd хочет < 10ms)
```text
Без `--direct=1` IOPS и MB/s вырастут в разы, latency — в десятки микросекунд: чтение
из page cache (файл 1 ГБ помещается в RAM). Это замер памяти, а не диска.

</details>

**3.** Засеки, когда `dd` закончился, и когда `Dirty` вернулся к нулю. Затем повтори с `conv=fsync`.

<details><summary>Ответ</summary>

`pidstat -d 1` покажет `dd` с `kB_wr/s` порядка скорости диска и ненулевым `iodelay`;
`sudo iotop -oPa` — `dd` сверху с растущим `DISK WRITE` и `IO>`; в `/proc/PID/io` растут
`wchar` и `write_bytes` синхронно (из-за `oflag=direct` записи не копятся в кэше).

</details>

### C6. 🔑 Удалённый открытый файл (мини-версия лабы 3)
**1.** Запусти писатель: `(while true; do head -c 10M /dev/urandom; sleep 1; done) > ~/perf/03/app.log &`.

<details><summary>Ответ</summary>

Профиль 1 (`iodepth=1`): `aqu-sz` ≈ 1, `r/s` ≈ 1000 / `r_await`, `rareq-sz` 4, `%util`
близок к 100% уже при одной операции — наглядно, почему `%util` не предел. Профиль 2
(`iodepth=32`): `aqu-sz` ≈ 30–32, IOPS в разы больше, `r_await` выше. Литтл сходится с
точностью до округления: например, 18 950 × 1,68 / 1000 ≈ 31,8.

</details>

**2.** Через минуту `rm ~/perf/03/app.log`. Убедись, что `df` продолжает расти.

<details><summary>Ответ</summary>

Пример таблицы (числа свои):
```text
профиль        IOPS     MB/s   p50 clat   p99 clat   p99.9
lat (qd1)      2.1k      8.2   430us      780us      1.9ms
iops (qd32)   19.8k     77.4   1.5ms      4.6ms      9.9ms
seq 1M (qd8)   1.1k     1100   6.8ms      12ms       18ms
fdatasync      ~900      —     fdatasync p99 = 2.4ms (etcd хочет < 10ms)
```text
Без `--direct=1` IOPS и MB/s вырастут в разы, latency — в десятки микросекунд: чтение
из page cache (файл 1 ГБ помещается в RAM). Это замер памяти, а не диска.

</details>

**3.** Найди файл через `lsof +L1` и через `find /proc/*/fd -lname '*(deleted)'`.

<details><summary>Ответ</summary>

`pidstat -d 1` покажет `dd` с `kB_wr/s` порядка скорости диска и ненулевым `iodelay`;
`sudo iotop -oPa` — `dd` сверху с растущим `DISK WRITE` и `IO>`; в `/proc/PID/io` растут
`wchar` и `write_bytes` синхронно (из-за `oflag=direct` записи не копятся в кэше).

</details>

**4.** Освободи место через `/proc/PID/fd/N`, не убивая писатель. Проверь `df -h`, потом убей писатель.

<details><summary>Ответ</summary>

Среднее из `iostat` близко к центру гистограммы только при узком распределении.
На VM обычно видно основной горб в сотнях мкс–единицах мс и редкие запросы в десятки мс
(хост, соседи). Хвост в среднем почти не заметен.

</details>

### C7. Кончились inodes
Создай маленькую ФС на loop-файле с малым числом inodes, заполни её пустыми файлами
до `No space left on device` при свободных байтах. Каркас:
```text:no-line-numbers
truncate -s 100M ~/perf/03/inodes.img
```text
```text:no-line-numbers
mkfs.ext4 -q -N 2000 ~/perf/03/inodes.img
```text
```text:no-line-numbers
sudo mkdir -p /mnt/inodes && sudo mount -o loop ~/perf/03/inodes.img /mnt/inodes
```text
### C8. Файлы под точкой монтирования
**1.** `sudo mkdir -p /data && sudo dd if=/dev/zero of=/data/hidden bs=1M count=500`.

<details><summary>Ответ</summary>

Профиль 1 (`iodepth=1`): `aqu-sz` ≈ 1, `r/s` ≈ 1000 / `r_await`, `rareq-sz` 4, `%util`
близок к 100% уже при одной операции — наглядно, почему `%util` не предел. Профиль 2
(`iodepth=32`): `aqu-sz` ≈ 30–32, IOPS в разы больше, `r_await` выше. Литтл сходится с
точностью до округления: например, 18 950 × 1,68 / 1000 ≈ 31,8.

</details>

**2.** Отформатируй весь `/dev/vdb` в ext4 и смонтируй на `/data`: `sudo mkfs.ext4 -q /dev/vdb && sudo mount /dev/vdb /data`.

<details><summary>Ответ</summary>

Пример таблицы (числа свои):
```text
профиль        IOPS     MB/s   p50 clat   p99 clat   p99.9
lat (qd1)      2.1k      8.2   430us      780us      1.9ms
iops (qd32)   19.8k     77.4   1.5ms      4.6ms      9.9ms
seq 1M (qd8)   1.1k     1100   6.8ms      12ms       18ms
fdatasync      ~900      —     fdatasync p99 = 2.4ms (etcd хочет < 10ms)
```text
Без `--direct=1` IOPS и MB/s вырастут в разы, latency — в десятки микросекунд: чтение
из page cache (файл 1 ГБ помещается в RAM). Это замер памяти, а не диска.

</details>

**3.** Сравни `df -h /` и `sudo du -xsh /` до и после, затем найди «пропавшие» 500 МБ.

<details><summary>Ответ</summary>

`pidstat -d 1` покажет `dd` с `kB_wr/s` порядка скорости диска и ненулевым `iodelay`;
`sudo iotop -oPa` — `dd` сверху с растущим `DISK WRITE` и `IO>`; в `/proc/PID/io` растут
`wchar` и `write_bytes` синхронно (из-за `oflag=direct` записи не копятся в кэше).

</details>

### C9. Reserved blocks
На `/dev/vdb` (ext4 из C8, смонтирован в `/data`) посмотри резерв через `tune2fs -l`.
Сделай `sudo chown vagrant /data`, заполни ФС от обычного пользователя до ENOSPC
(`dd if=/dev/zero of=/data/fill bs=1M`) и проверь, что root ещё может писать.
Уменьши резерв до 1% и объясни, почему на корневой ФС так делать не стоит.

### C10. Планировщик
Посмотри активный планировщик `vda` и `vdb`, переключи `vdb` на `mq-deadline`,
повтори профиль 2. Есть ли разница и почему?

---

### Блок D. Инциденты


**D1.** Каждую ночь с 02:00 до 02:40 растёт время коммитов в PostgreSQL. В 02:00 по cron
стартует бэкап на тот же диск. Как доказать связь и что сделать?

<details><summary>Ответ</summary>

Наложить графики: `sar -d -f /var/log/sysstat/saDD -s 01:50:00 -e 02:50:00`
(`await`, `%util`), время коммитов из логов/метрик БД и время cron. `pidstat -d` в окне
бэкапа покажет процесс. Решения: бэкап с реплики, `ionice -c3`/`nice`, ограничить скорость
бэкапа, отдельный диск, сдвинуть окно.

</details>

**D2.** Алерт: `/var` заполнен на 100%. `du -xh --max-depth=1 /var` насчитал 12 ГБ из 50.
Твои шаги?

<details><summary>Ответ</summary>

`sudo lsof -nP +L1 | grep -v memfd` — ищем deleted-файлы на `/var` (часто лог,
удалённый руками или logrotate без HUP). Освободить: `truncate -s 0 /proc/PID/fd/N`, затем
`reload` сервиса и починить logrotate. Если deleted-файлов нет — проверить файлы под точкой
монтирования (bind mount) и снапшоты.

</details>

**D3.** Приложение от пользователя `app` падает с `No space left on device`, а `df -h` показывает

<details><summary>Ответ</summary>

Inodes (`df -i`) и reserved blocks (`tune2fs -l`, у пользователя `app` резерв
недоступен). Третий вариант — квоты (`quota -u app`), если включены.

</details>

**70.** % занято. Какие две причины проверишь первыми и как?
**D4.** Подключили новый диск и смонтировали на `/var/lib/docker`. Место на `/` не освободилось,
хотя старые образы «переехали». Что случилось?

<details><summary>Ответ</summary>

Старые данные остались на корневой ФС в каталоге `/var/lib/docker` под новой точкой
монтирования. Их не видно, но место они занимают. Найти через `mount --bind / /mnt/rootview`
и `du -sh /mnt/rootview/var/lib/docker`, удалить (при остановленном docker), размонтировать.

</details>

**D5.** etcd в кластере пишет в лог `slow fdatasync` и `apply request took too long`,
лидер переизбирается. Как проверить диск и что посоветовать?

<details><summary>Ответ</summary>

etcd на каждый коммит делает `fdatasync`, и медленный диск ломает кворум. Проверка:
fio-профиль из документации etcd (`--rw=write --ioengine=sync --fdatasync=1 --bs=2300
--size=22m`) — p99 должен быть < 10 мс; метрика `etcd_disk_wal_fsync_duration_seconds`;
`iostat` — `f_await`/`w_await`. Совет: выделенный SSD/NVMe или облачный том с гарантированными
IOPS, не делить диск с логами и контейнерами.

</details>

**D6.** Сервис на машине со 128 ГБ RAM пишет много логов и данных; каждые 20–40 секунд
latency всех запросов подскакивает. CPU свободен. Гипотеза и как её проверить?

<details><summary>Ответ</summary>

Writeback-шторм: при 128 ГБ RAM `dirty_background_ratio` 10% — это ~12 ГБ
грязных данных до начала сброса. Проверка: `grep -E '^(Dirty|Writeback)' /proc/meminfo` в цикле
и `iostat -dxz 1` — пики `Writeback` и `w_await` совпадают со всплесками latency.
Фикс: `vm.dirty_background_bytes` ~ 256 МБ и `vm.dirty_bytes` ~ 1 ГБ (подобрать замером),
вынести логи на отдельный диск.

</details>

**D7.** Утром все сервисы на хосте пишут `Read-only file system`. Дежурный хочет
`mount -o remount,rw /`. Что сначала?

<details><summary>Ответ</summary>

Сначала `dmesg -T`/`journalctl -k`: почему ФС ушла в read-only (ошибки I/O,
повреждение журнала). Проверить состояние диска/тома, сделать бэкап важного, затем
плановый `fsck` на размонтированной ФС (для корня — rescue/live). `remount,rw` без
починки — риск испортить ФС окончательно.

</details>

**D8.** Облачный том: IOPS весь день ровно 3000, `r_await` вырос с 1 до 20 мс,
`%util` 100%. Команда предлагает поменять планировщик. Что на самом деле?

<details><summary>Ответ</summary>

Том упёрся в свой лимит IOPS: ровная полка ровно на 3000, растущая очередь и
`await`. Планировщик не поможет. Нужно: увеличить IOPS тома (класс/размер/provisioned IOPS),
уменьшить I/O (кэш, индексы, батчи) или распределить нагрузку по томам.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как понять, что узкое место — диск?

<details><summary>Ответ</summary>

Высокий `await` и `aqu-sz` в `iostat -x`, процессы в `D` (`vmstat` колонка `b`), рост PSI io,
   `iowait` при свободном CPU; подтверждаю, какой процесс грузит (`pidstat -d`), и сравниваю
   с пределом устройства из fio.

</details>

**2.** Чем `%util` отличается от `await`? Чему верить на NVMe?

<details><summary>Ответ</summary>

`%util` — доля времени, когда был хоть один запрос; `await` — сколько запрос реально ждёт.
   На NVMe `%util` почти всегда 100% под нагрузкой и ничего не значит — верю `await`, `aqu-sz`
   и IOPS против известного предела.

</details>

**3.** Как бы ты измерил производительность диска?

<details><summary>Ответ</summary>

fio на файле с `--direct=1`, профили под нагрузку: random 4k qd1 (latency), random 4k
   qd32 (IOPS), sequential 1M (MB/s), запись с `fdatasync` для БД; смотрю p99/p99.9,
   параллельно `iostat -x`.

</details>

**4.** Что такое page cache и dirty pages?

<details><summary>Ответ</summary>

Page cache — кэш файлов в свободной RAM: чтение из него не трогает диск. Dirty pages —
   изменённые в кэше, но не записанные страницы; flusher сбрасывает их по порогам
   `dirty_background_ratio`/`dirty_ratio` и таймерам, `fsync` — принудительно.

</details>

**5.** Диск заполнен, а `du` показывает гораздо меньше. Что делаешь?

<details><summary>Ответ</summary>

`lsof +L1` — удалённые открытые файлы; bind-mount корня — файлы под точками монтирования;
   reserved blocks; снапшоты и метаданные ФС.

</details>

**6.** Как освободить место от удалённого, но открытого лога без рестарта сервиса?

<details><summary>Ответ</summary>

`sudo lsof -nP +L1` → PID и FD → `truncate -s 0 /proc/PID/fd/FD`; потом `reload`/HUP,
   чтобы процесс переоткрыл файл, и чиню logrotate.

</details>

**7.** Что такое inode и что будет, когда они кончатся?

<details><summary>Ответ</summary>

Inode — структура с метаданными файла (права, владелец, размер, указатели на блоки,
   число ссылок). Их число задаётся при создании ext4; когда кончатся, создать файл нельзя:
   `No space left on device` при свободных байтах, видно в `df -i`.

</details>

**8.** Чем random I/O отличается от sequential и почему это важно?

<details><summary>Ответ</summary>

Random — мелкие запросы в разные места, упираются в IOPS и latency; sequential — крупные
   подряд, упираются в MB/s. HDD на random в сотни раз медленнее, SSD — в разы; профиль
   нагрузки определяет, какой диск и какие метрики нужны.

</details>

**9.** Что такое `fsync` и почему он важен для баз данных и etcd?

<details><summary>Ответ</summary>

`fsync` сбрасывает данные файла и метаданные из кэша на устройство и ждёт подтверждения.
   БД и etcd вызывают его на каждый коммит ради durability, поэтому latency `fsync`
   напрямую = latency транзакции/записи в кластер.

</details>

**10.** Какие типичные причины «медленного диска» в облаке?

<details><summary>Ответ</summary>

Лимиты IOPS/MB/s тома и исчерпание burst-кредитов, шумные соседи, сетевое хранилище
    (latency по сети), маленький том с маленьким лимитом, writeback-штормы и `fsync`-нагрузка
    на одном томе с логами.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю каждую колонку `iostat -x`, проверяю вывод законом Литтла
- [ ] ⭐ Не верю `%util` на SSD/NVMe и знаю, что смотреть вместо него
- [ ] Нахожу процесс, который грузит диск, тремя способами
- [ ] Отличаю чтение из кэша от чтения с диска (`rchar` vs `read_bytes`)
- [ ] Снимаю гистограмму latency `biolatency` и вижу хвост
- [ ] ⭐ Составил «паспорт» диска fio: latency, IOPS, MB/s, `fdatasync` p99
- [ ] Объясняю dirty pages и writeback-шторм, видел `Dirty`/`Writeback` своими глазами
- [ ] ⭐ Нахожу и освобождаю deleted-файл без рестарта
- [ ] Знаю все причины «`df` больше `du`» и нашёл файлы под точкой монтирования
- [ ] Отличаю ENOSPC из-за inodes и reserved blocks
- [ ] Разбираю read-only ФС по `dmesg`, не делая слепой `remount,rw`
