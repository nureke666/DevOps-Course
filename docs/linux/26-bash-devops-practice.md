---
title: "26. Bash в DevOps: боевые паттерны"
description: "entrypoint для контейнера, wait-for, curl+jq, ретраи с backoff, параллельность — конспект и задачи"
---

# 26. Bash в DevOps — боевые паттерны: CI, Docker, API, параллельность

> Конспект №4 (финальный) модуля bash. Предыдущий: [25. Надёжный bash-скрипт](/linux/25-bash-robust)
> **После темы ты умеешь:** писать entrypoint для контейнера, ждать готовности зависимостей,
> ходить в API с ретраями, запускать задачи параллельно и понимать, когда bash пора бросать.

---

## 🗺️ Схема: где в DevOps живёт bash

```text:no-line-numbers
   ┌──────────────┐   entrypoint.sh, healthcheck, wait-for-db
   │   Docker     │   ← sh, а не bash! (alpine)
   ├──────────────┤
   │   CI/CD      │   каждый script: в .gitlab-ci.yml / Jenkinsfile — это bash
   ├──────────────┤
   │  Kubernetes  │   initContainer, lifecycle hooks, exec-пробы, kubectl-обёртки
   ├──────────────┤
   │   Ansible    │   модуль shell/command — крайнее средство, но встречается всегда
   ├──────────────┤
   │ cron/systemd │   бэкапы, ротации, выгрузки, health-check, отчёты
   ├──────────────┤
   │   Runbook    │   «что делать, когда упало» — обычно набор скриптов
   └──────────────┘
```

---

## 1. Ожидание готовности зависимости (wait-for)

Самая частая задача в контейнерах и CI: приложение стартует раньше БД и падает.

```bash
wait_for_port() {
  local host="$1" port="$2" timeout="${3:-60}" waited=0
  until (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; do    # bash умеет TCP сам!
    (( waited >= timeout )) && { echo "таймаут ожидания $host:$port" >&2; return 1; }
    sleep 1; (( waited++ ))
  done
  exec 3<&-; exec 3>&-
  echo "$host:$port доступен за ${waited}s"
}

wait_for_http() {
  local url="$1" timeout="${2:-60}" waited=0
  until curl -sf --max-time 2 "$url" >/dev/null; do
    (( waited >= timeout )) && { echo "таймаут $url" >&2; return 1; }
    sleep 2; (( waited += 2 ))
  done
}

wait_for_port db 5432 30 || exit 1
wait_for_http http://localhost:8080/health 60 || exit 1
```

⚠️ `/dev/tcp/host/port` — фича bash, в `sh`/alpine её нет: там `nc -z host port`.

---

## 2. Работа с HTTP API: curl + jq

```bash
# Обязательные флаги curl в скриптах
curl --silent --show-error --fail --location \
     --max-time 10 --retry 3 --retry-delay 2 --retry-connrefused \
     -H "Authorization: Bearer $TOKEN" \
     "https://api.example.com/v1/apps"
```

| Флаг | Зачем |
|------|-------|
| `-s` / `--silent` | Убрать прогресс-бар (иначе он мусорит в логах CI) |
| `-S` / `--show-error` | Но ошибки всё же показывать |
| `-f` / `--fail` | **Вернуть ненулевой код при HTTP 4xx/5xx** ← без него скрипт «успешен» на 500 |
| `--fail-with-body` | То же, но с телом ответа (curl 7.76+) — видно, что сказал сервер |
| `-L` | Идти за редиректами |
| `--max-time`, `--connect-timeout` | Скрипт не висит вечно |
| `--retry N --retry-delay` | Встроенный ретрай на сетевых ошибках |

```bash
# Разбор ответа
version=$(curl -sf "$API/status" | jq -r '.version')
jq -e '.status == "ok"' <<<"$response" >/dev/null || die "сервис не готов"   # -e даёт код выхода

# Код ответа отдельно от тела
code=$(curl -s -o /tmp/body.json -w '%{http_code}' "$API/deploy" -X POST -d @payload.json)
[[ $code == 2* ]] || die "API вернул $code: $(cat /tmp/body.json)"

# Генерация JSON — только через jq, не конкатенацией строк!
jq -n --arg env "$ENVIRONMENT" --arg ver "$VERSION" \
   '{environment:$env, version:$ver, ts:now|todate}' > payload.json
```

⚠️ Собирать JSON руками (`"{\"name\": \"$name\"}"`) — гарантированная поломка на кавычках,
переводах строк и юникоде. `jq -n --arg` экранирует всё сам.

---

## 3. Ретрай с экспоненциальной задержкой

```bash
retry() {
  local max="$1" delay="${2:-2}"; shift 2
  local attempt=1
  until "$@"; do
    (( attempt >= max )) && { echo "провал после $max попыток: $*" >&2; return 1; }
    echo "попытка $attempt/$max не удалась, жду ${delay}s" >&2
    sleep "$delay"; delay=$(( delay * 2 )); (( attempt++ ))
  done
}

retry 5 2 curl -sf "$API/health"
retry 3 5 kubectl rollout status deploy/app --timeout=60s
```

Ретраить можно **только идемпотентные** операции: `GET`, `kubectl apply`, `rsync`.
Повторять «создать заказ» или `POST` без ключа идемпотентности — способ сделать дубли.

---

## 4. Скрипты в Docker

```dockerfile
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["app", "--serve"]
```

```bash
#!/bin/sh
# ⚠️ в alpine это busybox sh: без [[ ]], массивов и /dev/tcp
set -eu

: "${DB_HOST:?DB_HOST обязателен}"

# 1. Подставить конфиг из переменных окружения
envsubst < /etc/app/config.tpl > /etc/app/config.yaml

# 2. Дождаться зависимости
i=0
while ! nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
  i=$((i+1)); [ "$i" -gt 30 ] && { echo "БД недоступна" >&2; exit 1; }
  sleep 1
done

# 3. Миграции (идемпотентно)
app migrate --if-needed

# 4. ⭐ Передать управление приложению, СТАВ процессом PID 1
exec "$@"
```

