---
title: "08. Практика: 6 инцидентов на стенде"
description: "Блок → Deep Linux Troubleshooting & Performance → практика."
---

# 08. Практика: 6 инцидентов на стенде

> Блок → Deep Linux Troubleshooting & Performance → практика.
> Каждая лаба — маленький инцидент по одной схеме: **сломать → найти методом → доказать
> причину командой → починить → записать мини-постмортем**. Стенд — VM `perf-lab`
> из [00_INDEX.md](/performance/).
>
> ⚠️ Всё ниже ломает систему по-настоящему (OOM, заполненный диск, D-state, дропы пакетов).
> **Только на VM**, перед каждой лабой — `vagrant snapshot save before_lab_N`.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ CPU hog: найти горячую функцию и построить flame graph | темы 01, 02, 07 | `cpu.svg`, `py.svg`, замер до/после |
| 2 | ⭐ Утечка памяти до OOM: cgroup OOM и глобальный OOM, разбор отчёта | тема 02 (+06) | разобранный OOM-отчёт, график RSS |
| 3 | «Диск полон, а файлов нет» | тема 03 | место освобождено без рестарта |
| 4 | conntrack table full / исчерпание эфемерных портов | тема 04 | счётчики до/после, sysctl-фикс |
| 5 | ⭐ CPU throttling в контейнере при «30% CPU» | тема 06 | `cpu.stat` до/после, p90 до/после |
| 6 | D-state: зависший процесс на «умирающем» диске + strace медленного приложения | темы 03, 05 | стек из `/proc/PID/stack`, strace-сводка |

## 📝 Мини-постмортем (для каждой лабы)

Полный шаблон и культура blameless — в [../SRE/05_postmortems.md](/sre/05-postmortems).
Для лаб хватит короткой версии, файл `~/perf/labN/postmortem.md`:

```markdown
# PM-lab-N: &lt;что случилось одной строкой&gt;
**Симптом:**        как это увидел бы пользователь или алерт
**Обнаружение:**    метод (60 секунд / USE / RED) и команды по порядку, с временем
**Доказательство:** команда + фрагмент вывода, который однозначно показывает причину
**Причина:**        триггер и сопутствующие факторы (почему не поймали раньше)
**Фикс:**           что сделал сейчас (mitigation) и что сделать навсегда
**Как не повторить:** алерт / лимит / тест / изменение кода — с владельцем и сроком
```text
> 💡 Забрать файл с VM на хост (общей папки у стенда нет):
> `vagrant ssh -c 'cat ~/perf/lab1/cpu.svg' > cpu.svg`.

---

## 🧪 Лаба 1. ⭐ CPU hog: горячая функция и flame graph

### Что делаем
«Сервис отчётов» на Python под нагрузкой съедает CPU. Методом «60 секунд» находим процесс,
perf'ом — горячую функцию на уровне C, py-spy — на уровне Python, строим flame graph'и,
чиним одно место и доказываем эффект цифрами.

