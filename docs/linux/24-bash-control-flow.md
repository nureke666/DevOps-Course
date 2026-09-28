---
title: "24. Bash: условия, циклы, функции, массивы"
description: "if/case, [[ ]] vs (( )), циклы и ловушки subshell, функции с local, массивы"
---

# 24. Bash Scripting — условия, циклы, функции, массивы

> Конспект №2 модуля bash. Предыдущий: [23. Основы](/linux/23-bash-basics)
> **После темы ты умеешь:** писать разветвлённую логику, корректно обходить файлы и строки,
> раскладывать скрипт на функции и хранить данные в массивах.

---

## 🗺️ Схема: структура нормального скрипта

```text:no-line-numbers
┌──────────────────────────────────────────────────────┐
│ #!/usr/bin/env bash                                  │
│ set -euo pipefail            ← тема 25               │
├──────────────────────────────────────────────────────┤
│ КОНСТАНТЫ:  readonly LOG_DIR="/var/log/app"          │
├──────────────────────────────────────────────────────┤
│ ФУНКЦИИ:    log() die() usage() main()               │
│             ↑ маленькие, одна функция — одно дело    │
├──────────────────────────────────────────────────────┤
│ РАЗБОР АРГУМЕНТОВ: case / getopts                    │
├──────────────────────────────────────────────────────┤
│ main "$@"                    ← точка входа           │
└──────────────────────────────────────────────────────┘
```

---

## 1. Условия: что такое «истина» в bash

⚠️ Главное отличие от других языков: **истина — это код возврата 0**, а не значение `true`.
`if` смотрит не на «выражение», а на код завершения команды.

```bash
if grep -q "ERROR" app.log; then echo "есть ошибки"; fi     # if от КОМАНДЫ — нормально
if systemctl is-active --quiet nginx; then echo "работает"; fi
```

### `[ ]` vs `[[ ]]` vs `(( ))`

| Форма | Что это | Когда использовать |
|-------|---------|--------------------|
| `[ ]` | Это команда `test`, POSIX | Когда скрипт должен работать в `sh`/alpine |
| `[[ ]]` | Ключевое слово bash | ⭐ По умолчанию в bash: безопаснее и умеет больше |
| `(( ))` | Арифметический контекст | Всё, что про числа |

```bash
[[ -f "$file" ]]                 # без кавычек тоже не сломается, но кавычки — привычка
[[ $str == ab* ]]                # шаблон (globbing) — БЕЗ кавычек справа
[[ $str == "ab*" ]]              # буквальное сравнение — в кавычках
[[ $str =~ ^[0-9]{3}$ ]]         # регулярка (regex справа НЕ в кавычках)
[[ -n $a && -z $b ]]             # && и || прямо внутри
(( count > 10 ))                 # числа — без -gt и без $
```

### Проверки файлов

| Тест | Истина, если |
|------|--------------|
| `-e path` | Существует (любой тип) |
| `-f path` | Обычный файл |
| `-d path` | Каталог |
| `-L path` | Символическая ссылка |
| `-s path` | Существует и **не пустой** |
| `-r / -w / -x` | Доступен на чтение / запись / выполнение |
| `f1 -nt f2` / `-ot` | Новее / старше по времени модификации |

### Сравнение строк и чисел — не перепутать

| Строки (`[[ ]]`) | Числа (`[ ]` / `(( ))`) |
|------------------|-------------------------|
| `==`, `!=` | `-eq`, `-ne` |
| `<`, `>` (лексикографически) | `-lt`, `-le`, `-gt`, `-ge` |
| `-z` пусто, `-n` не пусто | `(( a > b ))` |

```bash
[[ "10" > "9" ]]  && echo "строки: 10 больше 9?"   # ЛОЖЬ — лексикографически "1" < "9"
(( 10 > 9 ))      && echo "числа: верно"           # ИСТИНА
```

---

## 2. if / case

```bash
if [[ $used -gt 90 ]]; then
  level="critical"
elif [[ $used -gt 75 ]]; then
  level="warning"
else
  level="ok"
fi

# Короткие формы — для однострочных проверок
[[ -d /var/log/app ]] || mkdir -p /var/log/app
command -v jq >/dev/null || { echo "нужен jq" >&2; exit 1; }
```

`case` — когда вариантов больше двух и они по шаблону:

```bash
case "$1" in
  start)            systemctl start myapp ;;
  stop)             systemctl stop myapp ;;
  restart|reload)   systemctl restart myapp ;;      # несколько вариантов через |
  status)           systemctl status myapp ;;
  *.log)            echo "это лог-файл" ;;          # шаблоны работают
  '')               echo "пустой аргумент" >&2; exit 2 ;;
  *)                echo "usage: $0 {start|stop|restart|status}" >&2; exit 2 ;;
esac
```

⭐ Проверка «это число?» без regex — классика: `case "$v" in ''|*[!0-9]*) echo "не число";; esac`

---

## 3. Циклы

