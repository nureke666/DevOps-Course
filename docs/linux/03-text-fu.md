---
title: "03. Text-Fu"
description: "Потоки stdin/stdout/stderr, пайпы, grep/sort/uniq/awk-основы — главный рабочий навык линуксоида"
---

# 03. Text-Fu: потоки, пайпы и обработка текста

> Источник: `03_text_fu.txt` (Grasshopper, 16 уроков)
> **После темы ты умеешь:** собирать конвейеры из утилит, анализировать логи одной строкой,
> перенаправлять вывод куда угодно. Это **главный рабочий навык линуксоида**.

---

## 🗺️ Схема: три потока каждого процесса

У любого процесса при старте открыты три файловых дескриптора (fd):

```text:no-line-numbers
                        ┌─────────────────────┐
   fd 0  stdin   ─────▶ │                     │
   (клавиатура/файл)    │      ПРОЦЕСС        │
                        │    (например grep)  │ ─────▶ fd 1  stdout (экран/файл/пайп)
                        │                     │ ─────▶ fd 2  stderr (экран, ВСЕГДА отдельно)
                        └─────────────────────┘
                                   │
                                   ▼
                         exit code → $? (0 = ок)
```

| fd | Имя | По умолчанию куда | Зачем |
|----|-----|-------------------|-------|
| 0 | stdin | клавиатура | вход данных |
| 1 | stdout | экран | **полезный результат** |
| 2 | stderr | экран | **ошибки и диагностика** |

🔑 **Ключевая идея:** stdout и stderr — **разные каналы**, хотя оба валятся на экран.
Именно поэтому `grep` не поймает ошибку, а `2>/dev/null` прячет только ошибки.

---

## 1-3. stdout, stdin, stderr — перенаправление

```bash
# STDOUT
command > file          # записать (ПЕРЕЗАПИСАТЬ файл!)
command >> file         # дописать в конец
command 1> file         # то же, что >  (1 можно не писать)

# STDERR
command 2> errors.log   # только ошибки в файл
command 2>> errors.log  # дописать ошибки
command 2>/dev/null     # выбросить ошибки

# ОБА ПОТОКА
command > out.log 2>&1      # stdout в файл, stderr туда же  ← классика
command &> out.log          # то же короче (bash-only)
command &>> out.log         # дописать оба
command > out.log 2> err.log # раздельно

# STDIN
command < file          # читать из файла вместо клавиатуры
wc -l < /etc/passwd     # (обрати внимание: без имени файла в выводе!)

# ЧЁРНАЯ ДЫРА
command > /dev/null 2>&1    # молча выполнить, ничего не показывать
```

⚠️ **Порядок важен!**
```bash
command > file 2>&1     # ✅ stdout→file, потом stderr→туда же, где stdout (то есть в file)
command 2>&1 > file     # ❌ stderr→на экран (где сейчас stdout), потом stdout→file
```
Читай справа налево как «присвоение»: `2>&1` значит «направь fd2 туда, куда СЕЙЧАС указывает fd1».

### Практика

```bash
ls /etc /nope > out.txt 2> err.txt
cat out.txt      # содержимое /etc
cat err.txt      # ls: cannot access '/nope': No such file or directory

# Типовой запуск задачи в фоне с логом
./backup.sh >> /var/log/backup.log 2>&1 &

# Проверка "есть ли команда" без мусора на экране
command -v docker >/dev/null 2>&1 && echo "docker есть"
```

💡 `/dev/null` — «чёрная дыра»: всё записанное исчезает, чтение возвращает EOF.
`/dev/zero` — бесконечные нули (для создания файлов), `/dev/urandom` — случайные байты.

---

## 4. pipe `|` и tee — конвейеры

**Пайп** соединяет **stdout** одной команды со **stdin** следующей:

```text:no-line-numbers
cat access.log │ grep 500 │ awk '{print $1}' │ sort │ uniq -c │ sort -rn │ head
     ▲              ▲           ▲               ▲       ▲         ▲         ▲
   читаем      фильтруем   берём IP        сортируем считаем  по убыв.  топ-10
```

```bash
ps aux | grep nginx
cat /var/log/syslog | grep -i error | tail -20
ls -l /etc | wc -l
```

⚠️ Пайп передаёт **только stdout**. Чтобы прогнать через пайп и ошибки:
```bash
command 2>&1 | grep -i error
command |& grep -i error     # bash-сокращение
```

### tee — «тройник»: и на экран, и в файл

```bash
command | tee out.log                 # показать И записать (перезапись)
command | tee -a out.log              # дописать
command | tee out.log | grep error    # записать всё, дальше по конвейеру отфильтрованное
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf   # ← ГЛАВНЫЙ КЕЙС
```

🔑 **Зачем `sudo tee`:** конструкция `sudo echo "x" >> /etc/file` **не работает** — перенаправление
делает shell от **твоего** пользователя, а не от root. `tee` же запускается под sudo и пишет сам.

### xargs — превратить поток в аргументы