| Правило | Почему |
|---------|--------|
| `exec "$@"` в конце entrypoint | Иначе PID 1 — скрипт, и приложение **не получит SIGTERM** от `docker stop`: контейнер будет убиваться через 10 с по SIGKILL |
| `#!/bin/sh` + `set -eu` в alpine | Bash там не установлен; `pipefail` в busybox sh может отсутствовать |
| Не `bash -c "..."` в CMD | Лишний процесс-обёртка между init и приложением |
| `tini`/`dumb-init` | Если приложение плодит потомков и не жнёт зомби |

⭐ Связь с темой 07 (сигналы) и 13 (systemd): и там, и там проблема одна — кто получит SIGTERM.

---

## 5. Скрипты в CI

```yaml
# .gitlab-ci.yml
deploy:
  script:
    - set -euo pipefail           # ← каждый job: shell новый, настройки не наследуются
    - ./scripts/deploy.sh --env "$CI_ENVIRONMENT_NAME"
```

| Практика | Смысл |
|----------|-------|
| Логику — в файл `scripts/deploy.sh`, а не в YAML | Тестируется локально, проходит shellcheck, видно в diff |
| `set -euo pipefail` в каждом job | Иначе упавший шаг не завалит pipeline |
| Секреты — только через переменные CI | Никогда в коде и в `echo` |
| `echo "::add-mask::"` / masked variables | Маскирование в логах |
| Артефакты и коды выхода | Пайплайн реагирует именно на код |
| Никаких `git commit` из джобы без нужды | Рекурсивные пайплайны — классическая авария |

```bash
# Определить, где выполняемся (частая потребность)
if [[ -n ${CI:-} ]]; then log "режим CI: без интерактива"; else log "локальный запуск"; fi
```

---

## 6. Параллельность

```bash
# 1. Фон + wait — просто и наглядно
for host in "${hosts[@]}"; do
  ssh -n "$host" 'uptime' > "/tmp/out.$host" 2>&1 &
done
wait                                   # дождаться всех
for host in "${hosts[@]}"; do echo "== $host"; cat "/tmp/out.$host"; done

# 2. Собрать коды выхода
pids=(); for h in "${hosts[@]}"; do ssh -n "$h" true & pids+=("$!"); done
rc=0; for p in "${pids[@]}"; do wait "$p" || rc=1; done

# 3. xargs -P — ограничение параллелизма (лучший вариант для больших списков)
printf '%s\n' "${hosts[@]}" | xargs -P 8 -I{} -r ssh -n {} 'uptime'
find . -name '*.log' -print0 | xargs -0 -P 4 -n 1 gzip

# 4. Таймаут на команду
timeout 30 ./slow_task.sh || echo "не уложился в 30 секунд"
```

⚠️ Параллельные процессы пишут в один файл вперемешку — собирай вывод в отдельные файлы
или используй `flock` на запись. И не ставь `-P 100` на прод-кластер: положишь сеть или API.

---

## 7. Типовые скрипты, которые ты напишешь на первой работе

```bash
# Освободить место: удалить логи старше 14 дней и пересжать старые
find /var/log -name '*.log' -mtime +14 -delete
find /var/log -name '*.log.1' -exec gzip -f {} +

# Топ-10 IP по 5xx за сегодня (темы 03-04)
awk '$9 ~ /^5/ {print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head

# Выгрузка метрики для Prometheus node_exporter (textfile collector)
printf 'app_backup_last_success_timestamp %s\n' "$(date +%s)" \
  > /var/lib/node_exporter/textfile/backup.prom.$$ && \
  mv /var/lib/node_exporter/textfile/backup.prom.$$ /var/lib/node_exporter/textfile/backup.prom

# Проверка срока действия TLS-сертификата
days=$(( ( $(date -d "$(openssl s_client -connect example.com:443 </dev/null 2>/dev/null \
        | openssl x509 -noout -enddate | cut -d= -f2)" +%s) - $(date +%s) ) / 86400 ))
(( days < 14 )) && echo "CRITICAL: сертификат истекает через $days дней"

# Уведомление в чат при аварии
curl -sf -X POST -H 'Content-Type: application/json' \
  -d "$(jq -n --arg t "Бэкап упал на $(hostname)" '{text:$t}')" "$WEBHOOK_URL" >/dev/null
```

---

## 8. Стиль и ревью — чек-лист чужого (и своего) скрипта

- [ ] Shebang, `set -euo pipefail`, комментарий-заголовок «что делает и как запускать»
- [ ] Все переменные в кавычках, константы `readonly`, переменные функций `local`
- [ ] Нет `$(ls)`, нет `eval`, нет `curl | bash`
- [ ] Есть `usage()`, `--help`, осмысленные коды выхода
- [ ] Разрушающие операции: `--dry-run`, `${var:?}`, `--` перед аргументами
- [ ] `trap` для уборки, `mktemp` для временных файлов, `flock` от параллельного запуска
- [ ] Логи с метками времени, ошибки в stderr, секретов в логах нет
- [ ] Идемпотентность: три запуска подряд дают тот же результат
- [ ] `shellcheck` чист
- [ ] Скрипт лежит в git, а не только на сервере ⭐

---

## 9. Когда bash пора бросать

