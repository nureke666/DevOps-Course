---
title: "14. Мониторинг процессов и cron"
description: "top/htop, load average, iostat, память, потоки, cron — диагностика «сервер тормозит» — конспект и задачи"
---

# 14. Process Utilization — мониторинг и cron

> Источник: `14_process_utilization.txt` (Journeyman, 8 уроков)
> **После темы ты умеешь:** находить, кто ест CPU, память и диск, читать load average
> и настраивать регулярные задачи. Это навык «дежурного инженера».

---

## 🗺️ Схема: четыре ресурса и чем их смотреть

```text:no-line-numbers
            ┌──────────────────────── СЕРВЕР ТОРМОЗИТ ────────────────────────┐
            │                                                                 │
     ┌──────▼──────┐      ┌───────▼──────┐     ┌───────▼──────┐     ┌────────▼───────┐
     │     CPU     │      │    ПАМЯТЬ    │     │     ДИСК     │     │      СЕТЬ      │
     ├─────────────┤      ├──────────────┤     ├──────────────┤     ├────────────────┤
     │ top / htop  │      │ free -h      │     │ iostat -x    │     │ ss -s          │
     │ uptime      │      │ vmstat       │     │ iotop        │     │ iftop / nload  │
     │ mpstat -P ALL│     │ ps --sort=-%mem│   │ df / du      │     │ tcpdump        │
     │ pidstat     │      │ smem         │     │ lsof         │     │ ss -tunap      │
     └─────────────┘      └──────────────┘     └──────────────┘     └────────────────┘
            │                    │                    │                     │
            └────────────────────┴──── ОБЩЕЕ: top, vmstat 1, dstat, sar ────┘
```

**Универсальный первый шаг:** `uptime` → `top` → `vmstat 1 5` → дальше по подозреваемому ресурсу.

---

## 1. top — главный инструмент

```bash
top
htop           # красивее и удобнее (sudo apt install htop)
```

Шапка `top` — читаем построчно:

```text:no-line-numbers
top - 14:23:01 up 5 days,  3:42,  2 users,  load average: 0.52, 0.58, 0.59
Tasks: 142 total,   1 running, 141 sleeping,   0 stopped,   0 zombie
%Cpu(s):  3.2 us,  1.1 sy,  0.0 ni, 95.4 id,  0.3 wa,  0.0 hi,  0.0 si,  0.0 st
MiB Mem :   1987.4 total,    234.1 free,    892.3 used,    861.0 buff/cache
MiB Swap:   2048.0 total,   2048.0 free,      0.0 used.   1002.1 avail Mem
```

| Поле | Значение |
|------|----------|
| `load average` | Средняя очередь за 1 / 5 / 15 минут |
| `us` (user) | CPU на пользовательский код |
| `sy` (system) | CPU в ядре (syscalls, I/O) |
| `ni` | Процессы с изменённым nice |
| `id` (idle) | Простой |
| **`wa`** (iowait) | **Ждём диск/сеть** ← если высокий, проблема в I/O |
| `hi`/`si` | Аппаратные/программные прерывания |
| **`st`** (steal) | **Время, отобранное гипервизором** ← «сосед шумит» в облаке |
| `buff/cache` | Кэш ФС — **это не занятая память**, она освободится по требованию |
| `avail Mem` | ⭐ Реально доступная память — смотри сюда, а не на `free` |

**Load average — самое частое непонимание:**
```text:no-line-numbers
load average: 2.50, 1.80, 1.20
                │     │     └─ за 15 минут (тренд)
                │     └─ за 5 минут
                └─ за 1 минуту (сейчас)

Интерпретация (для N ядер):
  load < N      — всё в порядке
  load ≈ N      — система загружена под завязку
  load > N      — есть очередь, задержки

⚠️ В Linux в load входят не только процессы, ждущие CPU, но и процессы в состоянии D
   (непрерываемый I/O). Поэтому load 40 при простаивающем CPU = проблема с диском/сетью.
```

Горячие клавиши в `top`:

| Клавиша | Действие |
|---------|----------|
| `M` | Сортировать по памяти |
| `P` | Сортировать по CPU |
| `T` | По времени работы |
| `1` | Показать каждое ядро отдельно |
| `c` | Полная командная строка |
| `u` | Фильтр по пользователю |
| `k` | Убить процесс |
| `r` | renice |
| `H` | Показать **потоки** |
| `W` | Сохранить настройки |
| `q` | Выход |

```bash
top -b -n1 | head -20                     # batch-режим — для скриптов и логов
top -b -n1 -o %MEM | head -15             # сразу отсортировать по памяти
top -p 1234                               # только конкретный процесс
```

---

## 2. lsof и fuser — кто держит файл/порт

```bash
lsof                        # ВСЕ открытые файлы (огромный вывод)
lsof -p 1234                # файлы конкретного процесса
lsof /var/log/app.log       # кто держит этот файл
lsof +D /mnt/data           # кто держит что-либо в каталоге (рекурсивно)
lsof -u nurik               # файлы пользователя
lsof -i                     # сетевые соединения
lsof -i :80                 # ⭐ кто занял порт 80
lsof -i TCP:LISTEN          # все слушающие сокеты
lsof +L1                    # ⭐ удалённые, но открытые файлы (съедают место)
lsof -c nginx               # по имени команды

fuser -v /var/log/app.log   # какие процессы используют файл
fuser -k /var/log/app.log   # убить их
fuser -vm /mnt/data         # процессы, мешающие размонтировать
fuser -n tcp 8080           # кто на порту
```

💡 Современная альтернатива для портов — `ss`:
```bash
ss -tulpn                   # все слушающие TCP/UDP с PID ← используй это чаще lsof
ss -tulpn | grep :8080
```

---

## 3. Process Threads — потоки

Поток (thread) — единица выполнения внутри процесса; потоки делят память, но имеют свой стек.