```bash
find . -name "*.log" | xargs rm            # передать имена как аргументы rm
find . -name "*.log" -print0 | xargs -0 rm # безопасно (имена с пробелами)
cat hosts.txt | xargs -I{} ssh {} uptime   # выполнить для каждой строки
cat urls.txt | xargs -P4 -n1 curl -sO      # 4 параллельных загрузки
```
Разница: пайп даёт данные в **stdin**, а многие команды (`rm`, `mkdir`, `kill`) хотят **аргументы** —
вот `xargs` и переводит одно в другое.

---

## 5. env — переменные окружения

```bash
env                    # все переменные окружения
printenv PATH          # одну
echo $HOME
set                    # ВСЕ переменные, включая локальные shell-переменные и функции

MY_VAR="hello"         # локальная переменная (видна только этому shell)
export MY_VAR          # ЭКСПОРТ → видна дочерним процессам
export API_KEY="123"   # сразу
unset MY_VAR           # удалить

env FOO=bar ./script.sh  # запустить команду с доп. переменной, не меняя своё окружение
```

Ключевые переменные:

| Переменная | Смысл |
|-----------|-------|
| `$PATH` | Где искать исполняемые файлы |
| `$HOME` | Домашний каталог |
| `$USER` | Имя пользователя |
| `$PWD` / `$OLDPWD` | Текущий / предыдущий каталог |
| `$SHELL` | Оболочка пользователя |
| `$LANG`, `$LC_ALL` | Локаль (влияет на сортировку и формат дат!) |
| `$TERM` | Тип терминала |
| `$EDITOR` | Редактор по умолчанию (для `crontab -e`, `visudo`) |
| `$?` | Код возврата последней команды |
| `$$` | PID текущего shell |
| `$0`, `$1`, `$@`, `$#` | Имя скрипта, аргументы, все аргументы, их количество |

Наследование — то, что путает новичков:

```text:no-line-numbers
bash (родитель)  MY_VAR=hello  (не экспортирована)
   └── ./script.sh (дочерний процесс) → $MY_VAR ПУСТА

bash  export MY_VAR=hello
   └── ./script.sh → $MY_VAR=hello  ✅
```
Дочерний процесс **никогда** не может изменить окружение родителя. Поэтому `cd` внутри скрипта
не меняет каталог твоего шелла — нужно `source script.sh` (выполнить в текущем шелле).

💼 В DevOps это фундамент: `docker run -e`, `env` в Kubernetes, секреты в CI, `.env`-файлы —
всё это ровно та же механика.

---

## 6. cut — вырезать колонки

```bash
cut -d':' -f1 /etc/passwd         # разделитель ':' , взять 1-е поле → список юзеров
cut -d':' -f1,3 /etc/passwd       # поля 1 и 3
cut -d':' -f1-3 /etc/passwd       # с 1 по 3
cut -d' ' -f1 access.log          # по пробелу
cut -c1-10 file.txt               # по СИМВОЛАМ, с 1 по 10
cut -d':' -f1 --output-delimiter=' | ' /etc/passwd
```

⚠️ `cut` не умеет «несколько пробелов подряд как один разделитель». Для логов с выровненными
колонками (`ps aux`, `df`) используй `awk '{print $1}'` — он сам схлопывает пробелы.

---

## 7. paste — склеить файлы построчно

```bash
paste f1.txt f2.txt              # строки рядом через TAB
paste -d',' f1.txt f2.txt        # через запятую
paste -s f1.txt                  # все строки файла в ОДНУ строку
seq 1 5 | paste -sd',' -         # 1,2,3,4,5  ← полезный трюк
```

---

## 8-9. head и tail — начало и конец

```bash
head file.txt              # первые 10 строк
head -n 20 file.txt        # первые 20
head -n -5 file.txt        # всё, КРОМЕ последних 5
head -c 100 file.txt       # первые 100 байт

tail file.txt              # последние 10 строк
tail -n 50 file.txt        # последние 50
tail -n +10 file.txt       # начиная с 10-й строки до конца
tail -f /var/log/syslog    # СЛЕДИТЬ за файлом в реальном времени ← используешь каждый день
tail -F /var/log/app.log   # то же, но переживает ротацию лога (переоткрывает файл)
tail -f app.log | grep -i error   # live-фильтр
```

Комбо «взять строки с 10 по 20»:
```bash
head -n 20 file.txt | tail -n 11
sed -n '10,20p' file.txt          # то же одной командой
```

💡 `tail -F` вместо `-f` — правильный выбор на сервере: после logrotate `-f` продолжит читать
старый (удалённый) файл и ты не увидишь новых строк.

---

## 10. expand / unexpand — табы ↔ пробелы

```bash
expand file.txt            # табы → пробелы
expand -t4 file.txt        # таб = 4 пробела
unexpand -a file.txt       # пробелы → табы
cat -A file.txt            # посмотреть, где реально табы (^I)
```
Кажется мелочью, пока не встретишь `Makefile` (требует **табы**) или YAML (**запрещены табы**).
Ошибка `missing separator` в Makefile — это ровно про это.

---

## 11. join / split