```bash
# По списку
for env in dev stage prod; do echo "деплой в $env"; done

# По файлам — ⭐ ГЛОБ, а не $(ls)
for f in /var/log/*.log; do
  [[ -e $f ]] || continue          # защита: если ничего не совпало, глоб останется строкой
  echo "$f: $(wc -l < "$f") строк"
done

# C-style и диапазоны
for (( i=1; i<=5; i++ )); do echo "попытка $i"; done
for i in {1..10}; do echo "$i"; done
for i in {0..20..5}; do echo "$i"; done       # с шагом
n=5; for i in $(seq 1 "$n"); do echo "$i"; done   # когда границы в переменных

# По аргументам скрипта
for arg in "$@"; do echo "[$arg]"; done

# while / until
while (( attempt < 5 )); do ((attempt++)); done
until curl -sf http://localhost:8080/health >/dev/null; do sleep 2; done

break        # выйти из цикла
continue     # к следующей итерации
break 2      # выйти из двух вложенных циклов
```

### ⭐ Чтение файла построчно — единственно правильная форма

```bash
while IFS= read -r line; do
  echo "строка: $line"
done < /etc/passwd
```

Почему именно так:
- `IFS=` — не обрезать пробелы в начале и конце строки;
- `read -r` — не съедать обратные слэши;
- `< файл` в конце — перенаправление на весь цикл.

```bash
# Разбор по полям сразу в переменные
while IFS=: read -r user _ uid _ _ home shell; do
  (( uid >= 1000 )) && echo "$user ($uid) $home $shell"
done < /etc/passwd
```

### ⚠️ Ловушка subshell: `cmd | while read`

```bash
count=0
grep ERROR app.log | while read -r line; do (( count++ )); done
echo "$count"     # 0 (!) — цикл выполнялся в подпроцессе, переменная не сохранилась

# Решение 1 — перенаправление вместо пайпа (process substitution)
count=0
while read -r line; do (( count++ )); done < <(grep ERROR app.log)
echo "$count"     # правильное значение

# Решение 2 — shopt -s lastpipe (только с отключённым job control)
```

### ⚠️ Ловушка: `ssh` внутри цикла съедает stdin

```bash
while read -r host; do
  ssh "$host" uptime            # ssh прочитает ВЕСЬ оставшийся список хостов
done < hosts.txt

while read -r host; do
  ssh -n "$host" uptime         # ✅ -n: не читать stdin (или < /dev/null)
done < hosts.txt
```

---

## 4. Функции

```bash
log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die()  { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }

backup_dir() {
  local src="$1"                       # ⭐ local — иначе переменная глобальная
  local dst="${2:-/backup}"
  local name="${src##*/}-$(date +%F).tar.gz"

  [[ -d $src ]] || { log "нет каталога $src"; return 1; }   # return — КОД, не значение
  tar -czf "$dst/$name" -C "$(dirname "$src")" "$name" || return 1
  printf '%s/%s\n' "$dst" "$name"      # «возврат значения» = вывод в stdout
}

# Вызов
if archive=$(backup_dir /etc /backup); then
  log "готово: $archive"
else
  die "бэкап не удался"
fi
```

| Правило | Почему |
|---------|--------|
| `local` для всех внутренних переменных | Иначе функция незаметно портит глобальные |
| `return` возвращает **код** (0-255) | Для данных — `echo`/`printf` и `$(...)` |
| Аргументы — те же `$1`, `$2`, `"$@"` | `$0` при этом остаётся именем скрипта |
| Функцию определяют **до** вызова | Bash читает файл сверху вниз |
| `main "$@"` в конце | Логика вся в функциях, файл читается как оглавление |

```bash
# Общая библиотека функций
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
```

---

## 5. Массивы

```bash
# Индексные
services=(nginx postgresql redis)
services+=(rabbitmq)                  # добавить
echo "${services[0]}"                 # nginx
echo "${services[@]}"                 # все элементы
echo "${#services[@]}"                # количество: 4
echo "${services[-1]}"                # последний
unset 'services[1]'                   # удалить элемент

for s in "${services[@]}"; do         # ⭐ кавычки и [@] обязательны
  systemctl is-active --quiet "$s" && echo "$s: ok" || echo "$s: DOWN"
done

# Массив из вывода команды (по строкам)
mapfile -t users < <(awk -F: '$3>=1000 {print $1}' /etc/passwd)
readarray -t logs < <(find /var/log -name '*.log' -type f)
echo "нашёл ${#logs[@]} логов"

# Ассоциативные (словари) — только bash 4+
declare -A thresholds=([cpu]=80 [mem]=90 [disk]=85)
thresholds[net]=70
echo "${thresholds[cpu]}"             # 80
for key in "${!thresholds[@]}"; do    # ! — перебор КЛЮЧЕЙ
  echo "$key -> ${thresholds[$key]}"
done
[[ -v thresholds[cpu] ]] && echo "ключ есть"
```

⚠️ `"${arr[@]}"` — каждый элемент отдельным словом (нужно почти всегда);
`"${arr[*]}"` — одна строка через первый символ `IFS`. Без кавычек — снова word splitting.

⚠️ Массивов **нет** в `sh`/dash/busybox — в alpine-контейнерах скрипт с массивами не запустится.

---

## 6. Собираем всё вместе — каркас скрипта

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly SERVICES=(ssh cron nginx)
readonly THRESHOLD=85

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