| Сигнал | Что брать вместо |
|--------|------------------|
| Скрипт перевалил за ~200-300 строк | Python |
| Нужны структуры данных, вложенный JSON, классы | Python |
| Много арифметики с дробями, дат, часовых поясов | Python |
| Нужны тесты, повторное использование, библиотеки | Python |
| Скрипт настраивает сервер (пакеты, конфиги, юзеры) | Ansible |
| Скрипт создаёт инфраструктуру (ВМ, сети, диски) | Terraform |
| Скрипт деплоит в кластер | Helm / ArgoCD |
| Скрипт «оркестрирует» другие скрипты по расписанию | systemd-таймеры, CI, Airflow |

Но: bash остаётся лучшим выбором для «склейки» готовых утилит, коротких обёрток,
entrypoint'ов и одноразовой автоматизации. Знать его надо именно для этого.

---

## 💼 Как это в DevOps

- Умение прочитать чужой `entrypoint.sh` и понять, почему контейнер не останавливается —
  типичная задача первой недели на работе.
- Половина «магии» CI — это bash в YAML. Кто понимает кавычки и коды выхода, чинит пайплайны быстро.
- Ретраи и таймауты в скриптах — то, что отличает стабильный пайплайн от «перезапусти, обычно проходит».
- Скрипты в git + shellcheck в pre-commit — то, что ревьюеры проверяют в первую очередь.

---

## 🧪 Мини-лаба

```bash
vagrant ssh
mkdir -p ~/lab26 && cd ~/lab26
sudo apt-get install -y jq netcat-openbsd >/dev/null

# 1. Bash умеет TCP сам
(exec 3<>/dev/tcp/127.0.0.1/22) && echo "порт 22 открыт"; exec 3<&- 2>/dev/null
(exec 3<>/dev/tcp/127.0.0.1/9999) 2>/dev/null || echo "порт 9999 закрыт"

# 2. wait-for
cat > waitfor.sh <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
wait_for_port() {
  local host="$1" port="$2" timeout="${3:-10}" waited=0
  until (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; do
    (( waited >= timeout )) && { echo "таймаут $host:$port" >&2; return 1; }
    sleep 1; (( waited++ ))
  done
  echo "$host:$port готов за ${waited}s"
}
wait_for_port 127.0.0.1 22 5
wait_for_port 127.0.0.1 9999 3 || echo "как и ожидалось: недоступен"
EOS
chmod +x waitfor.sh && ./waitfor.sh

# 3. Локальный HTTP-сервер и curl с правильными флагами
python3 -m http.server 8080 >/dev/null 2>&1 &
SRV=$!; sleep 1
curl -sf http://127.0.0.1:8080/ >/dev/null && echo "200 OK"
curl -sf http://127.0.0.1:8080/нет 2>/dev/null || echo "404 → curl -f вернул $?"
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/нет); echo "код: $code"
kill "$SRV"

# 4. jq: генерация и разбор JSON
jq -n --arg env prod --arg ver 1.4.2 '{environment:$env, version:$ver}' | tee payload.json
jq -r '.version' payload.json
jq -e '.environment == "prod"' payload.json >/dev/null && echo "окружение верное"
name='с "кавычками" и \обратными'
jq -n --arg n "$name" '{name:$n}'          # корректный JSON без ручного экранирования

# 5. Ретрай с экспоненциальной задержкой
cat > retry.sh <<'EOS'
#!/usr/bin/env bash
set -uo pipefail
retry() {
  local max="$1" delay="${2:-1}"; shift 2
  local n=1
  until "$@"; do
    (( n >= max )) && { echo "провал после $max попыток" >&2; return 1; }
    echo "попытка $n не удалась, жду ${delay}s" >&2
    sleep "$delay"; delay=$(( delay * 2 )); (( n++ ))
  done
  echo "успех с попытки $n"
}
retry 3 1 curl -sf --max-time 1 http://127.0.0.1:9999/ ; echo "код: $?"
retry 3 1 true
EOS
chmod +x retry.sh && ./retry.sh

# 6. Параллельность и её эффект
time bash -c 'for i in 1 2 3 4; do sleep 1; done'                    # ~4 секунды
time bash -c 'for i in 1 2 3 4; do sleep 1 & done; wait'             # ~1 секунда
printf '%s\n' 1 2 3 4 5 6 7 8 | xargs -P 4 -I{} sh -c 'sleep 1; echo "готово {}"'

# 7. Таймаут
timeout 2 sleep 10; echo "код таймаута: $?"      # 124

# 8. Entrypoint и PID 1 — увидеть разницу (если есть docker из блока Docker)
cat > entrypoint.sh <<'EOS'
#!/bin/sh
set -eu
echo "entrypoint: подготовка конфига"
exec "$@"          # попробуй убрать exec и сравнить поведение docker stop
EOS
chmod +x entrypoint.sh
# docker run --rm -v "$PWD/entrypoint.sh:/e.sh" alpine /e.sh sleep 60
# в другом терминале: docker stop <id> — с exec контейнер остановится мгновенно

# 9. Метрика для node_exporter (textfile collector)
mkdir -p ./textfile
printf 'app_backup_last_success_timestamp %s\n' "$(date +%s)" > ./textfile/backup.prom.tmp
mv ./textfile/backup.prom.tmp ./textfile/backup.prom      # атомарная замена!
cat ./textfile/backup.prom

# 10. shellcheck по всем скриптам модуля
shellcheck ./*.sh || true

# 11. Уборка
cd ~ && rm -rf ~/lab26
```

---

## 📌 Шпаргалка