```bash
# join — как SQL JOIN по общему полю (файлы должны быть ОТСОРТИРОВАНЫ по этому полю!)
join file1.txt file2.txt
join -1 2 -2 1 f1 f2          # по 2-му полю первого и 1-му второго
join -t':' f1 f2              # другой разделитель

# split — разрезать большой файл
split -l 1000 big.log part_       # по 1000 строк → part_aa, part_ab…
split -b 10M big.tar part_        # по 10 МБ
split -n 5 big.log part_          # на 5 равных частей
cat part_* > restored.log         # собрать обратно
```
`split` реально нужен, когда надо переслать дамп БД по кускам или обработать гигантский лог частями.

---

## 12. sort — сортировка

```bash
sort file.txt              # по алфавиту
sort -r file.txt           # обратный порядок
sort -n file.txt           # ЧИСЛОВАЯ сортировка (иначе 10 < 9!)
sort -h file.txt           # человекочитаемые размеры (1K, 5M, 2G)
sort -u file.txt           # уникальные (sort + uniq)
sort -k2 file.txt          # по 2-му полю
sort -t':' -k3 -n /etc/passwd   # разделитель ':', по 3-му полю (UID), численно
sort -rn -k2 file.txt      # по 2-му полю, численно, по убыванию
sort -f file.txt           # без учёта регистра
sort -R file.txt           # случайный порядок
sort -c file.txt           # проверить, отсортирован ли
```

⚠️ **Классическая ошибка:** `sort` без `-n` сортирует как текст: `1, 10, 2, 20, 3`.
⚠️ **Локаль влияет на сортировку.** В скриптах фиксируй: `LC_ALL=C sort` — даст предсказуемый
байтовый порядок и работает быстрее.

---

## 13. tr — замена/удаление символов

```bash
tr 'a-z' 'A-Z' < file.txt         # в верхний регистр
tr -d ' ' < file.txt              # удалить пробелы
tr -d '\r' < win.txt > unix.txt   # убрать CR (лечение CRLF)
tr -s ' ' < file.txt              # сжать повторяющиеся пробелы в один ← очень полезно
tr ' ' '\n' < file.txt            # пробелы → переводы строк (разбить на слова)
tr -c 'a-zA-Z0-9\n' '_' < f.txt   # заменить всё, КРОМЕ перечисленного

# Генерация пароля
tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 20; echo
```
`tr` работает **только с потоком** (stdin), файл как аргумент не принимает — только через `<` или пайп.

---

## 14. uniq — уникальные строки

🔴 **`uniq` убирает только СОСЕДНИЕ дубликаты!** Поэтому почти всегда идёт после `sort`.

```bash
sort file.txt | uniq          # уникальные строки
sort file.txt | uniq -c       # с подсчётом количества   ← ГЛАВНЫЙ РЕЖИМ
sort file.txt | uniq -d       # только дубликаты
sort file.txt | uniq -u       # только встречающиеся один раз
sort file.txt | uniq -i       # без учёта регистра
```

**Золотая формула анализа логов** (запомни как стихотворение):
```bash
... | sort | uniq -c | sort -rn | head
     └───────┬──────┘  └────┬───┘ └─┬─┘
        посчитать      по убыванию  топ
```

---

## 15. wc и nl — счёт и нумерация

```bash
wc file.txt        # строки слова байты имя
wc -l file.txt     # СТРОКИ ← самое частое
wc -w file.txt     # слова
wc -c file.txt     # байты
wc -m file.txt     # символы (важно для UTF-8)
ls | wc -l         # сколько файлов
grep -c error log  # ⚠️ лучше, чем grep error log | wc -l

nl file.txt        # пронумеровать непустые строки
nl -ba file.txt    # пронумеровать все строки
```

---

## 16. grep — поиск (королева темы)

```bash
grep "error" app.log              # строки со словом error
grep -i "error" app.log           # без учёта регистра
grep -v "debug" app.log           # ИНВЕРСИЯ: строки БЕЗ debug
grep -c "error" app.log           # количество совпавших строк
grep -n "error" app.log           # с номерами строк
grep -l "error" *.log             # только ИМЕНА файлов, где нашлось
grep -L "error" *.log             # имена файлов, где НЕ нашлось
grep -w "cat" file                # только целое слово (не "category")
grep -x "exact line" file         # строка целиком
grep -r "TODO" /opt/app           # рекурсивно по каталогу
grep -rn --include="*.py" "def " .   # только в py-файлах
grep -o "[0-9]\+" file            # вывести ТОЛЬКО совпавшую часть
grep -E "error|warn|fatal" log    # расширенный regex (ИЛИ)
grep -F "1.2.3.4" log             # фиксированная строка, без regex — быстрее и безопаснее
grep -q "error" log && echo found # тихий режим, только exit code ← для скриптов

# КОНТЕКСТ — критично при разборе инцидентов
grep -A5 "error" app.log          # 5 строк ПОСЛЕ (After)
grep -B5 "error" app.log          # 5 строк ДО (Before)
grep -C5 "error" app.log          # 5 строк вокруг (Context)
```