check_services() {
  local failed=0 svc
  for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc"; then
      log "OK   $svc"
    else
      log "FAIL $svc"
      (( failed++ )) || true
    fi
  done
  return "$failed"
}

check_disk() {
  local used
  used=$(df --output=pcent / | tr -dc '0-9')
  (( used < THRESHOLD )) || { log "FAIL диск: ${used}%"; return 1; }
  log "OK   диск: ${used}%"
}

main() {
  local rc=0
  check_services || rc=1
  check_disk     || rc=1
  (( rc == 0 )) && log "всё в порядке" || log "есть проблемы"
  return "$rc"
}

main "$@"
```

---

## 💼 Как это в DevOps

- Цикл по хостам + `ssh -n` — самый частый «ansible на минималках» до появления Ansible.
- `while IFS= read -r` — разбор логов, CSV-выгрузок, списков инстансов из API.
- Ассоциативные массивы — пороги мониторинга, маппинг «окружение → кластер», «сервис → порт».
- `case "$1" in start|stop|restart)` — интерфейс любого управляющего скрипта и старых init-скриптов.
- Функции `log`/`die` копируются из скрипта в скрипт — это де-факто стандарт.
- Умение заметить `cmd | while read` в чужом скрипте экономит часы отладки «почему счётчик нулевой».

---

## 🧪 Мини-лаба

```bash
vagrant ssh
mkdir -p ~/lab24 && cd ~/lab24

# 1. Истина в bash — это код возврата
if grep -q root /etc/passwd; then echo "root есть"; fi
if ! systemctl is-active --quiet nosuchservice; then echo "сервиса нет"; fi

# 2. [ ] vs [[ ]] vs (( ))
a=10 b=9
[[ $a > $b ]] && echo "строковое сравнение: $a > $b"     # ЛОЖЬ по-строковому
(( a > b ))   && echo "числовое сравнение: $a > $b"      # ИСТИНА
str="access.log"
[[ $str == *.log ]] && echo "шаблон сработал"
[[ $str =~ ^[a-z]+\.log$ ]] && echo "regex сработал"

# 3. case-интерфейс
cat > svc.sh <<'EOS'
#!/usr/bin/env bash
case "${1:-}" in
  start)   echo "запускаю..." ;;
  stop)    echo "останавливаю..." ;;
  restart) echo "перезапускаю..." ;;
  status)  echo "состояние: ок" ;;
  *)       echo "usage: $0 {start|stop|restart|status}" >&2; exit 2 ;;
esac
EOS
chmod +x svc.sh; ./svc.sh start; ./svc.sh; echo "код: $?"