| Конструкция | Смысл |
|-------------|-------|
| `(exec 3<>/dev/tcp/h/p)` | Проверка TCP-порта средствами bash |
| `nc -z host port` | То же в sh/alpine |
| `curl -sSfL --max-time N --retry N` | Правильный curl в скрипте |
| `curl -o body -w '%{http_code}'` | Отдельно код ответа и тело |
| `jq -r '.field'` / `jq -e` | Разбор JSON / код выхода по условию |
| `jq -n --arg k "$v" '{k:$k}'` | Безопасная генерация JSON |
| `retry N delay cmd…` | Ретрай с экспоненциальной задержкой |
| `timeout 30 cmd` | Ограничение времени (код 124 при таймауте) |
| `cmd &` … `wait` | Параллельный запуск и ожидание |
| `xargs -P N -I{}` | Параллельность с ограничением |
| `exec "$@"` | ⭐ Финал entrypoint: приложение становится PID 1 |
| `envsubst < tpl > conf` | Подстановка переменных окружения в конфиг |
| `set -euo pipefail` в каждом CI-job | Пайплайн видит ошибки |
| `mv tmp final` | Атомарная публикация файла/метрики |

---

## 🧠 Что запомнить

1. `exec "$@"` в конце entrypoint — иначе контейнер не реагирует на `docker stop`.
2. В alpine нет bash: `#!/bin/sh`, без `[[ ]]`, массивов и `/dev/tcp`.
3. `curl` без `-f` считает HTTP 500 успехом; без `--max-time` — висит вечно.
4. JSON собирают `jq -n --arg`, а не конкатенацией строк.
5. Ретраить можно только идемпотентные операции; всегда с ограничением попыток и таймаутом.
6. `set -euo pipefail` нужен в **каждом** job CI — окружение между шагами не наследуется.
7. Параллельность: `& + wait` для единиц задач, `xargs -P` для десятков; вывод — в разные файлы.
8. Скрипты живут в git, проходят shellcheck и ревью — как обычный код.
9. Когда скрипт перерос 200-300 строк или ему нужны структуры данных — это Python/Ansible.
10. Bash — клей между утилитами. Его сила в простоте, и как только простота кончилась,
    правильный ответ — сменить инструмент.

---

## 🏁 Модуль bash пройден

Дальше по плану: закрыть блок — [27. Практика: лабы](/linux/27-practice-labs)
(итоговый стенд и бэкап-скрипт по таймеру) и [28. Вопросы с собеседований](/linux/28-interview). Потом следующие блоки роадмапа —
Сети → Docker → CI/CD → Ansible → Kubernetes → Остальное.
Всё, что там будет — запускается bash-скриптами, которые ты теперь умеешь писать.

---

## Задачи

> `vagrant snapshot save before_26 && vagrant ssh`
> ⭐ Финальные задания модуля: блок C — это готовые куски портфолио, кладите их в git.

---

### Блок A. Теория

**A1.** Где в DevOps-инфраструктуре встречаются bash-скрипты? Назови минимум 6 мест.

<details><summary>Ответ</summary>

Docker (entrypoint, healthcheck, wrapper), CI/CD (script в job), Kubernetes
(initContainer, lifecycle hooks, exec-пробы), Ansible (модули shell/command), cron и
systemd-таймеры (бэкапы, отчёты, ротации), runbook'и и утилиты эксплуатации, Makefile-цели,
git-хуки.

</details>

**A2.** Почему entrypoint заканчивается `exec "$@"`? Что сломается без `exec`?

<details><summary>Ответ</summary>

`exec` заменяет процесс скрипта процессом приложения, и приложение становится PID 1.
Без `exec` PID 1 — это shell, который обычно не пересылает сигналы потомку: `docker stop`
отправит SIGTERM shell'у, приложение его не получит и через `--time` (по умолчанию 10 с)
будет убито SIGKILL — без graceful shutdown, с оборванными соединениями.

</details>

**A3.** Почему скрипт с `[[ ]]` и массивами падает в alpine-образе? Два способа решения.

<details><summary>Ответ</summary>

В alpine `/bin/sh` — busybox ash, а bash не установлен: `[[ ]]`, массивы, `declare -A`,
`/dev/tcp` не поддерживаются. Решения: `apk add --no-cache bash` и shebang `#!/usr/bin/env bash`,
либо переписать скрипт на POSIX sh (`[ ]`, `case`, `nc -z`).

</details>

**A4.** Какие флаги `curl` обязательны в скрипте и что делает каждый?

<details><summary>Ответ</summary>

`-s` (без прогресс-бара), `-S` (но ошибки показывать), `-f` (ненулевой код при HTTP-ошибке),
`-L` (следовать редиректам), `--max-time` и `--connect-timeout` (не висеть вечно),
`--retry`/`--retry-delay` (сетевые ретраи). Для отладки — `--fail-with-body`.

</details>

**A5.** Что произойдёт, если вызвать `curl` без `-f` и сервер вернёт 500?

<details><summary>Ответ</summary>

Без `-f` curl вернёт 0, а в stdout попадёт HTML/JSON страницы ошибки. Скрипт решит,
что всё хорошо, и продолжит работу с мусором вместо данных.

</details>

**A6.** Почему JSON нельзя собирать конкатенацией строк? Как правильно?

<details><summary>Ответ</summary>

Значения могут содержать кавычки, обратные слэши, переводы строк, юникод — при
конкатенации получится невалидный JSON или инъекция. Правильно: `jq -n --arg name "$name"
'{name:$name}'` (или `--argjson` для чисел/объектов).

</details>

**A7.** Что делает `jq -e` и чем отличается от `jq -r`?

<details><summary>Ответ</summary>

`jq -r` печатает строковое значение без кавычек. `jq -e` задаёт **код выхода** по
результату: 0 — результат истинный, 1 — false/null, что позволяет писать `jq -e '.ok' || die`.

</details>

**A8.** Какие операции можно ретраить, а какие — нет? Приведи по два примера.

<details><summary>Ответ</summary>

Ретраить можно идемпотентное: `GET`, `kubectl apply`, `rsync`, скачивание артефакта,
проверка health. Нельзя: `POST /orders`, «списать деньги», `kubectl delete` c последующим
созданием, увеличение счётчика — без ключа идемпотентности это дубли.

</details>

**A9.** Как проверить доступность TCP-порта средствами bash без внешних утилит?