### Каркас
```python
# ~/perf/lab1/app.py — «сервис отчётов» с двумя горячими местами
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def checksum(data: bytes) -> int:                 # чистый Python: медленный цикл
    s = 0
    for b in data:
        s = (s * 31 + b) % 1_000_000_007
    return s

def build_report() -> bytes:
    key = hashlib.pbkdf2_hmac("sha256", b"secret", b"salt", 200_000)   # C-код (OpenSSL)
    return str(checksum(key * 20_000)).encode()                        # ~640 КБ на вход

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        out = build_report() if self.path == "/report" else b"ok"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass

ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
```text
```bash
mkdir -p ~/perf/lab1 && cd ~/perf/lab1
python3 -X perf app.py &            # -X perf (Python 3.12+): perf увидит имена Python-функций
APP=$!
for i in 1 2 3 4; do (while true; do curl -s -o /dev/null localhost:8000/report; done) & done

# замер «до»: 20 запросов подряд
time (for i in $(seq 20); do curl -s -o /dev/null localhost:8000/report; done)

# профилирование
sudo perf top -p $APP                  # живой топ (q — выход); Python-имена тут могут не резолвиться
sudo perf record -F 99 -g -p $APP -o perf.data -- sleep 30
# -f: perf-карта /tmp/perf-PID.map принадлежит vagrant, а perf запущен от root — без -f он её игнорирует
sudo perf report -f -i perf.data --stdio --no-children | head -40
sudo perf script -f -i perf.data | ~/FlameGraph/stackcollapse-perf.pl \
  | ~/FlameGraph/flamegraph.pl --title "lab1 perf" > cpu.svg
sudo ~/.local/bin/py-spy top --pid $APP                           # топ Python-функций
sudo ~/.local/bin/py-spy record -o py.svg --pid $APP --duration 30
sudo profile-bpfcc -F 99 -f -p $APP 30 > bpf.folded               # то же через eBPF
~/FlameGraph/flamegraph.pl bpf.folded > bpf.svg

# уборка
kill $(jobs -p)
```text
### Требования
- [ ] «60 секунд» сохранены в файл (`~/perf/60s.sh`); по ним назван ресурс и процесс
- [ ] Объяснено, почему `python3` может показывать > 100% CPU, хотя в Python есть GIL
- [ ] `perf report`: названы 2–3 самые горячие функции и их доля; видно `py::checksum` и
      функции libcrypto (`sha256…`) — если `-X perf` не сработал, объяснено, что показывает
      `_PyEval_EvalFrameDefault`
- [ ] Построены `cpu.svg` (perf) и `py.svg` (py-spy); объяснено, как читать ширину и высоту
      «языков» и чем они отличаются друг от друга
- [ ] Гипотеза записана до фикса: «кэширование ключа уберёт ~X% CPU» (X — по flame graph)
- [ ] Одно изменение: ключ считается один раз (вынести `pbkdf2_hmac` из запроса
      или `functools.lru_cache`), замер «после» тем же `time (…)` и тем же профилем
- [ ] Мини-постмортем с цифрами до/после

### Критерии приёмки
```bash
python3 -X perf -c 'import sys; print(sys.is_stack_trampoline_active())'   # True — трамплины есть
sudo perf report -f -i ~/perf/lab1/perf.data --stdio --no-children --sort symbol | grep -m5 -E 'py::|sha|%'
ls -l ~/perf/lab1/{cpu,py,bpf}.svg                  # три flame graph'а
grep -E 'real' ~/perf/lab1/postmortem.md            # время 20 запросов до и после
```text
### Вопросы себе
- Почему в `perf report` без `-g` и с `-g` доли функций разные? Что такое `self` и `children`?
- Почему `-F 99`, а не 100? Что будет с оверхедом при `-F 10000`?
- Что показал бы `pidstat -u -w 1` у этого процесса: много voluntary или involuntary
  переключений? Почему?
- Flame graph от perf и от py-spy выглядят по-разному. Какой из них ты покажешь разработчику
  и почему?

---

## 🧪 Лаба 2. ⭐ Утечка памяти до OOM

### Что делаем
Процесс с «кэшем без ограничения» медленно съедает память. Ловим утечку по росту RSS,
смотрим, где она (`pmap`, `smaps_rollup`), доводим до OOM — сначала в cgroup с лимитом,
потом глобально — и построчно разбираем отчёт OOM killer.