```bash
ps -eLf                          # все процессы с потоками
ps -o pid,nlwp,cmd -p 1234       # nlwp = число потоков у процесса
ps -T -p 1234                    # потоки конкретного процесса
top -H -p 1234                   # потоки в top
cat /proc/1234/status | grep Threads
ls /proc/1234/task/ | wc -l
```

💼 Зачем: у JVM/Go/nginx сотни потоков; «процесс ест 400% CPU» означает 4 ядра, занятых потоками.
Найти проблемный поток → сопоставить с thread dump приложения → найти узкое место в коде.

---

## 4. CPU Monitoring

```bash
uptime                             # быстрый взгляд на load average
nproc                              # число ядер (важно для интерпретации load)
lscpu                              # подробно о процессоре

sudo apt install -y sysstat        # даёт mpstat, iostat, pidstat, sar

mpstat 1 5                         # загрузка CPU каждую секунду, 5 раз
mpstat -P ALL 1                    # по каждому ядру отдельно ← ловит «одно ядро в полке»
pidstat 1 5                        # по процессам
pidstat -u -p 1234 1               # CPU конкретного процесса
vmstat 1 5                         # общая картина: процессы, память, swap, io, cpu

ps aux --sort=-%cpu | head -10
```

`vmstat 1` — что смотреть:
```text:no-line-numbers
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 2  0      0 234112  61232 800164    0    0     5    12  120  245  3  1 95  1  0
 │  │                                │    │     │     │              │  │  │  │
 │  │                                │    │     │     │              │  │  │  └ ждём I/O
 │  │                                │    │     │     └ блоков записано  │
 │  │                                │    │     └ блоков прочитано       └ idle
 │  │                                └ swap in/out (>0 постоянно = мало RAM!)
 │  └ процессы в непрерываемом сне (D) ← проблема с I/O
 └ процессы в очереди на CPU ← если стабильно > числа ядер, CPU в дефиците
```

---

## 5. I/O Monitoring

```bash
iostat -x 1 5                      # ⭐ расширенная статистика по устройствам
iostat -xh 1                       # человекочитаемо

sudo iotop -o                      # ⭐ какие ПРОЦЕССЫ грузят диск (только активные)
sudo iotop -oPa                    # накопительно, по процессам

pidstat -d 1                       # I/O по процессам без iotop
cat /proc/1234/io                  # сколько байт прочитал/записал процесс
df -h; df -i; du -xh --max-depth=1 /var | sort -rh | head
```

Ключевые метрики `iostat -x`:

| Метрика | Смысл | Тревога |
|---------|-------|---------|
| `r/s`, `w/s` | Операций чтения/записи в секунду (IOPS) | — |
| `rkB/s`, `wkB/s` | Пропускная способность | — |
| `await` | Среднее время ожидания операции, мс | > 20 мс для SSD — плохо |
| `%util` | Процент времени, когда устройство было занято | > 80% — узкое место |
| `aqu-sz` | Средняя длина очереди | Растёт → перегрузка |

⚠️ Для NVMe и RAID `%util` может вводить в заблуждение (они обрабатывают запросы параллельно) —
смотри в первую очередь на `await` и на latency со стороны приложения.

---

## 6. Memory Monitoring

```bash
free -h                     # ⭐ основная команда
free -h -s 2                # обновлять каждые 2 секунды
cat /proc/meminfo           # детально
vmstat -s                   # сводка

ps aux --sort=-%mem | head -10
ps -eo pid,user,rss,vsz,comm --sort=-rss | head
smem -rs uss                # честный учёт (sudo apt install smem)
sudo pmap -x 1234           # карта памяти процесса
```

**Как правильно читать `free -h`:**
```text:no-line-numbers
              total   used   free   shared  buff/cache   available
Mem:           1.9Gi  892Mi  234Mi    12Mi       861Mi      1002Mi
                                                              │
   НЕ пугайся маленького "free" — Linux использует свободную   │
   память под кэш. Реальный показатель — "available" ──────────┘
```

**OOM killer** — когда памяти действительно нет, ядро убивает процесс с наибольшим `oom_score`:
```bash
dmesg -T | grep -i "out of memory"
journalctl -k | grep -i oom
cat /proc/1234/oom_score
echo -500 | sudo tee /proc/1234/oom_score_adj    # защитить важный процесс
```

---

## 7. Continuous Monitoring — наблюдение во времени

```bash
watch -n 2 'df -h; echo; free -h'          # обновлять команду каждые 2 с
watch -d -n 1 'ss -s'                      # -d подсвечивает изменения

# sar — исторические данные (пакет sysstat)
sudo systemctl enable --now sysstat
sar -u 1 5              # CPU сейчас
sar -u -f /var/log/sysstat/sa13            # CPU за 13-е число ← «что было ночью»
sar -r                  # память
sar -d                  # диски
sar -n DEV              # сеть
sar -q                  # load average

dstat -cdngy 1          # всё сразу (пакет dstat/pcp-dstat)
glances                 # «швейцарский нож» мониторинга
```

💼 **Главная ценность `sar`:** он пишет метрики каждые 10 минут и позволяет ответить на вопрос
«что происходило в 3 часа ночи, когда всё упало» — когда Grafana ещё не настроена.

**Порог от «посмотрел глазами» к нормальному мониторингу:** Prometheus + node_exporter + Grafana +
Alertmanager. Команды выше — для быстрой диагностики на конкретной машине.

---

## 8. Cron Jobs — планировщик

```bash
crontab -e              # редактировать свои задачи (через $EDITOR)
crontab -l              # показать
crontab -r              # ⚠️ УДАЛИТЬ ВСЕ (легко нажать вместо -e!)
sudo crontab -u nurik -l   # чужие задачи

/etc/crontab               # системный, с полем ПОЛЬЗОВАТЕЛЬ
/etc/cron.d/               # отдельные файлы (удобно для пакетов и Ansible)
/etc/cron.{hourly,daily,weekly,monthly}/   # просто положи скрипт — запустится
/var/spool/cron/crontabs/  # пользовательские crontab-файлы
```