<details><summary>Ответ</summary>

`(exec 3<>/dev/tcp/host/port) 2>/dev/null` — bash открывает TCP-сокет сам;
код 0 означает, что соединение установлено.

</details>

**A10.** Чем `xargs -P` лучше, чем `&` + `wait`, для списка из 200 хостов?

<details><summary>Ответ</summary>

`&` + `wait` запустит все 200 разом: исчерпание памяти, лимитов ФД, DDoS собственного
API. `xargs -P 10` держит ровно 10 одновременно, поддерживает очередь и корректно завершает
работу; вдобавок `-0` безопасно работает с любыми именами.

</details>

**A11.** Что вернёт `timeout 5 cmd`, если команда не уложилась?

<details><summary>Ответ</summary>

Код 124 (а при `--signal`/`-k` возможны другие). Это стандартный способ отличить
таймаут от обычной ошибки команды.

</details>

**A12.** Зачем в CI писать `set -euo pipefail` в каждом job, а не один раз?

<details><summary>Ответ</summary>

Каждый job (а часто и каждая строка `script:`) выполняется в новом shell: опции,
переменные и текущий каталог не переносятся. Без строгого режима упавшая команда посередине
не завалит job, если последняя строка успешна.

</details>

**A13.** Почему логику пайплайна выносят в файл-скрипт, а не пишут в YAML?

<details><summary>Ответ</summary>

Скрипт в репозитории можно запустить локально, протестировать, прогнать shellcheck,
отревьюить в diff и переиспользовать в другом пайплайне; YAML-«простыня» не тестируется
и плохо читается.

</details>

**A14.** Что такое атомарная публикация файла и зачем `mv tmp final`?

<details><summary>Ответ</summary>

Запись во временный файл в **том же каталоге** и затем `mv` — переименование в пределах
одной ФС атомарно, читатель (node_exporter, nginx, приложение) никогда не увидит
полузаписанный файл.

</details>

**A15.** По каким признакам понятно, что задачу пора переписать с bash на Python или Ansible?

<details><summary>Ответ</summary>

Больше ~200-300 строк; нужны словари/списки объектов, разбор сложного JSON, работа
с датами и дробями; нужны тесты и повторное использование; задача — конфигурирование серверов
(Ansible) или создание инфраструктуры (Terraform).

</details>

---

### Блок B. «Что произойдёт»

```bash
B1.  curl -s http://localhost/notfound; echo $?
B2.  curl -sf http://localhost/notfound; echo $?
B3.  timeout 1 sleep 5; echo $?
B4.  echo '{"a":{"b":[1,2]}}' | jq -r '.a.b[1]'
B5.  echo '{"status":"fail"}' | jq -e '.status=="ok"' >/dev/null; echo $?
B6.  jq -n --arg v 'a"b' '{x:$v}'
B7.  (exec 3<>/dev/tcp/127.0.0.1/22) && echo открыт
B8.  for i in 1 2 3; do sleep 1 & done; wait; echo готово
B9.  printf '%s\n' a b c | xargs -P 3 -I{} echo "[{}]"
B10. time (for i in $(seq 4); do sleep 1; done)
B11. time (for i in $(seq 4); do sleep 1 & done; wait)
B12. docker run --rm alpine sh -c 'echo ${BASH_VERSION:-нет bash}'
```

- **B1.** Тело ошибки (или ничего) и код `0` — curl считает HTTP 404 успешным ответом.
- **B2.** Код `22` — `-f` превращает HTTP-ошибку в ненулевой код.
- **B3.** `124` — таймаут.
- **B4.** `2`.
- **B5.** `1` — условие ложно.
- **B6.** `{"x":"a\"b"}` — jq корректно экранировал кавычку.
- **B7.** `открыт`, если sshd слушает 22-й порт.
- **B8.** `готово` примерно через 1 секунду (три `sleep` параллельно).
- **B9.** Три строки `[a] [b] [c]` в произвольном порядке.
- **B10.** ~4 секунды.
- **B11.** ~1 секунда.
- **B12.** `нет bash` — в alpine bash не установлен.

**B13.** Чем отличается поведение контейнера при `docker stop` для двух entrypoint:
```sh
#!/bin/sh
./app --serve            # вариант 1
exec ./app --serve       # вариант 2
```

<details><summary>Ответ</summary>

Вариант 1: PID 1 — `sh`, он получает SIGTERM от `docker stop`, но не пересылает его
приложению; через 10 с контейнер убивается SIGKILL, приложение завершается аварийно.
Вариант 2: `exec` заменяет shell приложением, оно и есть PID 1, получает SIGTERM
и завершается штатно за миллисекунды.

</details>

---

### Блок C. Практика

#### C1. 🔑 deploy.sh — скрипт деплоя (главное задание)

Напиши скрипт, который «деплоит» приложение (реальные команды можно заменить на `echo`,
но структура должна быть боевой):

1. опции `--env dev|stage|prod`, `--version X.Y.Z`, `--dry-run`, `--help`;
2. `set -euo pipefail`, логирование с метками времени;
3. проверки предусловий: есть `curl`, `jq`; задан токен (не аргументом!); окружение есть в словаре;
4. ждёт готовности API (`wait_for_http`, таймаут 60 с);
5. скачивает «артефакт» с ретраями (3 попытки, экспоненциальная задержка);
6. проверяет контрольную сумму;
7. атомарно переключает симлинк `current → releases/<version>`;
8. health-check после деплоя; при провале — автоматический откат на предыдущий релиз;
9. уведомление в «чат» (вывести curl-команду через dry-run);
10. коды выхода: 0 / 1 / 2 / 3, `shellcheck` чист.

**Критерии приёмки:** `--dry-run` ничего не меняет; повторный запуск той же версии
идемпотентен; при падении health-check симлинк возвращается на предыдущий релиз.