### Каркас
```python
# ~/perf/lab2/leaky.py — «кэш ответов» без ограничения размера
import os
import time

cache = {}
i = 0
while True:
    cache[i] = os.urandom(1024 * 1024)      # 1 МиБ «ответа» — навсегда
    i += 1
    if i % 100 == 0:
        print(f"cached {i} MiB", flush=True)
    time.sleep(0.05)                        # ~20 МиБ/с
```text
```bash
mkdir -p ~/perf/lab2 && cd ~/perf/lab2

# Часть A — заметить утечку
python3 leaky.py > leaky.log &
P=$!
pidstat -r -p $P 5 6                                   # RSS растёт каждые 5 секунд
while kill -0 $P 2>/dev/null; do echo "$(date +%T) $(ps -o rss= -p $P)"; sleep 5; done > rss.log &
sudo pmap -x $P | sort -k3 -n | tail -5                # самые большие отображения: [ anon ]
grep -E 'Rss|Pss|Private' /proc/$P/smaps_rollup
kill $P

# Часть B — OOM внутри cgroup (как у контейнера)
sudo systemd-run --unit=leaky -p MemoryHigh=250M -p MemoryMax=300M python3 ~/perf/lab2/leaky.py
watch -n1 cat /sys/fs/cgroup/system.slice/leaky.service/memory.events   # high растёт, потом oom_kill
# между 250 и 300 МиБ процесс заметно замедлится — это MemoryHigh: reclaim и притормаживание
systemctl status leaky --no-pager ; journalctl -u leaky --no-pager | tail -5
sudo dmesg -T | grep -A3 -E 'invoked oom-killer|Memory cgroup out of memory'
sudo systemctl reset-failed leaky

# Часть C — глобальный OOM (⚠️ VM может «подвиснуть» на десятки секунд)
python3 ~/perf/lab2/leaky.py > /dev/null &
sleep 1; cat /proc/$!/oom_score /proc/$!/oom_score_adj
wait                                                   # ~3 минуты до OOM на 4 ГБ
sudo dmesg -T | grep -B2 -A40 'invoked oom-killer' > oom-report.txt
```text
### Требования
- [ ] По `rss.log` построен ряд RSS во времени и посчитана скорость утечки (МиБ/мин)
- [ ] Показано, что растёт именно анонимная память (`[ anon ]` в `pmap`, `Private_Dirty`
      в `smaps_rollup`), а не page cache
- [ ] Часть B: объяснено, что делает `MemoryHigh` (торможение и reclaim до убийства) и что
      `MemoryMax` (OOM внутри cgroup); по `memory.events` показаны счётчики `high`, `max`, `oom_kill`
- [ ] В `systemctl status` найден результат `oom-kill`, в `dmesg` — `constraint=CONSTRAINT_MEMCG`
- [ ] Часть C: в `oom-report.txt` подписаны строки: кто вызвал OOM (`invoked oom-killer`,
      `gfp_mask`, `order`), состояние памяти (`Mem-Info`), таблица задач (`rss`,
      `oom_score_adj`), `constraint=CONSTRAINT_NONE`, жертва и её `anon-rss`
- [ ] Объяснено, почему убили именно этот процесс (badness = rss + swap + page tables + adj)
- [ ] Бонус: второй процесс держит 1 ГБ (`python3 -c "x=bytearray(1<&lt;30); import time; time.sleep(3600)"`),
      ему выставлен `oom_score_adj` 500 через `echo 500 | sudo tee /proc/PID/oom_score_adj` —
      докажи, что теперь OOM убивает его, хотя утекает не он
- [ ] Фикс: кэш с ограничением (например, `collections.OrderedDict` с вытеснением после
      200 записей) — RSS выходит на плато, `pidstat -r` это показывает
- [ ] Мини-постмортем: чем cgroup OOM отличается от глобального для пользователя сервиса

### Критерии приёмки
```bash
head -3 ~/perf/lab2/rss.log; tail -3 ~/perf/lab2/rss.log      # рост RSS во времени
journalctl -u leaky --no-pager | grep -i 'oom'                 # «killed by the OOM killer», oom-kill
grep -E 'constraint=|Killed process' ~/perf/lab2/oom-report.txt
sudo dmesg -T | grep -c 'Killed process'                       # ≥ 2 (часть B и часть C)
```text
### Вопросы себе
- Почему `free` в момент перед OOM показывает маленький `buff/cache`? Куда делся кэш?
- Почему VM «подвисает» перед глобальным OOM, хотя свопа нет? (Подсказка: page cache
  исполняемых файлов и thrashing.)