Формат:
```text:no-line-numbers
┌───────────── минута (0-59)
│ ┌─────────── час (0-23)
│ │ ┌───────── день месяца (1-31)
│ │ │ ┌─────── месяц (1-12)
│ │ │ │ ┌───── день недели (0-7, 0 и 7 = воскресенье)
│ │ │ │ │
* * * * *  команда
```

```text:no-line-numbers
*/5 * * * *   /opt/scripts/check.sh              # каждые 5 минут
0 * * * *     /opt/scripts/hourly.sh             # каждый час в :00
0 2 * * *     /opt/scripts/backup.sh             # каждый день в 02:00
0 3 * * 0     /opt/scripts/weekly.sh             # воскресенье в 03:00
30 4 1 * *    /opt/scripts/monthly.sh            # 1-го числа в 04:30
0 9-18 * * 1-5 /opt/scripts/workhours.sh         # по будням с 9 до 18
@reboot       /opt/scripts/on_boot.sh            # при загрузке
@daily        /opt/scripts/daily.sh              # = 0 0 * * *
```

🔴 **Правила cron, нарушение которых = классический инцидент:**

1. **Всегда абсолютные пути** — у cron минимальный `$PATH` (`/usr/bin:/bin`).
2. **Всегда перенаправляй вывод**, иначе он уходит в почту, которой нет:
   ```text:no-line-numbers
   0 2 * * * /opt/backup.sh >> /var/log/backup.log 2>&1
   ```
3. **Экранируй `%`** — в cron это спецсимвол (перевод строки):
   ```text:no-line-numbers
   0 2 * * * /opt/backup.sh $(date +\%F)
   ```
4. **Защита от наложения запусков** (задача не успела — запустилась вторая):
   ```text:no-line-numbers
   */5 * * * * /usr/bin/flock -n /tmp/job.lock /opt/scripts/job.sh
   ```
5. Окружение не твоё: нет `~/.bashrc`, другой `$HOME`, другая локаль. Задавай явно в crontab:
   ```text:no-line-numbers
   SHELL=/bin/bash
   PATH=/usr/local/bin:/usr/bin:/bin
   MAILTO=""
   ```

```bash
# Отладка cron
grep CRON /var/log/syslog | tail -20
journalctl -u cron -n 50
systemctl status cron
run-parts --test /etc/cron.daily      # что запустится
```

**anacron** — для машин, которые выключают: выполняет пропущенные задачи после включения
(`/etc/anacrontab`). Аналог в systemd — `Persistent=true` у таймера (см. тему 13).

**at** — однократный запуск:
```bash
echo "/opt/scripts/once.sh" | at 02:00
atq        # очередь
atrm 1     # удалить задание
```

---

## 🔧 Алгоритм «сервер тормозит» (10 минут)

```text:no-line-numbers
1. uptime                        → load average vs nproc
2. top / htop                    → кто в топе, есть ли zombie/D-процессы
3. vmstat 1 5                    → r (очередь CPU), b (I/O), si/so (swap), wa
4. Если высокий us  → ps aux --sort=-%cpu ; pidstat 1 ; профилировать приложение
   Если высокий sy  → strace -c ; много syscalls/context switch
   Если высокий wa  → iostat -x 1 ; iotop -o ; проверить диск и NFS
   Если высокий st  → проблема на стороне гипервизора/облака (шумный сосед)
5. free -h                       → available, swap in/out
6. df -h && df -i                → место и inode
7. ss -s && ss -tulpn            → соединения, порты
8. dmesg -T | tail && journalctl -p err -n 50   → ошибки ядра, OOM
9. sar -u -f ...                 → что было раньше (исторические данные)
```

---

## 💼 Как это в DevOps

- Это буквально «дежурство»: алерт → SSH → эти команды → гипотеза → фикс.
- Метрики отсюда собирает node_exporter → Prometheus → Grafana → Alertmanager.
- `load average`, `iowait`, `steal`, `available memory` — базовые алерты в любом мониторинге.
- Cron → постепенно вытесняется systemd-таймерами и Kubernetes CronJob, но встречается везде.
- `flock` в cron — простейшая защита от параллельных запусков (в k8s — `concurrencyPolicy: Forbid`).

---

## 🧪 Мини-лаба

```bash
vagrant ssh
sudo apt update && sudo apt install -y htop sysstat iotop stress-ng

# 1. Базовая картина
uptime; nproc; free -h; df -h
top -b -n1 | head -15
vmstat 1 3

# 2. Нагрузка на CPU — смотри, как меняется load average
stress-ng --cpu 2 --timeout 60s &
sleep 5; uptime; top -b -n1 | head -8; mpstat -P ALL 1 3
wait

# 3. Нагрузка на память
stress-ng --vm 1 --vm-bytes 1G --timeout 30s &
sleep 5; free -h; ps aux --sort=-%mem | head -5
wait

# 4. Нагрузка на диск — смотри iowait и %util
stress-ng --hdd 1 --hdd-bytes 500M --timeout 30s &
sleep 5; iostat -x 1 3; sudo iotop -b -n2 -o | head -20
wait

# 5. Кто держит файлы и порты
sudo lsof -i -P -n | head
ss -tulpn
sudo lsof +L1 | head

# 6. Потоки
ps -o pid,nlwp,comm -e --sort=-nlwp | head -5

# 7. Непрерывное наблюдение
watch -n 2 'uptime; echo; free -h | head -2'    # Ctrl+C для выхода

# 8. Исторические данные
sudo systemctl enable --now sysstat
sar -u 1 3
ls /var/log/sysstat/ 2>/dev/null

# 9. Cron
crontab -l 2>/dev/null
(crontab -l 2>/dev/null; echo "* * * * * /usr/bin/date >> /tmp/cron_test.log 2>&1") | crontab -
crontab -l
sleep 70; cat /tmp/cron_test.log
grep CRON /var/log/syslog | tail -5
crontab -l | grep -v cron_test | crontab -      # аккуратно убрать свою задачу
rm -f /tmp/cron_test.log

# 10. Защита от наложения запусков
flock -n /tmp/demo.lock -c 'echo "первый пошёл"; sleep 10' &
sleep 1
flock -n /tmp/demo.lock -c 'echo "второй"' || echo "второй НЕ запустился — блокировка работает"
wait
```