Базовые regex (подробнее в теме [04_advanced_text_fu.md](/linux/04-advanced-text-fu)):
```bash
grep "^ERROR" log          # строка НАЧИНАЕТСЯ с ERROR
grep "failed$" log         # ЗАКАНЧИВАЕТСЯ на failed
grep "^$" log              # пустые строки
grep -v "^#" /etc/ssh/sshd_config | grep -v "^$"   # конфиг без комментариев ← кейс на каждый день
grep -E "[0-9]{1,3}(\.[0-9]{1,3}){3}" log          # IP-адреса
```

---

## 🔥 Боевые однострочники (учи наизусть)

```bash
# Топ-10 IP по числу запросов в nginx
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10

# Распределение HTTP-кодов
awk '{print $9}' access.log | sort | uniq -c | sort -rn

# Все 5xx за сегодня
grep "$(date +%d/%b/%Y)" access.log | awk '$9 ~ /^5/'

# Топ-10 самых медленных запросов (если время в последнем поле)
awk '{print $NF, $7}' access.log | sort -rn | head

# Кто долбится в SSH (неудачные попытки)
grep "Failed password" /var/log/auth.log | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn

# Топ процессов по памяти
ps aux --sort=-%mem | head -11

# Конфиг без комментариев и пустых строк
grep -vE '^\s*(#|$)' /etc/nginx/nginx.conf

# Сколько уникальных пользователей в системе с shell'ом (не служебных)
grep -vE '(nologin|false)$' /etc/passwd | cut -d: -f1

# Найти дубликаты строк в файле
sort file.txt | uniq -d

# Live-мониторинг ошибок
tail -F /var/log/app.log | grep --line-buffered -i error
```
💡 `--line-buffered` у grep обязателен в live-конвейерах, иначе вывод буферизуется и «залипает».

---

## 🗺️ Схема: как собирать конвейер

```text:no-line-numbers
  ИСТОЧНИК     →    ФИЛЬТР      →   ПРЕОБРАЗОВАНИЕ  →   АГРЕГАЦИЯ   →   ВЫВОД
 cat / tail /      grep / grep -v     cut / awk / tr      sort / uniq -c   head / tail
 journalctl /      grep -E            sed                 wc -l            tee file
 find / ps aux                                            sort -rn         > report.txt
```

Отлаживай конвейер **по шагам**: добавил одну команду → посмотрел вывод → добавил следующую.
Не пиши сразу семь пайпов.

---

## 💼 Как это в DevOps

- Разбор инцидента = `journalctl -u app | grep -i error -A5 | less`.
- Быстрая аналитика без Grafana: топ IP, топ ошибок, распределение кодов — теми же пайпами.
- Скрипты health-check: `curl -s ... | grep -q '"status":"ok"' || alert`.
- `2>&1`, `tee`, `/dev/null` — в каждом cron-джобе и systemd-юните.
- `sudo tee` — единственный корректный способ дописать в системный файл из пайпа.

---

## 🧪 Мини-лаба

```bash
vagrant ssh
mkdir -p ~/lab03 && cd ~/lab03

# Генерируем правдоподобный access.log
for i in $(seq 1 200); do
  ip="10.0.0.$((RANDOM % 8 + 1))"
  code=$(shuf -e 200 200 200 301 404 500 502 -n1)
  path=$(shuf -e /api/users /api/orders /health /login -n1)
  echo "$ip - - [13/Sep/2026:10:$((RANDOM%60)):00 +0000] \"GET $path HTTP/1.1\" $code $((RANDOM%5000))"
done > access.log

wc -l access.log
head -3 access.log

# 1. Топ IP
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -5

# 2. Распределение кодов
awk '{print $9}' access.log | sort | uniq -c | sort -rn

# 3. Только ошибки 5xx, с сохранением в файл и выводом на экран
awk '$9 ~ /^5/' access.log | tee errors.log | wc -l

# 4. Самые популярные URL
awk '{print $7}' access.log | sort | uniq -c | sort -rn

# 5. Потоки: посмотри разницу
ls /etc /nope > out.txt 2> err.txt; cat err.txt
ls /etc /nope 2>&1 | grep -c "cannot"

# 6. Переменные и наследование
MYVAR=local; bash -c 'echo "child sees: [$MYVAR]"'
export MYVAR; bash -c 'echo "child sees: [$MYVAR]"'
```

---

## 📌 Шпаргалка

| Инструмент | Одной строкой |
|-----------|---------------|
| `>` `>>` | перезаписать / дописать stdout |
| `2>` `&>` | ошибки / оба потока |
| `2>&1` | «ошибки туда же, куда вывод» (пишется **после** `>`) |
| `<` | подать файл на stdin |
| `\|` | stdout → stdin следующей команды |
| `tee` | и на экран, и в файл (`sudo tee` для системных файлов) |
| `xargs` | поток → аргументы |
| `env` / `export` | окружение, экспорт в дочерние процессы |
| `cut -d -f` | колонки по разделителю |
| `head` / `tail -F` | начало / конец + слежение |
| `sort -n -k -u -h` | сортировка |
| `uniq -c -d -u` | уникальные (**только после sort!**) |
| `tr -d -s -c` | замена/удаление/сжатие символов |
| `wc -l` | счёт строк |
| `grep -i -v -r -n -c -E -A -B -C -o -q` | поиск |

---

## 🧠 Что запомнить