- Что сделал бы systemd-oomd на этой машине и чем он отличается от ядерного OOM killer?
- Почему `oom_score` у крошечного процесса около 666, а не 0?

---

## 🧪 Лаба 3. «Диск полон, а файлов нет»

### Что делаем
Сервис пишет лог, «уборщик» удаляет его через `rm`, а сервис продолжает писать в удалённый
файл. `df` показывает 100%, `du` — почти ноль. Находим виновника и освобождаем место
**без рестарта** сервиса.

### Каркас
```bash
sudo mkfs.ext4 -q /dev/vdb                    # второй диск стенда (4 ГБ)
sudo mkdir -p /mnt/data && sudo mount /dev/vdb /mnt/data && sudo chown vagrant: /mnt/data
mkdir -p ~/perf/lab3
```text
```python
# ~/perf/lab3/writer.py — «сервис», который открыл лог один раз и никогда не переоткрывает
import time

with open("/mnt/data/app.log", "a") as f:
    chunk = ("x" * 1023 + "\n") * 1024        # 1 МиБ
    while True:
        try:
            f.write(chunk)
            f.flush()
        except OSError as e:                  # ENOSPC: сервис не падает, а молча «теряет» логи
            print(f"write failed: {e}", flush=True)
            time.sleep(1)
        time.sleep(0.05)                      # ~20 МиБ/с
```text
```bash
python3 ~/perf/lab3/writer.py&gt; ~/perf/lab3/writer.out 2>&1 &
sleep 60; df -h /mnt/data                     # ~30% занято
rm /mnt/data/app.log                          # «уборщик почистил логи»
sleep 120; df -h /mnt/data; du -sh /mnt/data  # df растёт, du — пусто
echo test > /mnt/data/new.txt                 # когда дойдёт до 100%: No space left on device
```text
### Требования
- [ ] Показано расхождение: `df -h` против `du -sh`, и `df -i` исключён (inode есть)
- [ ] Виновник найден двумя способами: `sudo lsof +aL1 /mnt/data` и
      `ls -l /proc/&lt;PID&gt;/fd | grep deleted`; объяснено, что значит `NLINK 0` в выводе lsof
- [ ] Место освобождено без рестарта: `sudo truncate -s 0 /proc/&lt;PID&gt;/fd/&lt;N&gt;`; объяснено,
      почему после этого файл не растёт снова до гигабайт (режим `O_APPEND`)
- [ ] Показано, что восстановить «удалённые» данные можно через `cp /proc/&lt;PID&gt;/fd/&lt;N&gt; …`
      (пока процесс жив)
- [ ] `pidstat -d 1` и `iostat -xz 1` показывают писателя и нагрузку на vdb
- [ ] Постоянный фикс описан: logrotate с `copytruncate` или `create` + сигнал на переоткрытие;
      алерт на «`df` растёт, а `du` нет» или на `lsof +L1`
- [ ] Бонус: «inode кончились» — `sudo mkfs.ext4 -q -N 2000 -F /dev/vdb` (после размонтирования),
      создай 3000 пустых файлов: `No space left on device` при свободных гигабайтах в `df -h`
- [ ] Мини-постмортем

### Критерии приёмки
```bash
df -h /mnt/data; sudo du -sh /mnt/data
sudo lsof -nP +aL1 /mnt/data                  # после фикса: SIZE/OFF маленький
ls -l /proc/$(pgrep -f lab3/writer.py)/fd | grep deleted
echo ok > /mnt/data/new.txt && cat /mnt/data/new.txt
```text
### Вопросы себе
- Что стало бы с местом, если бы писатель открыл файл без `O_APPEND` (режим `"w"`), а ты
  сделал `truncate`? Что покажут `ls -ls` и `du` про такой файл?
- Почему `rm` огромного лога в проде — плохая привычка, а `: > file` — нормальная?
- Как `df` и `du` поведут себя, если файлы спрятаны под точкой монтирования?
- Что такое 5% reserved blocks в ext4 и почему root иногда может писать, когда `df` показывает 100%?