---

## 📌 Шпаргалка

| Что нужно | Команда |
|-----------|---------|
| Общая картина | `top` / `htop`, `uptime`, `vmstat 1` |
| Топ по CPU | `ps aux --sort=-%cpu \| head` |
| Топ по памяти | `ps aux --sort=-%mem \| head` |
| CPU по ядрам | `mpstat -P ALL 1` |
| CPU по процессам | `pidstat 1` |
| Диск (устройства) | `iostat -x 1` |
| Диск (процессы) | `sudo iotop -o` |
| Память | `free -h`, `/proc/meminfo`, `smem` |
| Кто держит файл | `lsof <файл>`, `fuser -v <файл>` |
| Кто занял порт | `ss -tulpn`, `lsof -i :80` |
| Удалённые открытые файлы | `lsof +L1` |
| Потоки процесса | `ps -T -p PID`, `top -H -p PID` |
| Наблюдение | `watch -n 2 'команда'` |
| История метрик | `sar -u/-r/-d/-q [-f файл]` |
| OOM | `dmesg -T \| grep -i oom` |
| Cron | `crontab -e/-l`, `/etc/cron.d/`, `flock` |

---

## 🧠 Что запомнить

1. `load average` считает и процессы в состоянии `D` → высокий load при простаивающем CPU = проблема I/O.
2. Сравнивай load с `nproc`: load 4 на 8 ядрах — норма, на 2 ядрах — перегрузка.
3. В `free -h` смотри на **available**, а не на `free`: `buff/cache` освободится при необходимости.
4. `wa` (iowait) высокий → `iostat -x` и `iotop`; `st` (steal) высокий → проблема у гипервизора.
5. `si`/`so` в `vmstat` постоянно > 0 = система свопится = не хватает RAM.
6. `ss -tulpn` — кто слушает порт; `lsof +L1` — кто держит удалённые файлы.
7. Cron: **абсолютные пути**, `>> log 2>&1`, экранировать `%`, `flock` от наложения.
8. `sar` даёт историю метрик без Prometheus — «что было ночью».
9. Алгоритм: uptime → top → vmstat → адресно по ресурсу → dmesg/journal.

➡️ Дальше: [15. Логирование](/linux/15-logging)

---

## Задачи

> `vagrant snapshot save before_14 && vagrant ssh`
> Установи инструменты: `sudo apt install -y htop sysstat iotop stress-ng`

---

### Блок A. Теория

**A1.** Что такое load average? Почему три числа? Как правильно интерпретировать `load 4.0`?

<details><summary>Ответ</summary>

Среднее число процессов в очереди на выполнение (runnable) **плюс** в непрерываемом сне (D)
за 1, 5 и 15 минут. Три числа дают тренд: растёт нагрузка или спадает. `load 4.0` — норма для
4+ ядер, перегрузка для 2 ядер. Всегда сравнивай с `nproc`.

</details>

**A2.** Почему в Linux load average может быть высоким при почти простаивающем CPU?

<details><summary>Ответ</summary>

Потому что в Linux в load учитываются процессы в состоянии `D` — ожидание дискового или
сетевого ввода-вывода. Зависший NFS, сбойный диск или перегруженное хранилище дают огромный load
при простаивающем процессоре.

</details>

**A3.** Что означают в `top`: `us`, `sy`, `ni`, `id`, `wa`, `si`, `st`? На какие смотришь
при жалобе «сервер тормозит»?

<details><summary>Ответ</summary>

`us` — пользовательский код; `sy` — код ядра (syscalls); `ni` — процессы с изменённым nice;
`id` — простой; `wa` — ожидание I/O; `si`/`hi` — программные/аппаратные прерывания;
`st` — время, украденное гипервизором. При жалобе смотрю в первую очередь на `wa`, `st` и
соотношение `us`/`sy`.

</details>

**A4.** Что такое `steal time` и что он говорит о проблеме?

<details><summary>Ответ</summary>

Доля времени, когда виртуальная машина была готова выполняться, но физический CPU был отдан
другой ВМ. Высокий steal = проблема на стороне гипервизора/облака (переподписка, «шумный сосед»).
Внутри ВМ не лечится: нужно менять тип инстанса, переносить на другой хост или обращаться к провайдеру.

</details>

**A5.** Почему в `free -h` мало «free», и это нормально? На какое поле смотреть вместо него?

<details><summary>Ответ</summary>

Linux использует незанятую память под страничный кэш (`buff/cache`), потому что простаивающая
память бесполезна. Этот кэш мгновенно освобождается при запросе приложения. Смотреть надо на
колонку **available**.

</details>

**A6.** Чем `buff/cache` отличается от `used`?

<details><summary>Ответ</summary>

`used` — память, занятая процессами (анонимные страницы). `buff/cache` — кэш файловой
системы и буферы блочных устройств: технически занята, но доступна для немедленного освобождения.

</details>

**A7.** Что делает OOM killer? Как он выбирает жертву и как защитить важный процесс?

<details><summary>Ответ</summary>

Когда физическая память и swap исчерпаны, ядро выбирает процесс с наибольшим `oom_score`
(зависит от объёма потребляемой памяти и `oom_score_adj`) и убивает его SIGKILL, чтобы система
выжила. Защитить: `echo -1000 > /proc/<pid>/oom_score_adj` (или `OOMScoreAdjust=` в systemd-юните),
а по-хорошему — ограничить память через cgroups/`MemoryMax` и устранить причину.

</details>

**A8.** В `iostat -x` — что означают `await`, `%util`, `aqu-sz`? Какие значения тревожные?

<details><summary>Ответ</summary>

`await` — среднее время обслуживания запроса (ожидание + выполнение), мс; для SSD норма
единицы мс, >20 мс — проблема. `%util` — доля времени, когда устройство обрабатывало запросы;
>80% для HDD — насыщение (для NVMe/RAID показатель некорректен). `aqu-sz` — средняя длина очереди;
устойчивый рост означает, что диск не справляется.