# 4. Цикл по файлам правильно
sudo ls /var/log/*.log >/dev/null 2>&1
for f in /var/log/*.log; do
  [[ -e $f ]] || continue
  printf '%-40s %8s строк\n' "$f" "$(sudo wc -l < "$f")"
done

# 5. Построчное чтение и разбор полей
while IFS=: read -r user _ uid _ _ home shell; do
  (( uid >= 1000 && uid < 65534 )) && printf '%-12s uid=%-6s %s\n' "$user" "$uid" "$shell"
done < /etc/passwd

# 6. Ловушка subshell — увидеть своими глазами
count=0; printf 'a\nb\nc\n' | while read -r _; do (( count++ )); done; echo "через пайп: $count"
count=0; while read -r _; do (( count++ )); done < <(printf 'a\nb\nc\n'); echo "через <(): $count"

# 7. Функции и local
cat > lib.sh <<'EOS'
log() { printf '[%s] %s\n' "$(date '+%T')" "$*"; }
die() { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }
disk_pct() { df --output=pcent "${1:-/}" | tr -dc '0-9'; }
EOS
source ./lib.sh
log "диск занят на $(disk_pct /)%"
( die "так выглядит падение" ) ; echo "код после die: $?"

# 8. Массивы
services=(ssh cron dbus)
services+=(systemd-journald)
echo "всего: ${#services[@]}"
for s in "${services[@]}"; do
  printf '%-20s %s\n' "$s" "$(systemctl is-active "$s")"
done
mapfile -t users < <(awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd)
echo "обычные пользователи (${#users[@]}): ${users[*]}"

# 9. Ассоциативный массив
declare -A limit=([cpu]=80 [mem]=90 [disk]=85)
for k in "${!limit[@]}"; do printf 'порог %-5s = %s%%\n' "$k" "${limit[$k]}"; done

# 10. Уборка
cd ~ && rm -rf ~/lab24
```

---

## 📌 Шпаргалка

| Конструкция | Смысл |
|-------------|-------|
| `if cmd; then … fi` | Условие по коду возврата команды |
| `[[ -f f ]]`, `[[ -d d ]]`, `[[ -s f ]]` | Файл / каталог / непустой файл |
| `[[ $a == шаблон ]]`, `[[ $a =~ regex ]]` | Сравнение по шаблону / регулярке |
| `(( a > b ))` | Числовое сравнение |
| `[[ -z $v ]]` / `[[ -n $v ]]` | Пусто / не пусто |
| `case "$1" in x) … ;; *) … ;; esac` | Ветвление по шаблонам |
| `for f in ./*; do … done` | Обход файлов (не через `ls`!) |
| `for (( i=0; i<n; i++ ))` | Счётный цикл |
| `while IFS= read -r line; do … done < f` | ⭐ Построчное чтение |
| `while … done < <(cmd)` | Без subshell — переменные сохраняются |
| `func() { local x="$1"; …; }` | Функция с локальной переменной |
| `return N` / `echo значение` | Код возврата / «возврат» данных |
| `arr=(a b c)`, `"${arr[@]}"`, `${#arr[@]}` | Массив, элементы, длина |
| `declare -A m`, `"${!m[@]}"` | Словарь и его ключи |
| `mapfile -t arr < <(cmd)` | Вывод команды → массив строк |
| `main "$@"` | Точка входа в конце скрипта |

---

## 🧠 Что запомнить

1. `if` проверяет **код возврата**, а не значение: `0` — истина.
2. В bash по умолчанию `[[ ]]`; `[ ]` — только когда нужен POSIX `sh`.
3. Числа сравнивают `(( ))` или `-gt/-lt`, строки — `==`/`!=`; перепутаешь — получишь `10 < 9`.
4. Обход файлов — глобом `./*`, никогда не `$(ls)`.
5. Построчное чтение — только `while IFS= read -r line; do … done < файл`.
6. `cmd | while read` создаёт subshell: переменные после цикла теряются — используй `< <(cmd)`.
7. `ssh` в цикле нужен с `-n`, иначе он «съест» список хостов.
8. `local` в каждой функции; `return` — это код, данные возвращают через stdout.
9. `"${arr[@]}"` с кавычками; в dash/alpine массивов нет вообще.
10. Скрипт из функций + `main "$@"` читается и правится в разы легче простыни команд.

Дальше — [25. Robust: set -euo pipefail, trap](/linux/25-bash-robust).

---

## Задачи

> `vagrant snapshot save before_24 && vagrant ssh`
> ⭐ Блок C — ровно то, что дают как тестовое задание джуну.

### Блок A. Теория

**A1.** Что для `if` является «истиной» в bash? Почему `if [ ... ]` — это тоже проверка команды?

<details><summary>Ответ</summary>

Истина — код возврата 0. `[` — это исполняемая команда (`/usr/bin/[`, а в bash —
встроенная), которая просто возвращает 0 или 1; поэтому `if` везде работает одинаково.

</details>

**A2.** Чем `[[ ]]` отличается от `[ ]`? Назови 4 возможности, которых нет в `[ ]`.

<details><summary>Ответ</summary>

`[[ ]]` — ключевое слово bash, разбирается парсером до раскрытий: нет word splitting
и globbing внутри, поэтому пустая переменная не ломает синтаксис. Умеет: шаблоны `==` с `*`,
регулярки `=~`, логические `&&`/`||` внутри скобок, сравнение строк `<`/`>` без экранирования.

</details>

**A3.** Когда использовать `(( ))`, а когда `[[ ]]`?

<details><summary>Ответ</summary>

`(( ))` — для любых чисел и счётчиков (короче и без `-gt`), `[[ ]]` — для строк, файлов
и шаблонов.

</details>

**A4.** Почему `[[ "10" > "9" ]]` — ложь, а `(( 10 > 9 ))` — истина?

<details><summary>Ответ</summary>

`>` в `[[ ]]` сравнивает строки лексикографически: `"1"` меньше `"9"`, поэтому `"10" < "9"`.
`(( ))` работает с числами.

</details>

**A5.** Перечисли тесты файлов: `-e`, `-f`, `-d`, `-L`, `-s`, `-r/-w/-x`, `-nt`.

<details><summary>Ответ</summary>

`-e` существует; `-f` обычный файл; `-d` каталог; `-L` симлинк; `-s` существует и непустой;
`-r/-w/-x` доступен на чтение/запись/выполнение текущему пользователю; `f1 -nt f2` — f1 новее f2.

</details>

**A6.** В чём разница `[[ $s == ab* ]]`, `[[ $s == "ab*" ]]` и `[[ $s =~ ^ab ]]`?

<details><summary>Ответ</summary>

Первое — сравнение по шаблону (глоб): истина для `abc`, `ab123`. Второе — буквальное
сравнение со строкой `ab*`. Третье — регулярное выражение: истина, если строка начинается с `ab`.

</details>

**A7.** Почему `for f in $(ls)` — плохо, а `for f in ./*` — хорошо?

<details><summary>Ответ</summary>

Вывод `ls` — это текст, который режется по `IFS`: имена с пробелами разваливаются,
спецсимволы и переводы строк в именах ломают всё окончательно, а цвета/опции `ls` могут
добавить лишнее. Глоб `./*` отдаёт элементы как отдельные слова, без разбора текста.

</details>

**A8.** Зачем в `while IFS= read -r line` нужны `IFS=` и `-r`?

<details><summary>Ответ</summary>

`IFS=` отключает обрезание ведущих и конечных пробелов/табов в строке;
`-r` запрещает интерпретировать `\` как экранирование (иначе пути вроде `C:\dir` исказятся).

</details>

**A9.** Почему после `cmd | while read …; done` счётчик, изменённый внутри цикла, равен нулю?
Два способа это обойти.

<details><summary>Ответ</summary>

Каждая часть пайпа выполняется в отдельном подпроцессе; переменные, изменённые в нём,
пропадают вместе с ним. Обход: `while … done < <(cmd)` (process substitution) либо
`shopt -s lastpipe` (в неинтерактивном bash с выключенным job control).

</details>

**A10.** Почему `ssh` внутри `while read` ломает цикл и как это лечится?

<details><summary>Ответ</summary>

`ssh` читает stdin, а stdin цикла — это файл со списком хостов; ssh вычитывает его
целиком, и цикл делает одну итерацию. Лечение: `ssh -n` или `ssh … < /dev/null`.

</details>

**A11.** Зачем в функциях писать `local`? Что вернёт `return` и как вернуть строку?

<details><summary>Ответ</summary>

Без `local` переменная функции глобальна и может затереть переменную вызывающего кода
(классика — счётчик `i`). `return` возвращает код 0-255; данные возвращают печатью в stdout
и захватом через `$(...)`.

</details>

**A12.** Чем `"${arr[@]}"` отличается от `"${arr[*]}"` и от `${arr[@]}` без кавычек?

<details><summary>Ответ</summary>

`"${arr[@]}"` — каждый элемент отдельным словом (правильно почти всегда);
`"${arr[*]}"` — одна строка, элементы через первый символ IFS; `${arr[@]}` без кавычек
дополнительно режется по пробелам внутри элементов.

</details>

**A13.** Как объявить словарь и перебрать его ключи?

<details><summary>Ответ</summary>

`declare -A m; m[key]=value`; ключи — `"${!m[@]}"`, значения — `"${m[@]}"`,
проверка ключа — `[[ -v m[key] ]]`.

</details>

**A14.** Почему скрипт с массивами не заработает в alpine-контейнере?

<details><summary>Ответ</summary>

В alpine `/bin/sh` — busybox ash, а bash по умолчанию не установлен: нет `declare -A`,
массивов, `[[ ]]`. Варианты: `apk add bash` и правильный shebang, либо писать на POSIX sh.

</details>

**A15.** Зачем нужен паттерн `main "$@"` в конце скрипта?

<details><summary>Ответ</summary>

Все определения идут сверху, исполнение — одной строкой в конце: скрипт не начинает
что-то делать при частичной загрузке файла, легко тестировать функции по отдельности
(`source script.sh` без запуска main) и читать логику как оглавление.

</details>

---

### Блок B. «Что выведет / найди ошибку»

```bash
B1.  x=5;  [[ $x -gt 3 ]] && echo big || echo small
B2.  s="";  [[ -z $s ]] && echo "пусто"
B3.  f=/etc/passwd; [[ -f $f && -r $f ]] && echo "читаемый файл"
B4.  for i in {1..3}; do echo -n "$i "; done; echo
B5.  n=3; for i in {1..$n}; do echo -n "$i "; done; echo
B6.  for i in $(seq 1 3); do echo -n "$i "; done; echo
B7.  arr=(a b c); echo "${#arr[@]} ${arr[1]} ${arr[-1]}"
B8.  arr=(a b c); echo "${arr[@]:1}"
B9.  declare -A m=([x]=1 [y]=2); echo "${!m[@]}" ; echo "${m[@]}"
B10. f() { local v=inner; }; v=outer; f; echo "$v"
B11. f() { v=inner; }; v=outer; f; echo "$v"
B12. f() { return 7; }; f; echo $?
B13. f() { echo "данные"; return 1; }; out=$(f); echo "$out / $?"
B14. c=0; printf 'a\nb\n' | while read -r l; do ((c++)); done; echo "$c"
B15. c=0; while read -r l; do ((c++)); done < <(printf 'a\nb\n'); echo "$c"
B16. case abc.log in *.log) echo "лог";; *) echo "не лог";; esac
```

<details><summary>Ответ</summary>

- **B1.** `big`.
- **B2.** `пусто`.
- **B3.** `читаемый файл`.
- **B4.** `1 2 3`.
- **B5.** `{1..3}` — раскрытие скобок происходит **до** подстановки переменных, диапазон
  с переменной не работает. Нужно `seq` или C-style цикл.
- **B6.** `1 2 3`.
- **B7.** `3 b c`.
- **B8.** `b c` — срез массива с индекса 1.
- **B9.** `x y` и `1 2` (порядок ключей в ассоциативном массиве не гарантирован).
- **B10.** `outer` — `local` защитил внешнюю переменную.
- **B11.** `inner` — функция затёрла глобальную переменную.
- **B12.** `7`.
- **B13.** `данные / 0` — `$?` относится к присваиванию, а не к функции. Чтобы получить код
  функции, нужно `out=$(f) || rc=$?` или проверять сразу: `if out=$(f); then …`.
- **B14.** `0` — цикл в подпроцессе.
- **B15.** `2`.
- **B16.** `лог`.

</details>

**B17.** Найди три ошибки:
```bash
for file in $(ls /var/log)
do
  if [ $file = "syslog" ]
  then echo "нашёл syslog"
  fi
done
```

<details><summary>Ответ</summary>

Ошибки: (1) `$(ls)` вместо глоба — ломается на пробелах и отдаёт только имена без пути;
(2) `$file` без кавычек — `[: too many arguments` при пустом или составном значении;
(3) сравнение через `[ ... = ... ]` без кавычек справа/слева и без `--`. Правильно:
```bash
for file in /var/log/*; do
  [[ "${file##*/}" == "syslog" ]] && echo "нашёл syslog"