---

## 🧪 Лаба 4. conntrack table full / исчерпание эфемерных портов

### Что делаем
Две частые «сетевые» аварии, в которых сеть ни при чём. **A:** таблица conntrack маленькая,
короткие соединения её заполняют, ядро молча дропает новые SYN. **B:** клиент без пула
соединений исчерпывает эфемерные порты. Достаточно сделать одну часть целиком, лучше — обе.

### Каркас
```python
# ~/perf/lab4/sink.py — TCP-сервер: принимает соединение и держит до EOF
import socket
import threading

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 9000))
srv.listen(4096)

def handle(c):
    while c.recv(4096):
        pass
    c.close()

while True:
    conn, _ = srv.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
```text
```python
# ~/perf/lab4/churn.py — клиент без пула: новое соединение на каждый «запрос»
import socket
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "close"     # close | hold
held, ok, t0 = [], 0, time.time()
while True:
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect(("127.0.0.1", 9000))
    except OSError as e:
        print(f"после {ok} соединений за {time.time() - t0:.1f} с: {e}")
        break
    ok += 1
    if mode == "hold":
        held.append(s)
    else:
        s.close()                   # клиент закрывает первым → TIME_WAIT на стороне клиента
```text
```bash
mkdir -p ~/perf/lab4 && cd ~/perf/lab4 && python3 sink.py &

# Часть A — conntrack
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT   # conntrack точно активен
sysctl net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_tcp_timeout_time_wait
ORIG=$(sysctl -n net.netfilter.nf_conntrack_max)                               # запомнить, чтобы вернуть
sudo sysctl -w net.netfilter.nf_conntrack_max=512                              # ⚠️ только на VM
python3 churn.py close                   # быстро упрётся: timed out
sudo conntrack -C ; sudo conntrack -S | head -2
sudo dmesg -T | grep -i 'table full'

# Часть B — эфемерные порты
sudo sysctl -w net.netfilter.nf_conntrack_max=$ORIG                            # вернуть A
sudo sysctl -w net.ipv4.ip_local_port_range="50000 50099"                      # 100 портов
python3 churn.py hold                    # Cannot assign requested address после ~100
sudo sysctl -w net.ipv4.tcp_tw_reuse=0   # по умолчанию 2: reuse только для loopback
python3 churn.py close                   # то же, но из-за TIME_WAIT
ss -tan state time-wait | wc -l ; ss -s
```text
### Требования
- [ ] A: доказательство цепочкой — `conntrack -C` = `nf_conntrack_max`, в `conntrack -S`
      растёт `drop` (и/или `insert_failed`), в `dmesg` — `nf_conntrack: table full, dropping packet`
- [ ] A: объяснено, почему клиент видит таймаут (SYN дропается молча), а не `Connection refused`,
      и почему записи в TIME_WAIT держат таблицу (таймаут `nf_conntrack_tcp_timeout_time_wait`)
- [ ] A: фикс и замер: `nf_conntrack_max` больше (и соответствующий `hashsize`), меньший
      таймаут TIME_WAIT или `NOTRACK` для этого трафика в таблице `raw`; объяснено, какой
      вариант выбрал бы в проде и почему
- [ ] B: `EADDRNOTAVAIL` (`Cannot assign requested address`) воспроизведён в режимах `hold`
      и `close`; посчитано, сколько соединений в секунду выдерживает диапазон 28 232 порта
      при TIME_WAIT 60 секунд к одному адресу:порту назначения
- [ ] B: показано, что `tcp_tw_reuse=1` (или 2 для loopback) снимает проблему режима `close`,
      но не `hold`; объяснено, почему `tcp_tw_recycle` не вариант (его нет с ядра 4.12)
- [ ] B: правильный фикс сформулирован: пул соединений / keep-alive на клиенте, несколько
      IP назначения или источника, расширение диапазона — и в каком порядке
- [ ] Всё возвращено: `ip_local_port_range`, `tcp_tw_reuse`, правило iptables удалено
- [ ] Мини-постмортем по одной из частей