</details>

**A9.** Чем `lsof` отличается от `fuser`? Что быстрее для поиска «кто занял порт»?

<details><summary>Ответ</summary>

`lsof` — универсальный инструмент: показывает все открытые файлы, сокеты, каталоги,
с подробностями, но медленный. `fuser` — быстрый и узкоспециализированный: какие процессы
используют файл/точку монтирования/порт, умеет их убивать (`-k`). Для «кто занял порт» быстрее
всего `ss -tulpn`.

</details>

**A10.** Что такое поток (thread) и чем он отличается от процесса? Как посмотреть потоки?

<details><summary>Ответ</summary>

Поток — единица планирования внутри процесса; потоки одного процесса делят адресное
пространство и дескрипторы, но имеют свой стек и регистры. Смотреть: `ps -T -p PID`,
`top -H -p PID`, `ls /proc/PID/task`, `ps -eLf`.

</details>

**A11.** Почему cron-задача работает вручную, но не работает из cron? Назови 4 причины.

<details><summary>Ответ</summary>

(1) Другой `$PATH` — команда не найдена (нужны абсолютные пути). (2) Другое окружение:
нет `~/.bashrc`, переменных, другой `$HOME`, другая локаль. (3) Нет терминала — падают команды,
требующие tty, а вывод уходит в почту и теряется. (4) Права: задача выполняется от другого
пользователя или без sudo. Плюс неэкранированный `%` и относительные пути внутри скрипта.

</details>

**A12.** Что делает `flock` в cron-строке и зачем это нужно?

<details><summary>Ответ</summary>

`flock -n /tmp/job.lock команда` берёт эксклюзивную блокировку на файл; если предыдущий
запуск ещё идёт, новый немедленно завершается. Это защищает от наложения долгих задач
(бэкапов, rsync, импортов), которые иначе накапливаются и «съедают» сервер.

</details>

**A13.** Чем `sar` полезнее `top` при разборе ночного инцидента?

<details><summary>Ответ</summary>

`top` показывает только текущий момент. `sar` (из пакета sysstat) собирает метрики
каждые 10 минут и хранит их посуточно в `/var/log/sysstat/`, поэтому позволяет посмотреть
CPU, память, диск, сеть и load в момент прошедшего инцидента.

</details>

**A14.** Расшифруй cron-выражения: `*/15 * * * *`, `0 3 * * 1`, `30 2 1 * *`, `0 9-18 * * 1-5`, `@reboot`.

<details><summary>Ответ</summary>

`*/15 * * * *` — каждые 15 минут; `0 3 * * 1` — каждый понедельник в 03:00;
`30 2 1 * *` — 1-го числа каждого месяца в 02:30; `0 9-18 * * 1-5` — каждый час с 9:00 до 18:00
по будням; `@reboot` — один раз при загрузке системы.

</details>

---

### Блок B. «Что покажет / что делает»

```bash
B1.  uptime
B2.  top -b -n1 -o %MEM | head -12
B3.  vmstat 1 5
B4.  mpstat -P ALL 1 3
B5.  pidstat -u 1 3
B6.  iostat -x 1 3
B7.  sudo iotop -o -b -n2
B8.  free -h -s 2
B9.  ps -eo pid,nlwp,comm --sort=-nlwp | head
B10. lsof -i :22
B11. sudo lsof +L1
B12. fuser -vm /mnt/data
B13. watch -d -n1 'ss -s'
B14. sar -u -f /var/log/sysstat/sa13
B15. crontab -l | grep -v '^#'
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Время работы системы, число пользователей и load average за 1/5/15 минут.
B2.  Снимок top в неинтерактивном режиме, отсортированный по памяти.
B3.  Пять снимков системной статистики с интервалом 1 с: очередь процессов, память, swap, I/O, CPU.
B4.  Загрузка каждого ядра отдельно — видно перекос на одно ядро.
B5.  Использование CPU по процессам.
B6.  Расширенная статистика по блочным устройствам: IOPS, пропускная способность, await, %util.
B7.  Процессы, активно использующие диск (batch-режим, 2 замера).
B8.  Использование памяти с обновлением каждые 2 секунды.
B9.  Процессы с наибольшим числом потоков.
B10. Какой процесс использует порт 22.
B11. Удалённые, но всё ещё открытые файлы — они держат место на диске.
B12. Процессы, использующие смонтированную ФС (мешающие umount).
B13. Статистика сокетов с обновлением каждую секунду и подсветкой изменений.
B14. Историческая загрузка CPU за 13-е число месяца.
B15. Активные задачи cron текущего пользователя без комментариев.
```

</details>

**B16.** Чем `ps aux` отличается от `top` по сути измерения `%CPU`?

<details><summary>Ответ</summary>

`ps aux` показывает **средний** `%CPU` за всё время жизни процесса (CPU-time / uptime),
поэтому долгоживущий процесс с давним пиком выглядит нагруженным. `top` считает загрузку за
**интервал обновления**, то есть показывает, что происходит сейчас.

</details>

---

### Блок C. Практика

#### C1. Снимок состояния

Собери одной серией команд:
- load average и число ядер;
- топ-5 процессов по CPU и по памяти;
- доступную память;
- заполненность дисков (место и inode);
- число процессов, зомби и процессов в состоянии D.

<details><summary>Ответ</summary>

```bash
uptime; nproc
ps aux --sort=-%cpu | head -6
ps aux --sort=-%mem | head -6
free -h
df -h; df -i
echo "procs: $(ps -e --no-headers | wc -l)"
echo "zombies: $(ps -eo stat --no-headers | grep -c '^Z')"
echo "D-state: $(ps -eo stat --no-headers | grep -c '^D')"
```

</details>

#### C2. CPU-нагрузка

Через `stress-ng --cpu 2` создай нагрузку на 60 секунд и зафиксируй:
- как менялся load average (сразу, через 10 с, через 60 с) — объясни инерцию;
- что показывал `mpstat -P ALL`;
- какой процесс был в топе `pidstat`.