done
```

</details>

---

### Блок C. Практика

**C1. 🔑 Health-check сервера (главное задание)**

`~/bin/healthcheck.sh` — проверяет и печатает отчёт:
- список сервисов задаётся массивом в начале скрипта;
- пороги (cpu/mem/disk) — в ассоциативном массиве;
- каждая проверка — отдельная функция, возвращающая код;
- вывод: `OK` / `WARN` / `CRIT` с выравниванием через `printf`;
- итоговый код выхода: 0 — всё ок, 1 — есть WARN, 2 — есть CRIT;
- вся логика в функциях, в конце `main "$@"`.

**Критерии приёмки:** `./healthcheck.sh; echo $?` даёт осмысленный код;
скрипт не падает, если сервиса нет в системе; повторный запуск даёт тот же результат.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail

readonly SERVICES=(ssh cron systemd-journald)
declare -A LIMIT=([cpu]=80 [mem]=90 [disk]=85)
warn_found=0; crit_found=0

log() { printf '%-8s %-22s %s\n' "$1" "$2" "${3:-}"; }

check_service() {
  local svc="$1"
  if ! systemctl list-unit-files "$svc.service" >/dev/null 2>&1; then
    log WARN "$svc" "нет такого юнита"; warn_found=1; return 1
  fi
  if systemctl is-active --quiet "$svc"; then
    log OK "$svc" "active"
  else
    log CRIT "$svc" "не работает"; crit_found=1; return 2
  fi
}

check_disk() {
  local used; used=$(df --output=pcent / | tr -dc '0-9')
  if   (( used >= LIMIT[disk] )); then log CRIT "disk /" "${used}%"; crit_found=1
  elif (( used >= LIMIT[disk] - 10 )); then log WARN "disk /" "${used}%"; warn_found=1
  else log OK "disk /" "${used}%"; fi
}

check_mem() {
  local total avail used
  total=$(awk '/MemTotal/{print $2}' /proc/meminfo)
  avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  used=$(( (total - avail) * 100 / total ))
  (( used >= LIMIT[mem] )) && { log CRIT memory "${used}%"; crit_found=1; } || log OK memory "${used}%"
}

main() {
  printf '=== HEALTHCHECK %s ===\n' "$(date '+%F %T')"
  local s; for s in "${SERVICES[@]}"; do check_service "$s"; done
  check_disk; check_mem
  (( crit_found )) && return 2
  (( warn_found )) && return 1
  return 0
}

main "$@"
```