### Критерии приёмки
```bash
sudo conntrack -S | grep -oE '(insert_failed|drop|early_drop)=[0-9]+' | sort | uniq -c   # drop > 0
sudo dmesg -T | grep -c 'table full'                  # > 0
python3 ~/perf/lab4/churn.py hold 2>&1 | tail -1       # «после ~100 соединений … Errno 99»
sysctl net.ipv4.ip_local_port_range net.ipv4.tcp_tw_reuse   # вернулись к 32768 60999 и 2
sudo iptables -S INPUT | grep -c conntrack             # 0 после уборки
```text
### Вопросы себе
- Почему conntrack вообще работает на машине без «файрвола»? Кто его включил на стенде?
- Где в Kubernetes conntrack становится проблемой (kube-proxy, NodePort, DNS по UDP)?
- Сервер с 4 IP назначения за балансировщиком: сколько исходящих соединений в секунду
  теперь выдержит клиент без пула?
- Почему `hold`-режим ломается одинаково при любом `tcp_tw_reuse`?

---

## 🧪 Лаба 5. ⭐ CPU throttling в контейнере при «30% CPU»

### Что делаем
Сервис на каждый запрос параллельно считает на 4 потоках. В контейнере с лимитом `--cpus=0.5`
`docker stats` показывает ~20% CPU, а запросы тормозят в 3–4 раза. Доказываем throttling через
`cpu.stat`, чиним, показываем эффект. Бонус — то же в kind.

### Каркас
```python
# ~/perf/lab5/burst.py — запрос = 4 потока CPU-работы (pbkdf2 отпускает GIL → настоящий параллелизм)
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ITER = 60_000          # подбери, чтобы один вызов занимал ~50 мс (см. ниже)

def work():
    hashlib.pbkdf2_hmac("sha256", b"pw", b"salt", ITER)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, *args):
        pass

ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
```text
```bash
mkdir -p ~/perf/lab5 && cd ~/perf/lab5
python3 -c "import hashlib,time; t=time.time(); hashlib.pbkdf2_hmac('sha256',b'pw',b'salt',60000); print(time.time()-t)"

docker run -d --name burst-free       -p 8081:8080 -v ~/perf/lab5:/app:ro python:3.12-slim python /app/burst.py
docker run -d --name burst-lim --cpus=0.5 -p 8082:8080 -v ~/perf/lab5:/app:ro python:3.12-slim python /app/burst.py

lat() {   # 30 запросов раз в секунду → p50/p90/max
  for i in $(seq 30); do curl -s -o /dev/null -w '%{time_total}\n' "localhost:$1/"; sleep 1; done \
    | sort -n | awk '{a[NR]=$1} END {print "p50=" a[int(NR*0.5)], "p90=" a[int(NR*0.9)], "max=" a[NR]}'
}
docker exec burst-lim cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/cpu.stat    # до
lat 8081 ; lat 8082
docker exec burst-lim cat /sys/fs/cgroup/cpu.stat                           # после: nr_throttled вырос
docker stats --no-stream burst-free burst-lim                               # ~20% CPU — «всё хорошо»
```text
### Требования
- [ ] До фикса: `cpu.max` = `50000 100000`; p50/p90 для `burst-free` и `burst-lim` записаны
- [ ] Посчитано: сколько CPU-времени съедает запрос, сколько 100-мс периодов ему нужно при квоте
      50 мс и почему latency ≈ (периодов − 1) × 100 мс + хвост
- [ ] Доказательство: прирост `nr_throttled` и `throttled_usec` за 30 запросов;
      `nr_throttled / nr_periods` посчитан
- [ ] Объяснено, почему `docker stats` (~20%) и средняя загрузка не видят проблему
- [ ] Фикс 1: `docker update --cpus=2 burst-lim` → замер; фикс 2 (альтернатива): лимит тот же,
      параллелизм 1 поток — что стало с latency и почему