<details><summary>Ответ</summary>

```bash
stress-ng --cpu 2 --timeout 60s &
uptime; sleep 10; uptime; sleep 50; uptime
mpstat -P ALL 1 3
pidstat -u 1 3 | head
wait
```

Load average — экспоненциально сглаженное среднее, поэтому первая цифра растёт не сразу
(за ~1 минуту) и так же медленно спадает после снятия нагрузки. Это не ошибка, а инерция метрики.

</details>

#### C3. Память

Создай нагрузку `stress-ng --vm 1 --vm-bytes 1200M` и понаблюдай:
- изменения в `free -h` (поля used / available / buff-cache);
- появился ли своп (`si`/`so` в `vmstat`);
- сработает ли OOM killer, если запросить больше памяти, чем есть (проверь `dmesg`).

<details><summary>Ответ</summary>

```bash
free -h
stress-ng --vm 1 --vm-bytes 1200M --timeout 30s &
sleep 5; free -h; vmstat 1 3
wait
stress-ng --vm 1 --vm-bytes 4G --timeout 20s   # заведомо больше RAM
dmesg -T | grep -i "out of memory" | tail -5
```

</details>

#### C4. Диск

Создай I/O-нагрузку и зафиксируй:
- `wa` в `top`;
- `%util` и `await` в `iostat -x`;
- какой процесс виноват (через `iotop`);
- сколько байт записал процесс (через `/proc/PID/io`).

<details><summary>Ответ</summary>

```bash
stress-ng --hdd 1 --hdd-bytes 500M --timeout 40s &
sleep 3; top -b -n1 | head -4; iostat -x 1 3; sudo iotop -b -n2 -o | head
PID=$(pgrep -f 'stress-ng.*hdd' | head -1); cat /proc/$PID/io
wait
```

</details>

#### C5. Кто занял ресурс

1. Запусти `python3 -m http.server 8080 &`.
2. Найди, кто слушает порт 8080, тремя разными способами.
3. Найди все открытые этим процессом файлы.
4. Заверши процесс, используя информацию из вывода.

<details><summary>Ответ</summary>

```bash
python3 -m http.server 8080 >/dev/null 2>&1 &
ss -tulpn | grep :8080
sudo lsof -i :8080
sudo fuser -n tcp 8080
PID=$(ss -tulpnH 'sport = :8080' | grep -oP 'pid=\K[0-9]+' | head -1)
sudo lsof -p "$PID" | head
kill "$PID"
```

</details>

#### C6. Удалённый открытый файл

Воспроизведи, найди через `lsof +L1`, освободи место
двумя способами. (Повтор навыка из темы 10 — доведи до автоматизма.)

<details><summary>Ответ</summary>

```bash
dd if=/dev/zero of=/tmp/ghost.bin bs=1M count=300 status=none
tail -f /tmp/ghost.bin >/dev/null & T=$!
rm /tmp/ghost.bin; df -h /tmp | tail -1
sudo lsof +L1 | grep ghost
truncate -s 0 /proc/$T/fd/3 2>/dev/null || kill $T
df -h /tmp | tail -1
```

</details>

#### C7. Cron с нуля

Настрой задачу, которая каждую минуту пишет в `/var/log/monitor.log`
строку вида `2026-09-13T10:05:00 load=0.52 mem_avail=1002Mi disk=28%`:
- скрипт в `/usr/local/bin/monitor.sh`;
- задача в crontab пользователя;
- вывод и ошибки логируются;
- добавь защиту от параллельного запуска через `flock`;
- проверь, что задача реально отработала (два способа проверки).

<details><summary>Ответ</summary>

```bash
sudo tee /usr/local/bin/monitor.sh >/dev/null <<'EOS'
#!/usr/bin/env bash
load=$(awk '{print $1}' /proc/loadavg)
mem=$(free -h | awk '/^Mem:/ {print $7}')
disk=$(df -hP / | awk 'NR==2 {print $5}')
echo "$(date -Is) load=$load mem_avail=$mem disk=$disk"
EOS
sudo chmod +x /usr/local/bin/monitor.sh
sudo touch /var/log/monitor.log && sudo chown "$USER" /var/log/monitor.log

(crontab -l 2>/dev/null; echo '* * * * * /usr/bin/flock -n /tmp/monitor.lock /usr/local/bin/monitor.sh >> /var/log/monitor.log 2>&1') | crontab -
crontab -l
sleep 70
tail -3 /var/log/monitor.log            # проверка 1: результат работы
grep CRON /var/log/syslog | tail -3     # проверка 2: факт запуска планировщиком
```

</details>

#### C8. Отладка cron

Специально сломай задачу (относительный путь к команде), убедись,
что она не работает, найди ошибку в логах системы, почини.
Объясни, почему из терминала всё работало.

<details><summary>Ответ</summary>

Типичная поломка — `monitor.sh` вместо `/usr/local/bin/monitor.sh` или вызов `flock`
без пути. В `/var/log/syslog` будет строка от CRON, а рядом — сообщение об ошибке или отсутствие
результата в логе задачи. Из терминала работает, потому что `$PATH` пользователя содержит нужные
каталоги, а у cron `PATH=/usr/bin:/bin`. Лечение: абсолютные пути (или явный `PATH=` в crontab).

</details>

#### C9. Скрипт-дежурного

Напиши `/vagrant/health_check.sh`, который проверяет и выводит
с цветными/текстовыми маркерами:
```text:no-line-numbers
=== HEALTH CHECK 2026-09-13T10:00:00 ===
[OK]   Load average: 0.52 (2 cores)
[WARN] Memory: 89% used, 210Mi available
[OK]   Disk /: 45% used, inodes 12%
[CRIT] Disk /var: 92% used
[OK]   Zombies: 0    D-state: 0
[CRIT] Failed services: myapp.service
[OK]   Swap: not used
--- TOP CPU ---
--- TOP MEM ---
EXIT CODE: 2
```
Требования: exit code 0 (всё ок), 1 (warning), 2 (critical) — чтобы скрипт годился
для мониторинга и cron.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
EXIT=0
warn(){ echo "[WARN] $*"; (( EXIT < 1 )) && EXIT=1; }
crit(){ echo "[CRIT] $*"; EXIT=2; }
ok(){   echo "[OK]   $*"; }