1. Три потока: **0 stdin, 1 stdout, 2 stderr**. Пайп несёт только stdout.
2. `> file 2>&1` — порядок имеет значение (справа налево).
3. `sudo echo x >> /etc/f` **не работает** → `echo x | sudo tee -a /etc/f`.
4. `uniq` видит только соседние дубликаты → **всегда `sort | uniq`**.
5. `sort -n` для чисел, `sort -h` для размеров, `LC_ALL=C sort` в скриптах.
6. Формула логов: `… | sort | uniq -c | sort -rn | head`.
7. `grep -A/-B/-C` даёт контекст — без него разбор ошибок бессмысленен.
8. `tail -F` (большая F) переживает ротацию логов.
9. `export` нужен, чтобы переменную увидел дочерний процесс; обратно ничего не возвращается.

---

## Задачи

> `vagrant snapshot save before_03 && vagrant ssh`
> Эта тема — самая «рабочая». Задачи решай в терминале, а не в голове.

### 🔧 Подготовка стенда (выполни первым делом)

```bash
mkdir -p ~/lab03 && cd ~/lab03
for i in $(seq 1 500); do
  ip="10.0.0.$((RANDOM % 10 + 1))"
  code=$(shuf -e 200 200 200 200 301 404 404 500 502 503 -n1)
  path=$(shuf -e /api/users /api/orders /api/pay /health /login /static/app.js -n1)
  ms=$((RANDOM % 3000))
  echo "$ip - - [13/Sep/2026:1$((RANDOM%10)):$((RANDOM%60)):00 +0000] \"GET $path HTTP/1.1\" $code $ms"
done > access.log

cat > app.log <<'EOF'
2026-09-13 10:00:01 INFO  starting service version=1.4.2
2026-09-13 10:00:02 INFO  connected to db host=db01 port=5432
2026-09-13 10:01:15 WARN  slow query duration=2100ms table=orders
2026-09-13 10:02:00 ERROR failed to connect redis host=cache01 timeout=5s
2026-09-13 10:02:01 ERROR retry 1/3 redis
2026-09-13 10:02:06 ERROR retry 2/3 redis
2026-09-13 10:02:11 ERROR retry 3/3 redis
2026-09-13 10:02:12 FATAL cache unavailable, degraded mode
2026-09-13 10:05:00 INFO  request path=/api/users status=200
2026-09-13 10:05:01 WARN  slow query duration=3400ms table=users
2026-09-13 10:06:00 INFO  request path=/api/pay status=500
EOF

wc -l access.log app.log
```

---

### Блок A. Теория

**A1.** Назови три стандартных потока, их номера и назначение.

<details><summary>Ответ</summary>

`0` stdin — вход, `1` stdout — полезный вывод, `2` stderr — ошибки и диагностика.
Разделение позволяет отдельно обрабатывать результат и ошибки.

</details>

**A2.** В чём разница между `команда > f 2>&1` и `команда 2>&1 > f`? Объясни механику.

<details><summary>Ответ</summary>

`> f 2>&1`: сначала fd1 переводится в файл, затем fd2 копирует **текущее** назначение fd1 →
оба в файл. `2>&1 > f`: сначала fd2 копирует назначение fd1 (терминал), потом fd1 уходит в файл →
stdout в файле, stderr на экране.

</details>

**A3.** Почему `sudo echo "text" >> /etc/sysctl.conf` не работает, а `echo "text" | sudo tee -a /etc/sysctl.conf` работает?

<details><summary>Ответ</summary>

Перенаправление `>>` выполняет **shell**, который запущен от твоего пользователя; `sudo`
влияет только на `echo`. Файл открывается до повышения прав → Permission denied.
`tee` же сам является процессом, запущенным под sudo, и открывает файл уже с правами root.

</details>

**A4.** Пайп передаёт stdout. Как прогнать через `grep` ещё и stderr?

<details><summary>Ответ</summary>

`command 2>&1 | grep ...` или bash-сокращение `command |& grep ...`.

</details>

**A5.** Почему `uniq` почти всегда пишут после `sort`?

<details><summary>Ответ</summary>

`uniq` схлопывает только **подряд идущие** одинаковые строки. Без сортировки одинаковые
строки, разбросанные по файлу, не будут считаться дубликатами.

</details>

**A6.** Чем `sort` отличается от `sort -n`? Приведи пример, где разница критична.

<details><summary>Ответ</summary>

`sort` сравнивает как строки: `100` < `20` < `3`. `sort -n` — как числа.
Критично при сортировке размеров, кодов, времени ответа, PID.

</details>

**A7.** Зачем нужен `export`? Что произойдёт, если скрипт сделает `cd /tmp` — изменится ли каталог в родительском шелле? Как добиться изменения?

<details><summary>Ответ</summary>

Без `export` переменная видна только текущему shell; `export` помещает её в окружение,
наследуемое дочерними процессами. Скрипт выполняется в **дочернем** процессе, поэтому его `cd`
родителя не меняет. Чтобы изменить — выполнять в текущем шелле: `source script.sh` или `. script.sh`.

</details>

**A8.** Чем `tail -f` отличается от `tail -F` и почему на сервере нужен именно второй?