</details>

**C2. case-интерфейс.** `myapp.sh {start|stop|restart|status|logs}` — выводит, что бы он сделал
(без реальных действий), на неизвестную команду печатает usage в stderr и `exit 2`.

<details><summary>Ответ</summary>

```bash
case "${1:-}" in
  start)   echo "systemctl start myapp" ;;
  stop)    echo "systemctl stop myapp" ;;
  restart) echo "systemctl restart myapp" ;;
  status)  echo "systemctl status myapp" ;;
  logs)    echo "journalctl -u myapp -f" ;;
  *)       echo "usage: $0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
esac
```

</details>

**C3. Обход файлов.** Скрипт принимает каталог и выводит топ-5 самых больших файлов
в нём **рекурсивно**, корректно работая с пробелами в именах (подсказка: `find -print0`,
`while IFS= read -r -d ''`).

<details><summary>Ответ</summary>

```bash
dir="${1:?нужен каталог}"
while IFS= read -r -d '' f; do
  printf '%s\t%s\n' "$(stat -c %s -- "$f")" "$f"
done < <(find "$dir" -type f -print0) | sort -rn | head -5 | cut -f2-
```
`-print0` + `read -d ''` — единственный полностью безопасный способ обходить произвольные имена.

</details>

**C4. Построчный разбор.** Из `/etc/passwd` вывести таблицу: логин, uid, домашний каталог,
shell — только для обычных пользователей (uid ≥ 1000, кроме `nobody`). Без `awk` — циклом.

<details><summary>Ответ</summary>

```bash
while IFS=: read -r user _ uid _ _ home shell; do
  (( uid >= 1000 )) || continue
  [[ $user == nobody ]] && continue
  printf '%-14s %-6s %-20s %s\n' "$user" "$uid" "$home" "$shell"
done < /etc/passwd
```

</details>

**C5. Счётчик без subshell.** Посчитай в цикле количество строк с `error` (без учёта регистра)
в `/var/log/syslog` двумя способами: через пайп (и покажи, что счётчик теряется) и через
`< <(...)` (счётчик сохраняется).