- [ ] Бонус (kind): Deployment с `limits.cpu: 500m`; `kubectl exec … -- cat /sys/fs/cgroup/cpu.stat`;
      PromQL для алерта `rate(container_cpu_cfs_throttled_periods_total[5m]) /
      rate(container_cpu_cfs_periods_total[5m]) > 0.25`
- [ ] Мини-постмортем: когда CPU-лимит в k8s нужен, а когда лучше оставить только requests

### Критерии приёмки
```bash
docker exec burst-lim sh -c 'cat /sys/fs/cgroup/cpu.max; grep -E "nr_periods|nr_throttled|throttled_usec" /sys/fs/cgroup/cpu.stat'
docker inspect burst-lim --format '&#123;&#123;.HostConfig.NanoCpus&#125;&#125;'     # после фикса 2000000000
grep -E 'p50|p90' ~/perf/lab5/postmortem.md                      # цифры до/после
docker rm -f burst-free burst-lim                                # уборка
```text
### Вопросы себе
- Почему с 4 потоками на 2 vCPU запрос без лимита занимает ~100 мс, а не ~50?
- Что изменится, если период CFS будет 10 мс вместо 100 мс?
- Как ведут себя Go (GOMAXPROCS) и JVM в контейнере с лимитом 500m на 64-ядерной ноде?
- Почему throttling бьёт по p99, а не по среднему?

---

## 🧪 Лаба 6. D-state: зависший процесс и strace медленного приложения

### Что делаем
Имитируем «умирающий» диск через device-mapper `delay`: сначала он просто медленный —
приложение-«база» делает fsync и тормозит, ищем причину strace'ом. Потом диск «зависает»
(`dmsetup suspend`) — процесс уходит в D-state, `kill -9` не помогает; находим, где он висит.

### Каркас
```bash
# если после лабы 3 vdb смонтирован: sudo umount /mnt/data
sudo modprobe dm_delay
SZ=$(sudo blockdev --getsz /dev/vdb)
echo "0 $SZ delay /dev/vdb 0 0" | sudo dmsetup create slowdisk      # пока без задержки
sudo mkfs.ext4 -q /dev/mapper/slowdisk
sudo mkdir -p /mnt/slow && sudo mount /dev/mapper/slowdisk /mnt/slow && sudo chown vagrant: /mnt/slow
mkdir -p ~/perf/lab6
```text
```python
# ~/perf/lab6/wal.py — «база»: пишет запись, делает fsync, печатает время коммита
import os
import time

fd = os.open("/mnt/slow/wal.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
while True:
    t = time.perf_counter()
    os.write(fd, b"x" * 4096)
    os.fsync(fd)
    print(f"commit {1000 * (time.perf_counter() - t):.1f} ms", flush=True)
    time.sleep(0.2)
```text
```bash
python3 ~/perf/lab6/wal.py > ~/perf/lab6/wal.log &
W=$!; sleep 5; tail -3 ~/perf/lab6/wal.log                          # commit ~1–3 ms

# Часть A — диск стал медленным: +200 мс на каждый запрос
sudo dmsetup suspend slowdisk
echo "0 $SZ delay /dev/vdb 0 200" | sudo dmsetup reload slowdisk
sudo dmsetup resume slowdisk
tail -3 ~/perf/lab6/wal.log                                         # commit сотни мс
sudo strace -f -tt -T -e trace=write,fsync -p $W                    # на чём время? (Ctrl+C)
sudo timeout 10 strace -c -w -p $W                                  # сводка по wall-clock
iostat -xz 1 3                                                      # dm-0: w_await ~200+ мс
sudo biolatency-bpfcc -D 10 1                                       # гистограмма по устройствам

# Часть B — диск «завис»: --nolockfs — без заморозки ФС, I/O просто копится в очереди dm
sudo dmsetup suspend --nolockfs slowdisk
sleep 5; grep State /proc/$W/status                                 # D (disk sleep)
sudo cat /proc/$W/stack ; cat /proc/$W/wchan; echo
kill -9 $W; sleep 2; grep State /proc/$W/status                     # всё ещё D
sleep 120; sudo dmesg -T | grep -A12 'blocked for more than'        # hung task
echo w | sudo tee /proc/sysrq-trigger >/dev/null                    # ⚠️ дамп заблокированных задач
sudo dmesg -T | grep -A20 'Show Blocked State' | head -40
sudo dmsetup resume slowdisk                                        # процесс «оживает» и умирает от KILL

# уборка
sudo umount /mnt/slow && sudo dmsetup remove slowdisk
```text
### Требования
- [ ] A: в strace видно, что время уходит в `fsync` (`&lt;0.4…&gt;`), а `write` быстрый; объяснено,
      почему `strace -c` без `-w` показал бы fsync «дешёвым» (по умолчанию — системное время,
      а не время ожидания)