<details><summary>Ответ</summary>

`-f` следит за **дескриптором** открытого файла: после logrotate файл переименован/создан
заново, и ты продолжаешь читать старый. `-F` = `--follow=name --retry` — отслеживает **имя** и
переоткрывает файл. На сервере с ротацией нужен `-F`.

</details>

**A9.** Чем `grep -F` отличается от `grep -E`? Когда какой выбирать?

<details><summary>Ответ</summary>

`-F` — фиксированная строка, метасимволы regex не интерпретируются (быстро и безопасно,
идеально для поиска IP и путей). `-E` — расширенные регулярные выражения (`|`, `+`, `{}`, `()` без
экранирования). Выбирай `-F`, если ищешь литерал; `-E`, если нужен шаблон.

</details>

**A10.** Почему `cut -d' ' -f3` плохо работает с выводом `ps aux`, а `awk '{print $3}'` — хорошо?

<details><summary>Ответ</summary>

`cut -d' '` считает **каждый** пробел разделителем, поэтому подряд идущие пробелы создают
пустые поля и колонки «съезжают». `awk` по умолчанию разделяет по последовательностям пробелов/табов.

</details>

---

### Блок B. «Что выведет / что делает»

```bash
B1.  wc -l < /etc/passwd
B2.  wc -l /etc/passwd
B3.  cut -d: -f1,7 /etc/passwd | head -3
B4.  grep -c "" /etc/passwd
B5.  seq 1 5 | paste -sd',' -
B6.  echo "a b  c   d" | tr -s ' ' | tr ' ' '\n' | wc -l
B7.  printf '3\n20\n100\n' | sort
B8.  printf '3\n20\n100\n' | sort -n
B9.  grep -vE '^\s*(#|$)' /etc/ssh/sshd_config | wc -l
B10. ls /etc /nope 2>/dev/null | wc -l
B11. ls /etc /nope 2>&1 | grep -c cannot
B12. history | awk '{print $2}' | sort | uniq -c | sort -rn | head -5
B13. tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16; echo
B14. command -v docker >/dev/null 2>&1; echo $?
```

<details><summary>Ответ</summary>

- **B1.** Число строк, **без имени файла** (файл подан на stdin).
- **B2.** Число строк **и имя файла**.
- **B3.** Имя пользователя и его shell, первые 3 строки.
- **B4.** Количество строк в файле (`""` совпадает с любой строкой) — аналог `wc -l`.
- **B5.** `1,2,3,4,5`.
- **B6.** `4` — сжали пробелы, разбили по словам, посчитали строки.
- **B7.** `100`, `20`, `3` — лексикографическая сортировка.
- **B8.** `3`, `20`, `100`.
- **B9.** Число «значимых» строк конфига — без комментариев и пустых.
- **B10.** Количество элементов `/etc` (ошибка отброшена).
- **B11.** `1` — одна строка ошибки поймана, потому что stderr слит в stdout до пайпа.
- **B12.** Топ-5 самых часто используемых тобой команд из истории.
- **B13.** Случайная строка из 16 букв/цифр — генератор паролей.
- **B14.** `0`, если docker установлен, иначе `1` (вывод подавлен).

</details>

**B15.** Объясни, что делает каждый элемент цепочки:
```bash
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -3
```

<details><summary>Ответ</summary>

`awk '{print $1}'` — вырезать первое поле (IP); `sort` — сгруппировать одинаковые рядом;
`uniq -c` — схлопнуть и посчитать; `sort -rn` — отсортировать по числу по убыванию;
`head -3` — оставить топ-3.

</details>

---

### Блок C. Практика — анализ логов

Все задачи на файлах `~/lab03/access.log` и `~/lab03/app.log`. Решение — **одна строка**.

**C1.** Сколько всего запросов в `access.log`?

<details><summary>Ответ</summary>

```bash
wc -l < access.log
```

</details>

**C2.** Топ-5 IP по количеству запросов (с числами).

<details><summary>Ответ</summary>

```bash
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -5
```

</details>

**C3.** Сколько уникальных IP обратилось к серверу?

<details><summary>Ответ</summary>

```bash
awk '{print $1}' access.log | sort -u | wc -l
```

</details>

**C4.** Распределение HTTP-кодов: код и количество, по убыванию.

<details><summary>Ответ</summary>

```bash
awk '{print $9}' access.log | sort | uniq -c | sort -rn
```

</details>

**C5.** Сколько запросов завершились ошибкой 5xx?

<details><summary>Ответ</summary>

```bash
awk '$9 ~ /^5/' access.log | wc -l
```

</details>

**C6.** Какие URL чаще всего отдавали 500? (топ-3)

<details><summary>Ответ</summary>

```bash
awk '$9 == 500 {print $7}' access.log | sort | uniq -c | sort -rn | head -3
```

</details>

**C7.** Найди IP, который сделал больше всего запросов с кодом 404.

<details><summary>Ответ</summary>

```bash
awk '$9 == 404 {print $1}' access.log | sort | uniq -c | sort -rn | head -1
```

</details>

**C8.** Выведи 10 самых медленных запросов (последнее поле — время в мс): время + URL.