<details><summary>Ответ</summary>

```bash
c=0; grep -i error /var/log/syslog | while read -r _; do ((c++)); done; echo "через пайп: $c"   # 0
c=0; while read -r _; do ((c++)); done < <(grep -i error /var/log/syslog); echo "через <(): $c"
```

</details>

**C6. Функции-библиотека.** Вынеси в `lib.sh` функции `log`, `warn`, `die`, `require_cmd`,
`confirm`. Подключи из двух разных скриптов. `require_cmd jq curl` должна падать с понятным
текстом, если утилиты нет.

<details><summary>Ответ</summary>

```bash
# lib.sh
log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(date '+%F %T')" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }
require_cmd() {
  local c missing=()
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
  (( ${#missing[@]} == 0 )) || die "не хватает утилит: ${missing[*]}"
}
confirm() { local a; read -r -p "${1:-Продолжить?} [y/N] " a; [[ $a == [yY] ]]; }
```

</details>

**C7. Массив хостов.** Файл `hosts.txt` со списком хостов. Скрипт читает его в массив,
пингует каждый (1 пакет, таймаут 1 с) и печатает таблицу «хост / доступен / время».
В конце — сводка «доступно N из M». Хосты с `#` в начале — пропускать.

<details><summary>Ответ</summary>

```bash
mapfile -t hosts < <(grep -vE '^\s*(#|$)' hosts.txt)
ok=0
for h in "${hosts[@]}"; do
  if t=$(ping -c1 -W1 "$h" 2>/dev/null | awk -F'time=' '/time=/{print $2; exit}'); then
    printf '%-20s %-10s %s\n' "$h" "доступен" "$t"; (( ok++ ))
  else
    printf '%-20s %-10s\n' "$h" "НЕДОСТУПЕН"
  fi
done
printf 'доступно %d из %d\n' "$ok" "${#hosts[@]}"
```

</details>

**C8. Ассоциативный массив как конфиг.** Маппинг «окружение → namespace»:
dev→app-dev, stage→app-stage, prod→app-prod. Скрипт принимает окружение аргументом,
проверяет, что такой ключ есть, и печатает команду `kubectl -n <ns> get pods`.
Неизвестное окружение → список доступных и `exit 2`.

<details><summary>Ответ</summary>

```bash
declare -A NS=([dev]=app-dev [stage]=app-stage [prod]=app-prod)
env="${1:-}"
if [[ -z $env || ! -v NS[$env] ]]; then
  echo "доступные окружения: ${!NS[*]}" >&2; exit 2
fi
echo "kubectl -n ${NS[$env]} get pods"
```

</details>

**C9. Ретрай с задержкой.** Функция `retry <кол-во> <команда…>`: выполняет команду,
при неудаче ждёт 2, 4, 8 секунд (экспоненциальная задержка) и пробует снова.
Проверь на `curl -sf http://localhost:9999/` (заведомо недоступен) и на `true`.

<details><summary>Ответ</summary>

```bash
retry() {
  local tries="$1"; shift
  local n=1 delay=2
  until "$@"; do
    (( n >= tries )) && { echo "сдаюсь после $n попыток: $*" >&2; return 1; }
    echo "попытка $n не удалась, жду ${delay}s..." >&2
    sleep "$delay"; delay=$(( delay * 2 )); (( n++ ))
  done
  echo "успех с $n-й попытки"
}
retry 3 curl -sf http://localhost:9999/ ; echo "код: $?"
retry 3 true
```

</details>

**C10. Цикл по хостам через ssh.** На своём стенде (или с `localhost` в списке) выполни
`uptime` на каждом хосте из файла. Сначала **без** `-n` — покажи, что цикл отработает один раз.
Потом добавь `-n` и объясни разницу.

<details><summary>Ответ</summary>

Без `-n` цикл делает одну итерацию: `ssh` вычитал весь `hosts.txt` из stdin и передал
его удалённой команде. С `ssh -n` (или `< /dev/null`) stdin цикла остаётся нетронутым,
и обрабатываются все хосты.

</details>

---

### Блок D. Инциденты

**D1.** Скрипт обходит `for f in $(find /data -name '*.csv')` и «теряет» файлы с пробелами.
Как переписать?

<details><summary>Ответ</summary>

`while IFS= read -r -d '' f; do … done < <(find /data -name '*.csv' -print0)` —
нулевой разделитель единственный, который не может встретиться в имени файла.
Альтернатива: `find … -exec … {} +`.

</details>

**D2.** Цикл по 50 хостам из файла отрабатывает ровно один раз и молча завершается. Диагноз?

<details><summary>Ответ</summary>

Внутри цикла вызывается команда, читающая stdin (`ssh`, `mysql`, `ffmpeg`, `docker exec -i`),
и она забирает весь список. Лечение: `ssh -n`, `< /dev/null` у команды, либо читать список
через другой дескриптор: `while read -r h <&3; do …; done 3< hosts.txt`.

</details>

**D3.** Функция должна вернуть имя созданного архива, но в вызывающем коде приходит `0`.
Что перепутал автор?

<details><summary>Ответ</summary>