- [ ] A: `iostat` и `biolatency` подтверждают: latency устройства ~200+ мс при почти нулевой
      нагрузке — это «медленный диск», а не «перегруженный»
- [ ] B: состояние D доказано тремя способами: `/proc/PID/status`, `ps -o stat,wchan`,
      `vmstat 1` (колонка `b`); стек из `/proc/PID/stack` прочитан снизу вверх и подписан
      (`fsync` → ext4/jbd2 → ожидание writeback/блочного слоя)
- [ ] B: показано, что `kill -9` не действует, пока идёт ожидание, и объяснено почему
- [ ] B: найдены сообщение hung task и вывод sysrq-w; объяснено, почему в списке могут быть
      и служебные потоки (`jbd2/dm-0-8`, `kworker`)
- [ ] B: LA вырос при простаивающем CPU — связано с темой 01
- [ ] Бонус (NFS): `/srv/nfs` экспортирован на `127.0.0.1`, смонтирован `-o hard`, сервер
      остановлен (`sudo systemctl stop nfs-server`) → `touch /mnt/nfs/x` висит в D, но
      `kill -9` срабатывает; объяснено, чем TASK_KILLABLE отличается от «настоящего» D
- [ ] Мини-постмортем: как по метрикам отличить «диск медленный» от «диск перегружен» и от «диск завис»

### Критерии приёмки
```bash
grep -E 'fsync' ~/perf/lab6/postmortem.md                  # фрагмент strace с &lt;время&gt;
sudo dmesg -T | grep -c 'blocked for more than'            # ≥ 1
sudo dmesg -T | grep -c 'Show Blocked State'               # ≥ 1
sudo dmsetup ls                                            # после уборки: No devices found
```text
### Вопросы себе
- Чем отличается ожидание в `fsync` от ожидания в `epoll_wait` для strace и для LA?
- Почему `dmsetup suspend` на смонтированной ФС сначала пытается сделать sync?
- Что бы ты сделал в проде с процессом в D на умершем NFS: ребут, `umount -f`, `umount -l`?
- Как этот сценарий выглядит в Kubernetes (PV на зависшем хранилище) и что увидит kubelet?

---

## 🏁 Что должно остаться после блока

```text
~/perf/
├── 60s.sh                        # «60 секунд» в файл — кладётся в runbook
├── lab1/  app.py  cpu.svg  py.svg  bpf.svg  postmortem.md
├── lab2/  leaky.py  rss.log  oom-report.txt  postmortem.md
├── lab3/  writer.py  postmortem.md
├── lab4/  sink.py  churn.py  postmortem.md
├── lab5/  burst.py  postmortem.md
└── lab6/  wal.py  wal.log  postmortem.md
```text
Это превращает ответ «знаю perf и cgroups» в «вот flame graph, где видно горячую функцию;
вот OOM-отчёт, разобранный построчно; вот `cpu.stat`, где throttling съедал p90».

> 🔥 Хочешь инциденты, где дан только симптом, без подсказок? —
> `99-incidents`: особенно
> «Сервер тормозит, вентилятор воет» и «Диск забит, но я не нахожу чем».

➡️ Дальше: [09_interview.md](/softskills/09-interview)