<details><summary>Ответ</summary>

Каркас (сокращённо, но со всеми ключевыми элементами):
```bash
#!/usr/bin/env bash
set -euo pipefail
readonly SCRIPT_NAME="${0##*/}"
declare -A API=([dev]=https://dev.api [stage]=https://stage.api [prod]=https://api)
env=""; version=""; dry_run=0
readonly RELEASES=/opt/app/releases CURRENT=/opt/app/current

log()  { printf '%s [INFO]  %s\n' "$(date '+%F %T')" "$*"; }
error(){ printf '%s [ERROR] %s\n' "$(date '+%F %T')" "$*" >&2; }
die()  { error "$*"; exit "${2:-1}"; }
run()  { (( dry_run )) && printf '[dry-run] %s\n' "$*" || "$@"; }
usage(){ echo "usage: $SCRIPT_NAME --env <dev|stage|prod> --version <x.y.z> [--dry-run]"; }

retry() { local max="$1" d="$2"; shift 2; local n=1
  until "$@"; do (( n >= max )) && return 1
    sleep "$d"; d=$((d*2)); (( n++ )); done; }

wait_for_http() { local url="$1" t="${2:-60}" w=0
  until curl -sf --max-time 2 "$url" >/dev/null; do
    (( w >= t )) && return 1; sleep 2; w=$((w+2)); done; }

health_or_rollback() {
  if wait_for_http "http://localhost:8080/health" 30; then
    log "health-check пройден"
  else
    error "health-check провален — откат на $previous"
    run ln -sfn "$previous" "$CURRENT"
    run systemctl restart app
    exit 1
  fi
}

main() {
  while [[ $# -gt 0 ]]; do case "$1" in
    --env) env="${2:?}"; shift 2 ;;
    --version) version="${2:?}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "неизвестная опция: $1" 2 ;;
  esac; done
  [[ -n $env && -n $version ]] || { usage >&2; exit 2; }
  [[ -v API[$env] ]] || die "неизвестное окружение: $env (есть: ${!API[*]})" 2
  command -v curl >/dev/null && command -v jq >/dev/null || die "нужны curl и jq" 3
  : "${DEPLOY_TOKEN:?токен должен приходить через переменную окружения}"

  previous=$(readlink -f "$CURRENT" 2>/dev/null || echo "")
  if [[ -d "$RELEASES/$version" ]]; then
    log "версия $version уже выкачана — пропускаю скачивание (идемпотентность)"
  else
    retry 3 2 run curl -sSfL --max-time 60 -o "/tmp/app-$version.tgz" \
      "${API[$env]}/artifacts/app-$version.tgz" || die "не смог скачать артефакт"
    run sha256sum -c "/tmp/app-$version.tgz.sha256" || die "контрольная сумма не сошлась"
    run mkdir -p "$RELEASES/$version"
    run tar -xzf "/tmp/app-$version.tgz" -C "$RELEASES/$version"
  fi
  run ln -sfn "$RELEASES/$version" "$CURRENT"      # атомарное переключение
  run systemctl restart app
  (( dry_run )) || health_or_rollback
  log "деплой $version в $env завершён"
}
main "$@"
```

</details>

**C2. entrypoint.sh.** Напиши entrypoint для контейнера: подставляет конфиг из переменных
окружения (`envsubst`), ждёт БД, выполняет миграции, запускает приложение через `exec "$@"`.
Требование: работает в `alpine` (только `sh`). Проверь `docker stop` — контейнер должен
останавливаться меньше чем за секунду.

<details><summary>Ответ</summary>

```sh
#!/bin/sh
set -eu
: "${DB_HOST:?}"; : "${APP_PORT:=8080}"
envsubst < /etc/app/config.tpl > /etc/app/config.yaml
i=0; while ! nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
  i=$((i+1)); [ "$i" -gt 30 ] && { echo "БД недоступна" >&2; exit 1; }; sleep 1
done
app migrate --if-needed
exec "$@"
```

</details>

**C3. wait-for.** Реализуй `wait_for.sh host:port [timeout]` двумя способами — через `/dev/tcp`
и через `nc` — и сравни поведение, когда хост не резолвится, порт закрыт, порт открыт.

<details><summary>Ответ</summary>

Разница: при нерезолвящемся хосте `/dev/tcp` даёт мгновенную ошибку bash, `nc`
может ждать DNS-таймаут; при закрытом порте оба возвращают ошибку сразу; `nc` в busybox
поддерживает `-w` (таймаут), а для `/dev/tcp` таймаут делают через `timeout 2 bash -c '…'`.

</details>

**C4. API-клиент.** Скрипт получает список репозиториев с публичного API (например,
`https://api.github.com/users/torvalds/repos`), и печатает таблицу: имя, звёзды, язык.
Требования: `curl -sSf --max-time`, разбор через `jq`, обработка HTTP-ошибки и пустого ответа,
ретрай при 5xx.

<details><summary>Ответ</summary>

```bash
api="https://api.github.com/users/torvalds/repos?per_page=100"
resp=$(retry 3 2 curl -sSf --max-time 15 -H 'Accept: application/vnd.github+json' "$api") \
  || die "API недоступен"
[[ -n $resp ]] || die "пустой ответ"
jq -r '.[] | [.name, .stargazers_count, (.language // "-")] | @tsv' <<<"$resp" \
  | sort -k2 -rn | head -20 \
  | while IFS=$'\t' read -r name stars lang; do
      printf '%-30s %8s  %s\n' "$name" "$stars" "$lang"
    done
```

</details>

**C5. Параллельная проверка хостов.** Из файла со 100 хостами (можно сгенерировать)
проверить доступность порта 22, не более 10 параллельно, собрать результат в CSV
`host,status,ms`. Сравни время с последовательным вариантом.