Автор написал `return "$archive"` — `return` принимает только числовой код (и берёт его
по модулю 256). Имя нужно печатать в stdout и ловить `archive=$(backup_dir …)`.

</details>

**D4.** Скрипт с `for i in {1..$COUNT}` печатает буквально `{1..10}`. Почему и как исправить?

<details><summary>Ответ</summary>

Раскрытие `{1..N}` выполняется раньше подстановки переменных, поэтому получается
буквальная строка. Варианты: `for (( i=1; i<=COUNT; i++ ))` или `for i in $(seq 1 "$COUNT")`.

</details>

**D5.** После вызова функции у вызывающего кода «испортилась» переменная `i`,
и внешний цикл пошёл по кругу. Что забыли в функции?

<details><summary>Ответ</summary>

В функции переменная цикла объявлена без `local`, поэтому функция затирает `i`
вызывающего цикла. Правило: любая переменная внутри функции — `local`.

</details>

**D6.** Скрипт работает на Ubuntu, но в alpine-контейнере падает:
`syntax error: unexpected "("` на строке `declare -A limits=(...)`. Причина и варианты решения.

<details><summary>Ответ</summary>

В alpine нет bash (только busybox ash), а `declare -A` — это bash 4+. Решения:
`apk add --no-cache bash` и shebang `#!/usr/bin/env bash`; либо переписать на POSIX sh
(словарь заменить на `case` или на два параллельных списка).

</details>

**D7.** `if [ $status = running ]` падает с `too many arguments`, когда `$status` пустая
или содержит два слова. Как правильно?

<details><summary>Ответ</summary>

Пустая переменная превращает выражение в `[ = running ]`, а значение с пробелом — в лишние
аргументы. Правильно: `[[ $status == running ]]` или, если нужен POSIX, `[ "$status" = running ]`.

</details>

**D8.** В цикле проверки сервисов используется `(( failed++ ))` и скрипт с `set -e`
неожиданно завершается на первой же итерации. Почему?

<details><summary>Ответ</summary>

`(( failed++ ))` возвращает код 1, когда **старое** значение было 0, а `set -e` считает
это ошибкой и завершает скрипт. Пишут `(( ++failed ))`, `failed=$(( failed + 1 ))`
или `(( failed++ )) || true`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем `[[ ]]` отличается от `[ ]`?

<details><summary>Ответ</summary>

`[[ ]]` — ключевое слово bash: без word splitting и globbing внутри, есть `=~`, шаблоны,
`&&`/`||`; `[ ]` — POSIX-команда `test`, работает и в dash.

</details>

**2.** Как сравнить числа и как строки?

<details><summary>Ответ</summary>

Числа — `(( a > b ))` или `-gt/-lt/-eq`; строки — `==`, `!=`, `-z`, `-n`.

</details>

**3.** Как правильно прочитать файл построчно?

<details><summary>Ответ</summary>

`while IFS= read -r line; do … done < файл`.

</details>

**4.** Почему нельзя парсить вывод `ls`?

<details><summary>Ответ</summary>

Вывод `ls` — текст: имена с пробелами и спецсимволами разваливаются при word splitting.
Нужен глоб или `find -print0`.

</details>

**5.** Что такое subshell и когда он создаётся?

<details><summary>Ответ</summary>

Дочерний shell: создаётся пайпом, `( … )`, подстановкой команд, фоновым запуском.
Изменения переменных в нём не видны родителю.

</details>

**6.** Как функция возвращает значение?

<details><summary>Ответ</summary>

Кодом — `return N` (0-255); данными — печатью в stdout и захватом `$(...)`.

</details>

**7.** Зачем нужен `local`?

<details><summary>Ответ</summary>

Чтобы переменные функции не затирали одноимённые переменные вызывающего кода.

</details>

**8.** Как объявить массив и перебрать его элементы?

<details><summary>Ответ</summary>

`arr=(a b c)`; `for x in "${arr[@]}"; do …; done`; длина — `${#arr[@]}`.

</details>

**9.** Как сделать ретрай команды с задержкой?

<details><summary>Ответ</summary>

Цикл `until cmd; do sleep $delay; delay=$((delay*2)); done` с ограничением по числу попыток.

</details>

**10.** Как написать скрипт с интерфейсом start/stop/restart?

<details><summary>Ответ</summary>

Через `case "$1" in start) … ;; stop) … ;; *) usage; exit 2 ;; esac`.

</details>

---

## 🎯 Чек-лист

- [ ] Использую `[[ ]]` для строк/файлов и `(( ))` для чисел
- [ ] Обхожу файлы глобом или `find -print0`, а не `$(ls)`
- [ ] Читаю файлы через `while IFS= read -r`
- [ ] Знаю про subshell в пайпе и умею обойти его через `< <(cmd)`
- [ ] Ставлю `ssh -n` в циклах
- [ ] Пишу функции с `local`, возвращаю данные через stdout
- [ ] Умею индексные и ассоциативные массивы, помню про `"${arr[@]}"`
- [ ] Написал `healthcheck.sh` с функциями, массивами и кодами выхода
- [ ] Помню, что в alpine/dash массивов и `[[ ]]` нет