echo "=== HEALTH CHECK $(date -Is) ==="

cores=$(nproc); load=$(awk '{print $1}' /proc/loadavg)
if (( $(echo "$load > $cores * 2" | bc -l) )); then crit "Load average: $load ($cores cores)"
elif (( $(echo "$load > $cores" | bc -l) )); then warn "Load average: $load ($cores cores)"
else ok "Load average: $load ($cores cores)"; fi

read -r total avail <<<"$(free -m | awk '/^Mem:/ {print $2, $7}')"
usedpct=$(( (total - avail) * 100 / total ))
if (( usedpct > 90 )); then crit "Memory: ${usedpct}% used, ${avail}Mi available"
elif (( usedpct > 80 )); then warn "Memory: ${usedpct}% used, ${avail}Mi available"
else ok "Memory: ${usedpct}% used, ${avail}Mi available"; fi

while read -r mnt usep inodep; do
  if (( usep > 90 || inodep > 90 )); then crit "Disk $mnt: ${usep}% used, inodes ${inodep}%"
  elif (( usep > 80 || inodep > 80 )); then warn "Disk $mnt: ${usep}% used, inodes ${inodep}%"
  else ok "Disk $mnt: ${usep}% used, inodes ${inodep}%"; fi
done < <(df -hP -x tmpfs -x devtmpfs | awk 'NR>1{gsub("%","",$5); print $6, $5}' |
         while read -r m u; do i=$(df -iP "$m" | awk 'NR==2{gsub("%","",$5); print $5}'); echo "$m $u $i"; done)

z=$(ps -eo stat --no-headers | grep -c '^Z'); d=$(ps -eo stat --no-headers | grep -c '^D')
(( z > 10 || d > 5 )) && warn "Zombies: $z  D-state: $d" || ok "Zombies: $z  D-state: $d"

f=$(systemctl --failed --no-legend | awk '{print $1}' | paste -sd, )
[ -n "$f" ] && crit "Failed services: $f" || ok "Failed services: none"

sw=$(free -m | awk '/^Swap:/ {print $3}')
(( sw > 100 )) && warn "Swap in use: ${sw}Mi" || ok "Swap: not used"