<details><summary>Ответ</summary>

```bash
check() {
  local h="$1" start end
  start=$(date +%s%3N)
  if timeout 2 bash -c "exec 3<>/dev/tcp/$h/22" 2>/dev/null; then
    end=$(date +%s%3N); printf '%s,up,%s\n' "$h" "$((end-start))"
  else
    printf '%s,down,\n' "$h"
  fi
}
export -f check
xargs -a hosts.txt -P 10 -I{} bash -c 'check {}' > result.csv
```

</details>

**C6. Метрика в Prometheus.** Скрипт бэкапа пишет в textfile-коллектор node_exporter метрики:
время последнего успеха, размер архива, код выхода. Обязательна атомарная запись через `mv`.
(Связь с блоком Monitoring.)

<details><summary>Ответ</summary>

```bash
TEXTFILE_DIR=/var/lib/node_exporter/textfile
tmp=$(mktemp "$TEXTFILE_DIR/backup.prom.XXXX")
{
  echo "# HELP app_backup_last_success_timestamp Время последнего успешного бэкапа"
  echo "# TYPE app_backup_last_success_timestamp gauge"
  echo "app_backup_last_success_timestamp $(date +%s)"
  echo "app_backup_size_bytes $(stat -c %s "$archive")"
  echo "app_backup_exit_code $rc"
} > "$tmp"
chmod 644 "$tmp"; mv "$tmp" "$TEXTFILE_DIR/backup.prom"
```

</details>

**C7. Проверка TLS-сертификата.** Скрипт принимает список доменов и печатает, сколько дней
осталось до истечения сертификата; `exit 2`, если меньше 14 дней хотя бы у одного.

<details><summary>Ответ</summary>

```bash
rc=0
for host in "$@"; do
  end=$(echo | openssl s_client -connect "$host:443" -servername "$host" 2>/dev/null \
        | openssl x509 -noout -enddate | cut -d= -f2) || { echo "$host: не смог проверить"; rc=2; continue; }
  days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
  printf '%-30s %4s дней\n' "$host" "$days"
  (( days < 14 )) && rc=2
done
exit "$rc"
```

</details>

**C8. Анализ логов.** Скрипт-отчёт по `nginx access.log`: всего запросов, распределение кодов,
топ-10 URL, топ-10 IP, доля 5xx, самый медленный запрос. Вывод — выровненная таблица.
(Использует темы [03](/linux/03-text-fu) и [04](/linux/04-advanced-text-fu).)

<details><summary>Ответ</summary>

Ядро отчёта (детали — в темах 03-04):
```bash
total=$(wc -l < "$LOG")
printf 'Всего запросов: %s\n' "$total"
echo "--- Коды ответа ---"
awk '{print $9}' "$LOG" | sort | uniq -c | sort -rn | awk '{printf "%-6s %8d\n", $2, $1}'
echo "--- Топ-10 URL ---";  awk '{print $7}' "$LOG" | sort | uniq -c | sort -rn | head -10
echo "--- Топ-10 IP  ---";  awk '{print $1}' "$LOG" | sort | uniq -c | sort -rn | head -10
err=$(awk '$9 ~ /^5/' "$LOG" | wc -l)
awk -v e="$err" -v t="$total" 'BEGIN{printf "Доля 5xx: %.2f%%\n", (t?e*100/t:0)}'
```

</details>

**C9. Скрипт в CI.** Напиши `.gitlab-ci.yml` (или `Jenkinsfile`) с тремя стадиями:
`lint` (shellcheck по всем скриптам), `test` (запуск скриптов с `--dry-run`),
`deploy` (ручной запуск `deploy.sh`). Покажи, что упавший shellcheck роняет пайплайн.

<details><summary>Ответ</summary>

```yaml
stages: [lint, test, deploy]
lint:
  stage: lint
  image: koalaman/shellcheck-alpine:stable
  script:
    - shellcheck scripts/*.sh
test:
  stage: test
  image: bash:5
  script:
    - set -euo pipefail
    - ./scripts/deploy.sh --env dev --version 0.0.0 --dry-run
deploy:
  stage: deploy
  when: manual
  script:
    - set -euo pipefail
    - ./scripts/deploy.sh --env prod --version "$CI_COMMIT_TAG"
```

</details>

**C10. Свой мини-runbook.** Собери каталог `scripts/` c `healthcheck.sh`, `backup.sh`,
`deploy.sh`, `lib.sh`, `README.md` (как запускать, какие коды выхода, что делать при ошибке).
Закоммить в git — это первый пункт в портфолио.

<details><summary>Ответ</summary>

`README.md` должен отвечать на три вопроса: как запустить, какие коды выхода
и что делать, когда скрипт вернул ошибку. Это и есть мини-runbook.

</details>

---

### Блок D. Инциденты

**D1.** `docker stop` у контейнера занимает ровно 10 секунд, потом контейнер убивается.
Приложение не успевает закрыть соединения. Причина в entrypoint — какая?

<details><summary>Ответ</summary>

В entrypoint нет `exec`: PID 1 — shell, он не пересылает SIGTERM приложению.
Docker ждёт `--time` (10 с) и шлёт SIGKILL. Починка: `exec "$@"`
(или обработчик сигналов в самом скрипте, или `tini`).

</details>

**D2.** CI-джоба «зелёная», но артефакт не собрался: в логе видно `curl: (22) The requested URL
returned error: 500`, а следующий шаг всё равно выполнился. Две причины.

<details><summary>Ответ</summary>

(1) Нет `set -euo pipefail` — упавшая команда не остановила job.
(2) `curl` без `-f` или его код потерялся в конвейере без `pipefail`.

</details>

**D3.** Скрипт деплоя отработал успешно, но приложение выкатилось со старой версией.
В коде: `VERSION=$(curl -s "$API/latest" | jq -r .version)`. Что могло пойти не так?