<details><summary>Ответ</summary>

```bash
awk '{print $NF, $7}' access.log | sort -rn | head -10
```

</details>

**C9.** Посчитай суммарное время всех запросов (подсказка: `awk '{s+=$NF} END{print s}'`).

<details><summary>Ответ</summary>

```bash
awk '{s+=$NF} END {print s}' access.log
```

</details>

**C10.** Из `app.log`: выведи все ERROR и FATAL строки вместе с 1 строкой контекста до каждой.

<details><summary>Ответ</summary>

```bash
grep -B1 -E "ERROR|FATAL" app.log
```

</details>

**C11.** Из `app.log`: сколько строк каждого уровня логирования (INFO/WARN/ERROR/FATAL)?

<details><summary>Ответ</summary>

```bash
awk '{print $3}' app.log | sort | uniq -c | sort -rn
```

</details>

**C12.** Из `app.log`: вытащи все значения `duration=...ms` и найди максимальное.

<details><summary>Ответ</summary>

```bash
grep -o 'duration=[0-9]*ms' app.log | grep -o '[0-9]*' | sort -n | tail -1
```

</details>

**C13.** Сохрани все ошибки из `access.log` (4xx и 5xx) в файл `errors.log` **и одновременно**
покажи на экране их количество. Использовать `tee`.

<details><summary>Ответ</summary>

```bash
awk '$9 ~ /^[45]/' access.log | tee errors.log | wc -l
```

</details>

**C14.** Сделай отчёт `report.txt`, содержащий:
```text:no-line-numbers
=== TRAFFIC REPORT ===
Total requests: 500
Unique IPs: 10
5xx errors: 47
Top IP: 10.0.0.3 (61)
```
*Критерий:* значения вычисляются, а не вписаны руками.

<details><summary>Ответ</summary>

```bash
{
  echo "=== TRAFFIC REPORT ==="
  echo "Total requests: $(wc -l < access.log)"
  echo "Unique IPs: $(awk '{print $1}' access.log | sort -u | wc -l)"
  echo "5xx errors: $(awk '$9 ~ /^5/' access.log | wc -l)"
  echo "Top IP: $(awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -1 | awk '{print $2" ("$1")"}')"
} > report.txt
cat report.txt
```

</details>

---

### Блок D. Практика — потоки и окружение

**D1.** Выполни `ls /etc /nonexistent` так, чтобы:
- (a) нормальный вывод ушёл в `out.txt`, ошибки — в `err.txt`;
- (b) оба потока ушли в один файл `all.txt`;
- (c) на экране осталось только сообщение об ошибке, а нормальный вывод исчез.

<details><summary>Ответ</summary>

```bash
ls /etc /nonexistent > out.txt 2> err.txt          # (a)
ls /etc /nonexistent > all.txt 2>&1                # (b)
ls /etc /nonexistent > /dev/null                   # (c)
```

</details>

**D2.** Напиши команду, которая тихо (без вывода) проверяет, установлен ли `nginx`,
и печатает `YES`/`NO`.

<details><summary>Ответ</summary>

```bash
command -v nginx >/dev/null 2>&1 && echo YES || echo NO
# или: dpkg -s nginx >/dev/null 2>&1 && echo YES || echo NO
```

</details>

**D3.** Добавь строку `net.ipv4.ip_forward=1` в конец `/etc/sysctl.conf`, работая **не** от root
(используй `sudo` правильно). Проверь, что строка появилась.

<details><summary>Ответ</summary>

```bash
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
tail -2 /etc/sysctl.conf
```

</details>

**D4.** Создай переменную `APP_ENV=prod` и убедись, что:
- дочерний bash её **не видит** без экспорта;
- видит после `export`;
- изменение в дочернем процессе **не влияет** на родителя.

<details><summary>Ответ</summary>

```bash
APP_ENV=prod
bash -c 'echo "[$APP_ENV]"'          # []  — пусто
export APP_ENV
bash -c 'echo "[$APP_ENV]"'          # [prod]
bash -c 'APP_ENV=dev; echo "child=$APP_ENV"'
echo "parent=$APP_ENV"               # prod — дочерний процесс не влияет на родителя
```

</details>

**D5.** Запусти команду так, чтобы переменная `DEBUG=1` была установлена **только** для неё,
не оставаясь в твоём окружении.

<details><summary>Ответ</summary>

```bash
DEBUG=1 ./script.sh          # или: env DEBUG=1 ./script.sh
echo "${DEBUG:-unset}"       # unset — в твоём окружении переменной нет
```

</details>

**D6.** Напиши скрипт `~/lab03/watch_errors.sh`, который следит за `app.log` в реальном времени
и показывает только строки с ERROR/FATAL, не «залипая» из-за буферизации.
Проверь: в другом окне дописывай строки в `app.log` через `echo ... >> app.log`.

<details><summary>Ответ</summary>

```bash
cat > ~/lab03/watch_errors.sh <<'EOF'
#!/usr/bin/env bash
tail -F "${1:-/home/vagrant/lab03/app.log}" | grep --line-buffered -E "ERROR|FATAL"
EOF
chmod +x ~/lab03/watch_errors.sh
```
Без `--line-buffered` grep копит вывод блоками по 4 КБ и строки появляются с большой задержкой.