echo "--- TOP CPU ---"; ps -eo pid,user,%cpu,comm --sort=-%cpu --no-headers | head -3
echo "--- TOP MEM ---"; ps -eo pid,user,%mem,comm --sort=-%mem --no-headers | head -3
echo "EXIT CODE: $EXIT"
exit "$EXIT"
```

</details>

#### C10. Исторические метрики

Включи сбор `sysstat`, подожди 15 минут (или создай нагрузку),
затем покажи через `sar`: загрузку CPU, память, диск и load average за сегодня.
Объясни, где физически лежат эти данные.

<details><summary>Ответ</summary>

```bash
sudo systemctl enable --now sysstat
sudo sed -i 's/^ENABLED=.*/ENABLED="true"/' /etc/default/sysstat 2>/dev/null
sudo systemctl restart sysstat
sar -u; sar -r; sar -d; sar -q
ls -l /var/log/sysstat/
```

Данные лежат в `/var/log/sysstat/saDD` (бинарные снимки за день), собираются заданием
`sysstat-collect.timer`/cron каждые 10 минут.

</details>

---

### Блок D. Инциденты

**D1.** Алерт: «load average 45 на 4-ядерном сервере». `top` показывает `id 92%`.
Что происходит и куда смотреть?

<details><summary>Ответ</summary>

CPU простаивает, значит очередь создают процессы в состоянии `D` — ожидание I/O.
Смотреть: `ps -eo pid,stat,wchan:25,cmd | awk '$2 ~ /D/'`, `iostat -x 1`, `iotop -o`,
`dmesg -T | tail` (ошибки диска), `mount | grep nfs` (зависший сетевой ресурс), состояние СХД.
Частые причины: отвалившийся NFS, деградировавший RAID, умирающий диск, переполненное хранилище.

</details>

**D2.** Приложение отвечает медленно. `top`: `us 15%, sy 5%, wa 60%`. Диагноз и план действий.

<details><summary>Ответ</summary>

Узкое место — дисковый ввод-вывод. План: `iostat -x 1` (найти нагруженное устройство:
`await`, `%util`), `iotop -o` (найти процесс), `pidstat -d 1`. Далее — понять, что это: бэкап,
логирование в дебаг-режиме, тяжёлые запросы БД, нехватка памяти и своп. Меры: перенести задачу
на другое время, `ionice`, ограничить скорость, добавить IOPS/диск, оптимизировать запросы,
вынести логи на отдельный том.

</details>

**D3.** В облаке: `top` показывает `st 35%`. CPU приложения в порядке, но всё тормозит. Что это и что делать?

<details><summary>Ответ</summary>

Steal time — CPU отобран гипервизором: хост переподписан или сосед потребляет ресурсы.
Внутри ВМ не исправляется. Действия: подтвердить метрикой за период (`sar -u`), обратиться
к провайдеру, перенести инстанс (stop/start обычно переезжает на другой хост), сменить тип
инстанса на dedicated/compute-optimized, распределить нагрузку.

</details>

**D4.** `free -h` показывает 100 Mi free из 8 Gi. Разработчик паникует: «утечка памяти!».
Твой ответ и какие команды покажешь.

<details><summary>Ответ</summary>

Это нормальная работа Linux: свободная память используется под страничный кэш и
освобождается по требованию. Показать `free -h` и объяснить колонку **available**;
`cat /proc/meminfo | grep -E 'MemAvailable|Cached'`. Реальные признаки проблемы — низкий
`available`, активный своп (`si`/`so` в `vmstat`), записи OOM в `dmesg`, растущий RSS одного
процесса в динамике (`ps --sort=-rss`, `/proc/PID/status`).

</details>

**D5.** Java-приложение периодически убивается, в `dmesg` — `Out of memory: Killed process (java)`.
Как расследовать и какие есть решения?

<details><summary>Ответ</summary>

Смотреть `dmesg -T | grep -i oom` (сколько памяти было у процесса и общий объём),
`journalctl -k -b -1`, метрики за период. Для JVM обычно: `-Xmx` больше доступной памяти или
не учтена нативная память (metaspace, direct buffers, потоки). Решения: выставить `-Xmx`
с запасом относительно лимита контейнера (или использовать `-XX:MaxRAMPercentage`), задать
`MemoryMax=` в юните/лимиты в k8s, увеличить RAM, найти утечку через heap dump,
защитить критичные процессы `OOMScoreAdjust`.

</details>

**D6.** Бэкап по cron не выполнялся три недели, никто не заметил. Как узнать, что он падал,
и как построить процесс, чтобы такого не повторилось?

<details><summary>Ответ</summary>

Проверить: `grep CRON /var/log/syslog*`, `journalctl -u cron --since -30d`, лог самого
скрипта, время файлов в каталоге бэкапов (`ls -lt`). Процесс: (1) задача должна логировать
результат и возвращать корректный exit code; (2) использовать systemd-таймер с
`OnFailure=`-уведомлением или обёртку с алертом; (3) мониторинг «мёртвой руки» — dead man's switch
(healthchecks.io, Prometheus Pushgateway + алерт на отсутствие метрики); (4) регулярная проверка
восстановления из бэкапа — бэкап без проверки восстановления не считается бэкапом.

</details>

**D7.** Cron-задача, которая делает `rsync`, начала запускаться параллельно сама с собой
и «положила» сеть. Как исправить?

<details><summary>Ответ</summary>

Задача выполняется дольше интервала запуска, экземпляры накладываются.
Исправление: `*/10 * * * * /usr/bin/flock -n /tmp/rsync.lock /opt/scripts/rsync.sh`
(плюс `rsync --bwlimit=...`, `ionice -c3 nice -n19`). В systemd-таймере то же решается
самой природой юнита (повторный запуск не стартует, пока сервис активен).

</details>

**D8.** Ночью сервер был недоступен 20 минут, сейчас всё в порядке. Метрик Prometheus нет.
Как выяснить, что происходило?

<details><summary>Ответ</summary>

`journalctl --since "yesterday 23:00" --until "today 01:00" -p warning`,
`journalctl -b -1 -p err` (если была перезагрузка), `journalctl --list-boots`,
`sar -u -r -q -f /var/log/sysstat/sa<DD>` за нужный день, `dmesg -T` (OOM, ошибки диска),
`last -x | head`, логи приложения и веб-сервера за тот период, `grep CRON /var/log/syslog`
(не совпало ли с бэкапом). Вывод инцидента — поставить нормальный мониторинг (Prometheus +
node_exporter) и алерты.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Сервер тормозит. Твои первые пять команд?

<details><summary>Ответ</summary>

`uptime`, `top` (или `htop`), `vmstat 1 5`, `free -h`, `df -h && df -i`; далее адресно
`iostat -x`/`iotop`, `ss -s`, `dmesg -T | tail`.

</details>

**2.** Что такое load average и как его интерпретировать?

<details><summary>Ответ</summary>

Среднее число процессов, ожидающих CPU **и** находящихся в непрерываемом I/O-сне, за 1/5/15 мин.
Сравнивать с числом ядер; высокий load при низком CPU = проблема ввода-вывода.

</details>

**3.** Как найти процесс, который ест всю память?

<details><summary>Ответ</summary>

`ps aux --sort=-%mem | head`, `top` с сортировкой `M`, `smem -rs uss`, затем смотреть динамику
RSS процесса и `/proc/PID/status`.

</details>

**4.** Как найти, что грузит диск?

<details><summary>Ответ</summary>

`iostat -x 1` (какое устройство), `iotop -o` / `pidstat -d 1` (какой процесс),
`/proc/PID/io` (сколько байт).

</details>

**5.** Почему `free` показывает мало свободной памяти?

<details><summary>Ответ</summary>

Потому что незанятая память используется под кэш ФС; она освобождается по первому требованию.
Смотреть колонку `available`.

</details>

**6.** Как узнать, кто занял порт?

<details><summary>Ответ</summary>

`ss -tulpn | grep :PORT`, `sudo lsof -i :PORT`, `sudo fuser -n tcp PORT`.

</details>

**7.** Как настроить регулярную задачу и что важно не забыть?

<details><summary>Ответ</summary>

`crontab -e` или файл в `/etc/cron.d/`. Не забыть: абсолютные пути, перенаправление
`>> log 2>&1`, экранирование `%`, `flock` от наложения, корректный пользователь и права,
мониторинг факта успешного выполнения.

</details>

**8.** Чем systemd-timer лучше cron?

<details><summary>Ответ</summary>

Логи в journald, зависимости, ограничения ресурсов и sandbox, `Persistent=` для пропущенных
запусков, удобный `list-timers` и проверяемые календарные выражения.

</details>

**9.** Что такое iowait и steal time?

<details><summary>Ответ</summary>

iowait — доля времени, когда CPU простаивал в ожидании ввода-вывода; steal — время, отнятое
гипервизором у виртуальной машины.

</details>

---

### 🎯 Чек-лист

- [ ] Интерпретирую load average относительно `nproc` и знаю про D-состояние
- [ ] Читаю шапку `top` по полям (`wa`, `st`, `available`)
- [ ] Знаю, почему «мало free памяти» — это нормально
- [ ] Нахожу пожирателя CPU / памяти / диска за три команды
- [ ] Умею `ss -tulpn`, `lsof -i`, `lsof +L1`
- [ ] Настроил cron с `flock` и логированием
- [ ] Написал `health_check.sh` с корректными exit-кодами
- [ ] Знаю про `sar` и где лежат исторические метрики