<details><summary>Ответ</summary>

`curl -s` без `-f`: при ошибке API `jq` получил HTML/JSON ошибки, `.version` вернул
`null`, и `VERSION` стал строкой `null` (или пустой), а дальше скрипт выкатил «что было».
Нужно `curl -sSf`, проверка `[[ -n $VERSION && $VERSION != null ]]` и `set -o pipefail`.

</details>

**D4.** Скрипт мониторинга отправил в Prometheus «битую» метрику, и графики сломались.
Он писал файл напрямую в `textfile/`. Как правильно?

<details><summary>Ответ</summary>

node_exporter прочитал файл в момент записи. Правильно — писать во временный файл
в том же каталоге и делать `mv` (атомарное переименование).

</details>

**D5.** Параллельный скрипт по 200 хостам положил внутренний DNS и API. Что сделать?

<details><summary>Ответ</summary>

Ограничить параллелизм (`xargs -P 5..10`), добавить таймауты на каждую операцию,
джиттер между запусками (`sleep $((RANDOM % 3))`), кешировать DNS-ответы/использовать IP,
а лучше — перейти на инструмент с встроенным управлением параллелизмом (Ansible `forks`).

</details>

**D6.** Скрипт с `curl` в цикле иногда висит часами. Каких флагов не хватает?

<details><summary>Ответ</summary>

`--max-time` и `--connect-timeout` (плюс `--retry` с `--retry-max-time`).
Без них curl может ждать сколько угодно на «зависшем» соединении.

</details>

**D7.** Скрипт в alpine-контейнере падает с `entrypoint.sh: line 12: syntax error: unexpected "("`.
Что это и как чинить?

<details><summary>Ответ</summary>

Это busybox sh, а в скрипте bash-синтаксис (`declare -A`, `(( ))`, массивы, подстановка
процессов). Либо `apk add bash` + `#!/usr/bin/env bash`, либо переписать на POSIX sh.

</details>

**D8.** Ретрай на `POST /orders` создал 3 дубля заказа. Что было сделано неправильно?

<details><summary>Ответ</summary>

Ретраился неидемпотентный `POST`: сервер успевал создать заказ, но ответ терялся
по таймауту. Правильно — передавать `Idempotency-Key`, ретраить только на сетевых ошибках
до отправки тела, либо проверять существование заказа перед повтором.

</details>

**D9.** JSON-полезная нагрузка с именем `O'Brien` сломала запрос к API. Что в коде?

<details><summary>Ответ</summary>

JSON собирался конкатенацией: апостроф/кавычка сломали строку. Правильно —
`jq -n --arg name "$name" '{name:$name}'`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что делает `exec "$@"` в entrypoint и зачем это нужно?

<details><summary>Ответ</summary>

Заменяет процесс shell процессом приложения — приложение становится PID 1 и получает
сигналы напрямую (graceful shutdown при `docker stop`).

</details>

**2.** Почему скрипт для alpine пишут на `sh`, а не на bash?

<details><summary>Ответ</summary>

В alpine bash не установлен, `/bin/sh` — busybox ash; bash-синтаксис там не работает.

</details>

**3.** Какие флаги curl обязательны в автоматизации?

<details><summary>Ответ</summary>

`-sSf -L --max-time --connect-timeout --retry` (и `--fail-with-body` для отладки).

</details>

**4.** Как сделать ретрай с экспоненциальной задержкой?

<details><summary>Ответ</summary>

Цикл `until cmd; do sleep $d; d=$((d*2)); done` с ограничением числа попыток;
ретраить только идемпотентное.

</details>

**5.** Как проверить доступность порта из скрипта?

<details><summary>Ответ</summary>

`(exec 3<>/dev/tcp/host/port)` в bash или `nc -z host port` в sh.

</details>

**6.** Как запустить 100 задач с ограничением в 10 параллельных?

<details><summary>Ответ</summary>

`xargs -P 10` (или `parallel -j10`); `&`+`wait` не ограничивает параллелизм.

</details>

**7.** Как безопасно сформировать JSON в bash?

<details><summary>Ответ</summary>

`jq -n --arg`/`--argjson` — экранирование делает сам jq.

</details>

**8.** Что такое идемпотентность деплой-скрипта?

<details><summary>Ответ</summary>

Повторный запуск с теми же параметрами не создаёт дублей и не ломает текущее состояние:
версия уже выкачана — пропускаем, симлинк уже верный — ничего не делаем.

</details>

**9.** Как сделать откат, если деплой не прошёл health-check?

<details><summary>Ответ</summary>

Запомнить предыдущий релиз (`readlink current`), после переключения прогнать health-check,
при провале вернуть симлинк и перезапустить сервис, вернуть ненулевой код.

</details>

**10.** Когда bash уже не подходит и что брать вместо него?

<details><summary>Ответ</summary>

Когда нужны структуры данных, тесты, сложный разбор JSON, больше ~200-300 строк —
Python; конфигурирование серверов — Ansible; инфраструктура — Terraform.

</details>

---

### 🎯 Чек-лист

- [ ] Знаю, почему entrypoint заканчивается `exec "$@"`
- [ ] Пишу скрипты для alpine на POSIX sh
- [ ] Использую `curl -sSf --max-time` и проверяю HTTP-код
- [ ] Собираю и разбираю JSON только через `jq`
- [ ] Делаю ретраи с экспоненциальной задержкой и только для идемпотентных операций
- [ ] Ограничиваю параллелизм через `xargs -P`
- [ ] Публикую файлы и метрики атомарно через `mv`
- [ ] Держу скрипты в git, гоняю shellcheck в CI
- [ ] Написал `deploy.sh` с откатом и `entrypoint.sh` для контейнера
- [ ] Понимаю, когда пора переходить на Python/Ansible/Terraform