</details>

---

### Блок E. Инциденты

**E1.** На сервере кончилось место. В `/var/log/nginx/access.log` — 8 ГБ.
Нужно: (1) узнать, какой IP налил больше всего трафика, (2) не открывая файл целиком в редакторе.
Какими командами?

<details><summary>Ответ</summary>

```bash
awk '{print $1, $10}' /var/log/nginx/access.log \
  | awk '{bytes[$1]+=$2} END {for (ip in bytes) print bytes[ip], ip}' \
  | sort -rn | head
```
Файл читается потоково, в память целиком не загружается. Для просмотра — `less`, `tail`, `head`,
но не `cat` и не редактор.

</details>

**E2.** Пайплайн `tail -f app.log | grep ERROR > errors.txt` запущен, но файл `errors.txt` остаётся
пустым, хотя ошибки в логе есть. Почему и как починить?

<details><summary>Ответ</summary>

Буферизация вывода: `grep` пишет не в терминал, а в файл, поэтому переходит на блочную
буферизацию (4 КБ). Починка: `tail -F app.log | grep --line-buffered ERROR > errors.txt`
(или `stdbuf -oL grep ERROR`).

</details>

**E3.** Скрипт в cron работает вручную, но из cron «ничего не делает и не пишет ошибок».
Как настроить логирование, чтобы увидеть причину? (Напиши строку cron.)

<details><summary>Ответ</summary>

У cron нет терминала, и вывод уходит в почту, которой обычно нет. Логируй явно:
```text:no-line-numbers
*/5 * * * * /opt/scripts/job.sh >> /var/log/job.log 2>&1
```
Частая вторая причина — другой `$PATH` в cron: использовать абсолютные пути.

</details>

**E4.** Тебе прислали CSV-файл из Windows. `cut -d',' -f3 data.csv` даёт странный результат,
а сравнение значений не работает. Диагноз и лечение (двумя способами).

<details><summary>Ответ</summary>

В файле окончания строк CRLF: последнее поле каждой строки содержит невидимый `\r`.
Диагноз: `file data.csv`, `cat -A data.csv` (увидишь `^M$`).
Лечение: `dos2unix data.csv` или `tr -d '\r' < data.csv > clean.csv` (либо `sed -i 's/\r$//'`).

</details>

**E5.** Коллега пишет `grep error /var/log/syslog | wc -l` и получает 0, хотя в логе явно есть
`Error` и `ERROR`. Что не так?

<details><summary>Ответ</summary>

`grep` регистрозависим: `error` ≠ `Error` ≠ `ERROR`. Нужно `grep -i error`.
Плюс `grep -c error file` эффективнее, чем `| wc -l`.

</details>

---

### Блок F. Вопросы с собеседования

**1.** Как посчитать топ-10 IP в access-логе одной строкой?

<details><summary>Ответ</summary>

`awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -10`

</details>

**2.** Что такое `2>&1` и зачем он нужен?

<details><summary>Ответ</summary>

Перенаправление stderr туда же, куда уже направлен stdout: собрать весь вывод в один файл/пайп.

</details>

**3.** Как дописать строку в файл, доступный только root, из пайпа?

<details><summary>Ответ</summary>

`echo "line" | sudo tee -a /path/file`

</details>

**4.** Чем `tee` отличается от `>`?

<details><summary>Ответ</summary>

`>` только записывает в файл; `tee` записывает в файл **и** передаёт данные дальше в stdout
(на экран или в следующий элемент конвейера).

</details>

**5.** Как найти в логе ошибку вместе с 5 строками вокруг неё?

<details><summary>Ответ</summary>

`grep -C5 "error" file`

</details>

**6.** Как узнать количество уникальных значений в колонке?

<details><summary>Ответ</summary>

`cut/awk` выделить колонку → `sort -u | wc -l` (или `sort | uniq -c` для частот).

</details>

**7.** Что произойдёт с переменной окружения, экспортированной в дочернем процессе, после его завершения?

<details><summary>Ответ</summary>

Ничего не произойдёт: окружение дочернего процесса умирает вместе с ним, на родителя не влияет.

</details>

**8.** Чем `xargs` отличается от пайпа?

<details><summary>Ответ</summary>

Пайп подаёт данные на **stdin** команды; `xargs` превращает поток в **аргументы командной строки**.
Это нужно для команд вроде `rm`, `mkdir`, `kill`, которые stdin не читают.

</details>

---

### 🎯 Чек-лист

- [ ] Помню формулу `sort | uniq -c | sort -rn | head` наизусть
- [ ] Понимаю разницу stdout/stderr и умею их разводить
- [ ] Знаю, почему `sudo tee`, а не `sudo echo >>`
- [ ] Умею `grep -A/-B/-C`, `-i`, `-v`, `-E`, `-o`, `-q`
- [ ] Решил все задачи блока C одной строкой каждую
- [ ] Понимаю `export` и наследование окружения
- [ ] Знаю про `--line-buffered` и `tail -F`
