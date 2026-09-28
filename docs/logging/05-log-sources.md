---
title: "05. Источники логов"
description: "Откуда берутся логи: journald и файлы Linux, Docker, Kubernetes, nginx, базы, аудит — конспект и задачи"
---

# 05. Источники логов: откуда они вообще берутся

> Роадмап → 7. Остальное → Логи → *«Плюс разобраться с источниками, то есть откуда берутся
> логи: файлы серверов, stdout k8s подов, и тд.»*
>
> **После темы ты умеешь:** найти логи любого компонента на сервере, в докере
> и в Kubernetes, понимать, как они физически хранятся и почему пропадают.

---

## 🗺️ Карта источников

```text:no-line-numbers
 ┌────────────────────────────────────────────────────────────────────────┐
 │ ОС и системные сервисы   → journald / /var/log/*, syslog, auditd        │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Приложения на VM         → файлы /var/log/app/*.log или stdout systemd  │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Docker                   → stdout/stderr → драйвер логов → json-файл    │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Kubernetes               → stdout пода → /var/log/pods/… на ноде ⭐      │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Веб-серверы/прокси       → nginx access/error, ingress-controller       │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Базы и middleware        → PostgreSQL, Redis, Kafka, RabbitMQ           │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Сеть и облако            → балансировщики, VPC flow logs, аудит облака  │
 ├────────────────────────────────────────────────────────────────────────┤
 │ CI/CD и инфраструктура   → GitLab/Jenkins, Terraform, Ansible           │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Linux: файлы и journald

```bash
ls /var/log/
# syslog / messages      общие системные сообщения
# auth.log / secure      аутентификация, sudo, SSH ⭐ для безопасности
# kern.log               ядро
# dmesg                  сообщения загрузки и драйверов (OOM killer тоже здесь!)
# nginx/, postgresql/    логи сервисов

journalctl -u nginx -f                  # логи сервиса в реальном времени
journalctl -u nginx --since "1 hour ago"
journalctl -p err -b                    # только ошибки с момента загрузки
journalctl -k                           # логи ядра
journalctl -u app -o json               # структурный вывод (удобно для сборщиков)
journalctl --disk-usage                 # сколько места занял журнал
```
```ini
# /etc/systemd/journald.conf — важные параметры
[Journal]
Storage=persistent        # ⭐ иначе журнал живёт только до перезагрузки
SystemMaxUse=2G
MaxRetentionSec=1month
```

⭐ Где искать «почему процесс умер»:
```bash
journalctl -k | grep -i -E 'oom|killed process'    # OOM killer
dmesg -T | tail -50
journalctl -u myapp -n 200 --no-pager              # последние строки перед падением
```

---

## 2. Docker: драйверы логирования

```text:no-line-numbers
приложение пишет в stdout/stderr
        │
        ▼
 docker log driver  ──► json-file (по умолчанию)
                    ──► local, journald, syslog, fluentd, gelf, awslogs, none
```
```bash
docker logs -f --tail 100 --since 10m myapp
docker inspect -f '{{.LogPath}}' myapp        # где лежит файл лога
ls -lh /var/lib/docker/containers/<id>/<id>-json.log
docker inspect -f '{{.HostConfig.LogConfig}}' myapp
```
```json
// /etc/docker/daemon.json — обязательная настройка на любом хосте
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "100m", "max-file": "3", "compress": "true" }
}
```
| Драйвер | Когда |
|---------|-------|
| `json-file` | По умолчанию; `docker logs` работает; нужна ротация |
| `local` | Компактнее и быстрее json-file, тоже поддерживает `docker logs` |
| `journald` | Единый журнал системы, удобно на VM |
| `fluentd`/`gelf`/`syslog` | Отправка сразу в конвейер (⚠️ `docker logs` перестаёт работать) |
| `none` | Логи выключены (только если они точно не нужны) |

> ⚠️ Если приложение в контейнере пишет в **файл внутри контейнера**, эти логи
> не попадут ни в `docker logs`, ни к сборщику, и исчезнут вместе с контейнером.
> Стандарт: приложение пишет в stdout/stderr.

---

## 3. Kubernetes: самый частый вопрос на собесе

```text:no-line-numbers
под пишет в stdout/stderr
        │
        ▼  kubelet + container runtime (containerd)
 /var/log/pods/<namespace>_<pod>_<uid>/<container>/0.log        ← реальные файлы
 /var/log/containers/<pod>_<namespace>_<container>-<id>.log     ← симлинки на них ⭐
        │
        ▼  агент DaemonSet'ом (Fluent Bit / Alloy) читает эти файлы
    хранилище (Loki / Elasticsearch)
```

```bash
kubectl logs my-pod                       # текущий контейнер
kubectl logs my-pod -c sidecar            # конкретный контейнер
kubectl logs my-pod --previous            # ⭐ логи упавшего предыдущего контейнера
kubectl logs -f deploy/api --tail=100
kubectl logs -l app=api --max-log-requests=10   # по лейблу со всех подов
kubectl describe pod my-pod               # события: OOMKilled, ImagePullBackOff
kubectl get events --sort-by=.lastTimestamp
```

| Факт | Следствие |
|------|-----------|
| `kubectl logs` читает файл на ноде | Под удалён → логов больше нет ⚠️ |
| Ротация делается kubelet'ом | Хранится ограниченное число файлов |
| `--previous` даёт логи прошлого запуска | Единственный способ увидеть, почему упал |
| Логи узлов: kubelet, containerd | `journalctl -u kubelet` |
| Логи control plane | Поды в `kube-system` или systemd на мастерах |
| События кластера живут ~1 час | Их тоже полезно собирать (kubernetes-event-exporter) |

⭐ Именно поэтому в Kubernetes централизованный сбор логов обязателен: под — эфемерная
сущность, и вместе с ним исчезает вся история.

**Sidecar-подход** (когда приложение не умеет в stdout): рядом с контейнером приложения
ставят контейнер-сборщик, читающий общий `emptyDir`-том. Дороже по ресурсам, применяют
как исключение.

---

## 4. nginx и ingress

```nginx
# структурные access-логи — так их приятно разбирать
log_format json_combined escape=json '{'
  '"time":"$time_iso8601","remote_addr":"$remote_addr","method":"$request_method",'
  '"path":"$uri","status":$status,"bytes":$body_bytes_sent,'
  '"request_time":$request_time,"upstream_time":"$upstream_response_time",'
  '"ua":"$http_user_agent","xff":"$http_x_forwarded_for"}';

access_log /var/log/nginx/access.log json_combined;
error_log  /var/log/nginx/error.log warn;
```
```bash
# в контейнере nginx логи уже идут в stdout/stderr (симлинки на /dev/stdout)
ls -l /var/log/nginx/access.log      # -> /dev/stdout
kubectl logs -n ingress-nginx deploy/ingress-nginx-controller
```
Что смотреть в nginx-логах: `status`, `request_time`, `upstream_response_time`
(время самого приложения), `upstream_addr` (какой бэкенд отвечал), `$http_x_forwarded_for`
(реальный клиент за прокси).

---

## 5. Базы и middleware

| Сервис | Где логи | Что важно |
|--------|----------|-----------|
| PostgreSQL | `/var/log/postgresql/` или stdout в докере | Медленные запросы, блокировки, checkpoint, старт/стоп (см. [04. postgresql.conf](/databases/04-postgresql-conf)) |
| Redis | stdout | Загрузка RDB/AOF, вытеснение, ошибки памяти |
| Kafka | `/opt/kafka/logs/`, stdout | Ребалансы, ISR, ошибки брокеров |
| RabbitMQ | stdout / `/var/log/rabbitmq/` | Очереди, подключения, memory alarm |
| Elasticsearch | stdout / `logs/` | GC, шарды, watermark |

Общее правило: у всех есть уровень логирования и формат — их приводят к JSON и stdout,
где это возможно.

---

## 6. Аудит и безопасность

```bash
# кто заходил и что делал
journalctl -u sshd | grep 'Accepted\|Failed'
grep sudo /var/log/auth.log

# auditd — системный аудит (файлы, вызовы, изменения)
sudo auditctl -w /etc/passwd -p wa -k passwd_changes
sudo ausearch -k passwd_changes
```
| Источник | Зачем |
|----------|-------|
| `auth.log`/`secure`, sshd | Входы, неудачные попытки, sudo |
| auditd | Изменения критичных файлов, выполнение команд |
| Kubernetes audit log | Кто и что делал в API кластера |
| Аудит облака (CloudTrail и аналоги) | Кто создал/удалил ресурс |
| Логи CI/CD | Кто и что задеплоил |

Эти логи хранят дольше остальных (часто год и больше) и отделяют от прикладных
по доступу — их читают безопасность и расследования.

---

## 7. Алгоритм «где искать логи» (рабочая шпаргалка дежурного)

```text:no-line-numbers
Что сломалось?
├── Сервис на VM         → journalctl -u <unit> -n 200 --no-pager
├── Контейнер            → docker logs --tail 200 <name>
├── Под в k8s            → kubectl logs <pod> [--previous]; kubectl describe pod
├── Нода k8s             → journalctl -u kubelet; journalctl -u containerd
├── Процесс убит         → journalctl -k | grep -i oom; dmesg -T
├── Не стартует система  → journalctl -b -p err
├── Веб/прокси           → nginx access/error, ingress-controller
├── База                 → логи БД + pg_stat_activity / аналоги
├── Сеть/доступ          → auth.log, firewall, VPC flow logs
└── Деплой               → логи пайплайна CI/CD + аннотации в Grafana
```

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| Приложение пишет в файл внутри контейнера | Логи исчезают с контейнером | Писать в stdout |
| `Storage=volatile` в journald | Журнал пропадает после перезагрузки | `Storage=persistent` |
| Нет `max-size` у докера | Диск ноды забит логами | `daemon.json` |
| Драйвер `fluentd`/`gelf` | `docker logs` не работает | Понимать компромисс |
| Логи пода смотрят после его удаления | «Логов нет» | Централизованный сбор |
| Забывают `--previous` | Не видно причину падения | `kubectl logs --previous` |
| События k8s не собираются | Через час информации нет | event-exporter |
| Логи nginx текстом | Тяжело разбирать | `log_format` в JSON |
| Аудит-логи в общей куче | Нельзя расследовать инцидент | Отдельный поток и retention |

---

## 💼 Как это в DevOps

- Первое требование к сервису: **stdout + JSON**. Всё остальное (сбор, хранение, поиск)
  девопс закрывает инфраструктурой.
- На VM логи собирают из journald и файлов; в Kubernetes — из `/var/log/containers/*.log`
  агентом-DaemonSet'ом с обогащением метаданными.
- Логи ноды (kubelet, containerd) и события кластера собирают отдельно —
  без них разбор «поды не запускаются» вслепую.
- Аудит-логи выделяют в отдельный поток с длинным retention и ограниченным доступом.
- На собесе почти гарантированный вопрос: *«Откуда берутся логи подов в Kubernetes
  и что с ними происходит при удалении пода?»*

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Логи systemd-сервиса | `journalctl -u nginx -n 200 --no-pager` |
| Следить в реальном времени | `journalctl -u app -f` / `docker logs -f` |
| Только ошибки с загрузки | `journalctl -b -p err` |
| Логи ядра и OOM | `journalctl -k \| grep -i oom`, `dmesg -T` |
| Размер журнала | `journalctl --disk-usage`, `journalctl --vacuum-size=1G` |
| Логи контейнера | `docker logs --tail 200 --since 10m <name>` |
| Где файл лога контейнера | <code v-pre>docker inspect -f '{{.LogPath}}' &lt;name&gt;</code> |
| Логи пода | `kubectl logs <pod> -c <container>` |
| Логи упавшего контейнера | `kubectl logs <pod> --previous` ⭐ |
| Логи по лейблу | `kubectl logs -l app=api --tail=50` |
| Почему под не стартует | `kubectl describe pod <pod>`, `kubectl get events` |
| Логи kubelet | `journalctl -u kubelet -n 200` |
| Где логи подов на ноде | `/var/log/pods/`, `/var/log/containers/` |
| Логи входов на сервер | `grep -E 'Accepted\|Failed' /var/log/auth.log` |
| JSON-логи nginx | `log_format json_combined escape=json '{...}'` |

---

## 🧠 Что запомнить

1. Источники делятся на: ОС и systemd, приложения, контейнеры, поды, прокси, базы,
   сеть/облако, CI/CD, аудит.
2. В Linux основное — journald (`journalctl -u`) и файлы в `/var/log`.
3. `journalctl -k | grep -i oom` и `dmesg -T` отвечают на вопрос «кто убил процесс».
4. Docker пишет stdout контейнера через драйвер логов; по умолчанию json-file,
   и ему обязательно нужна ротация.
5. ⭐ В Kubernetes логи пода — это файлы на ноде (`/var/log/pods`, симлинки
   в `/var/log/containers`); удалили под — логи исчезли.
6. `kubectl logs --previous` — единственный способ увидеть, почему контейнер упал.
7. Приложение должно писать в stdout: файл внутри контейнера не увидит никто.
8. События кластера живут около часа — их тоже собирают.
9. nginx настраивают на JSON-логи; `upstream_response_time` показывает время приложения.
10. Аудит и безопасность — отдельный поток логов с долгим хранением и ограниченным доступом.

---

## Задачи

> Стенд: Linux-машина с docker; для части заданий полезен kind/minikube (из блока Kubernetes).

---

### Блок A. Теория

**A1.** Назови восемь групп источников логов в типовой инфраструктуре.

<details><summary>Ответ</summary>

ОС и systemd, приложения на VM, контейнеры Docker, поды Kubernetes,
веб-серверы и прокси, базы и middleware, сеть и облако, CI/CD, аудит и безопасность.

</details>

**A2.** Чем journald отличается от файлов в `/var/log`?

<details><summary>Ответ</summary>

journald — бинарный индексируемый журнал systemd с метаданными (unit, pid,
приоритет), доступный через `journalctl`. Файлы в `/var/log` — обычные текстовые логи
сервисов; часть из них пишет rsyslog.

</details>

**A3.** Что произойдёт с журналом systemd после перезагрузки при `Storage=volatile`?

<details><summary>Ответ</summary>

Журнал хранится только в памяти и полностью теряется после перезагрузки —
разбирать инцидент, который привёл к ребуту, будет нечем.

</details>

**A4.** Где искать причину, если процесс внезапно убит?

<details><summary>Ответ</summary>

`journalctl -k | grep -i oom`, `dmesg -T`, статус сервиса
(`systemctl status`, код выхода), для контейнеров — `docker inspect` (`OOMKilled: true`),
в k8s — `kubectl describe pod` (Last State: OOMKilled).

</details>

**A5.** Как Docker обрабатывает stdout контейнера? Какие бывают драйверы логов?

<details><summary>Ответ</summary>

Docker перехватывает stdout/stderr контейнера и передаёт драйверу логов.
Драйверы: `json-file` (по умолчанию), `local`, `journald`, `syslog`, `fluentd`,
`gelf`, `awslogs`, `none`.

</details>

**A6.** Почему при драйвере `fluentd` перестаёт работать `docker logs`?

<details><summary>Ответ</summary>

Потому что логи уходят сразу во внешнюю систему и не сохраняются локально
в формате, который умеет читать `docker logs`.

</details>

**A7.** ⭐ Где физически лежат логи подов Kubernetes и что с ними происходит
при удалении пода?

<details><summary>Ответ</summary>

Файлы на ноде: `/var/log/pods/<ns>_<pod>_<uid>/<container>/0.log`.
При удалении пода kubelet удаляет и эти файлы — история пропадает, если её
не собрал агент.

</details>

**A8.** Чем отличаются `/var/log/pods/` и `/var/log/containers/`?

<details><summary>Ответ</summary>

`/var/log/pods/` — реальные файлы, сгруппированные по поду и контейнеру;
`/var/log/containers/` — симлинки с плоскими именами (`pod_ns_container-id.log`),
удобные для чтения агентом.

</details>

**A9.** Что делает `kubectl logs --previous` и когда он незаменим?

<details><summary>Ответ</summary>

Показывает логи предыдущего (упавшего) экземпляра контейнера. Незаменим,
когда контейнер в CrashLoopBackOff: текущий запуск ещё ничего не написал.

</details>

**A10.** Где смотреть, почему под не запускается (не логи приложения)?

<details><summary>Ответ</summary>

`kubectl describe pod` (события, состояние контейнеров, причины) и
`kubectl get events`; для проблем узла — `journalctl -u kubelet`.

</details>

**A11.** Сколько живут события кластера и что с этим делать?

<details><summary>Ответ</summary>

По умолчанию около часа (TTL в etcd). Их собирают отдельным экспортером
(kubernetes-event-exporter) в логовое хранилище.

</details>

**A12.** Почему приложение в контейнере не должно писать логи в файл?

<details><summary>Ответ</summary>

Такие логи не видит ни `docker logs`/`kubectl logs`, ни агент сбора,
и они исчезают вместе с контейнером; плюс раздувают слой/том.

</details>

**A13.** Что показывает `upstream_response_time` в nginx и чем он полезен?

<details><summary>Ответ</summary>

Время ответа апстрима (бэкенда). Позволяет разделить «медленно приложение»
и «медленно прокси/сеть»: сравнивают `request_time` и `upstream_response_time`.

</details>

**A14.** Какие источники относятся к аудиту и почему их хранят дольше?

<details><summary>Ответ</summary>

Логи входов и sudo, auditd, audit log Kubernetes, аудит облака, логи CI/CD.
Хранятся дольше из-за требований безопасности и расследований инцидентов.

</details>

**A15.** Опиши алгоритм «где искать логи» для пяти типовых ситуаций.

<details><summary>Ответ</summary>

Сервис на VM → `journalctl -u`; контейнер → `docker logs`;
под → `kubectl logs [--previous]` и `describe`; нода → `journalctl -u kubelet`;
убитый процесс → `journalctl -k | grep oom` / `dmesg`.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  journalctl -u nginx -n 200 --no-pager
B2.  journalctl -b -p err
B3.  journalctl -k | grep -i -E 'oom|killed process'
B4.  journalctl --disk-usage && journalctl --vacuum-size=1G
B5.  docker logs -f --tail 100 --since 10m myapp
B6.  docker inspect -f '{{.LogPath}}' myapp
B7.  kubectl logs my-pod --previous
B8.  kubectl logs -l app=api --tail=50
B9.  kubectl describe pod my-pod
B10. kubectl get events --sort-by=.lastTimestamp
B11. journalctl -u kubelet -n 200
B12. grep -E 'Accepted|Failed' /var/log/auth.log
```

<details><summary>Ответ</summary>

**B1.** Последние 200 строк логов сервиса без пейджера.
**B2.** Ошибки с момента текущей загрузки.
**B3.** Сообщения ядра об OOM-killer.
**B4.** Размер журнала и его усечение до 1 ГБ.
**B5.** Логи контейнера в реальном времени за последние 10 минут.
**B6.** Путь к файлу логов контейнера на хосте.
**B7.** Логи предыдущего (упавшего) запуска контейнера.
**B8.** Логи всех подов по лейблу.
**B9.** Подробности пода и события — причины, по которым он не стартует.
**B10.** События кластера по времени.
**B11.** Логи kubelet на ноде.
**B12.** Успешные и неудачные входы по SSH.

</details>

Оцени решения:
```text:no-line-numbers
B13. Приложение в контейнере пишет в /app/logs/app.log
B14. daemon.json без log-opts на ноде с 50 контейнерами
B15. Storage=volatile в journald на проде
B16. log-driver: none для всех контейнеров, "логи нам не нужны"
B17. Логи аудита лежат в одном индексе с прикладными, retention 7 дней
B18. nginx пишет access-лог в стандартном combined-формате, разбирают grok'ом
```

<details><summary>Ответ</summary>

**B13.** Логи не видны никому и исчезнут с контейнером.
**B14.** Без ротации логи контейнеров заполнят диск ноды.
**B15.** Журнал не переживёт перезагрузку — потеря данных об инциденте.
**B16.** Полное отключение логов лишает возможности разбирать инциденты;
допустимо разве что для очень шумных вспомогательных контейнеров.
**B17.** Аудит-логи требуют отдельного хранения, доступа и длинного retention.
**B18.** Текстовый формат требует хрупкого grok; JSON проще и надёжнее.

</details>

---

### Блок C. Практика

#### C1. journald
1. Посмотри логи трёх разных сервисов, ограничь по времени и уровню.
2. Проверь `Storage` в `journald.conf`, при необходимости переведи в `persistent`.
3. Посмотри `journalctl --disk-usage` и ограничь размер журнала.

#### C2. 🔑 Кто убил процесс
1. Запусти контейнер с маленьким лимитом памяти и программой, которая её съедает.
2. Поймай OOM: `docker inspect`, `journalctl -k | grep -i oom`, `dmesg -T`.
3. Опиши, какие признаки указывают именно на OOM.

<details><summary>Ответ</summary>

Признаки OOM: `OOMKilled: true` в `docker inspect`, сообщение ядра
`Killed process ... (name) total-vm... anon-rss...`, в k8s — `Last State: Terminated,
Reason: OOMKilled`.

</details>

#### C3. Драйверы логов докера
1. Посмотри текущий драйвер и путь к файлу лога контейнера.
2. Настрой `max-size`/`max-file`, проверь ротацию под нагрузкой логов.
3. Переключи один контейнер на драйвер `journald` и посмотри, что изменилось
   (`docker logs` и `journalctl CONTAINER_NAME=...`).

<details><summary>Ответ</summary>

При драйвере `journald` логи контейнера видны через
`journalctl CONTAINER_NAME=<name>`, а `docker logs` продолжает работать
(journald — один из драйверов, поддерживающих чтение).

</details>

#### C4. Файл внутри контейнера
1. Запусти приложение, пишущее в файл внутри контейнера.
2. Убедись, что `docker logs` пуст.
3. Удали контейнер и объясни, что стало с логами.
4. Переделай на stdout.

#### C5. 🔑 Логи в Kubernetes
1. Подними kind/minikube, задеплой приложение.
2. Посмотри `kubectl logs`, `-c`, `--previous`, `-l`.
3. Зайди на ноду (`docker exec` в узел kind) и найди файлы в `/var/log/pods`
   и симлинки в `/var/log/containers`.
4. Удали под и проверь, что логов больше нет.

<details><summary>Ответ</summary>

В kind зайти на «ноду» можно через `docker exec -it kind-control-plane bash`.

</details>

#### C6. Почему под не стартует
Сломай деплой (неверный образ, нехватка ресурсов, плохая проба) и разбери
через `describe` и `events`, а не через логи приложения.

<details><summary>Ответ</summary>

Типичные причины: `ImagePullBackOff`, `CrashLoopBackOff`, `Insufficient memory`,
проваленный readiness/liveness — всё это видно в `describe`, а не в логах приложения.

</details>

#### C7. nginx в JSON
1. Настрой `log_format` в JSON, перезапусти nginx.
2. Сгенерируй трафик, посмотри логи.
3. Отправь их в Loki/Elasticsearch и найди медленные запросы по `request_time`.

<details><summary>Ответ</summary>

Медленные запросы ищут по `request_time` и сравнивают с `upstream_response_time`.

</details>

#### C8. Логи базы
Включи `log_min_duration_statement` в PostgreSQL, сгенерируй медленный запрос,
найди его в логах и убедись, что он доехал до централизованного хранилища.

#### C9. Аудит
1. Посмотри `auth.log`: успешные и неудачные входы, sudo.
2. Настрой правило auditd на изменение `/etc/passwd`, проверь `ausearch`.
3. Реши, какой retention назначишь этим логам и почему.

<details><summary>Ответ</summary>

Логи аудита обычно хранят от 6 месяцев до нескольких лет в зависимости
от требований.

</details>

#### C10. Свой рунбук «где искать логи»
Составь одностраничную памятку для своей инфраструктуры: компонент → где логи →
какой командой смотреть → куда они уезжают.

---

### Блок D. Инциденты

**D1.** Под перезапустился 10 раз, приложение «ничего не пишет». Где смотреть?

<details><summary>Ответ</summary>

`kubectl logs --previous`, `kubectl describe pod` (Last State, Reason, Exit Code),
события, логи kubelet, проверка проб и лимитов памяти.

</details>

**D2.** Логи контейнера пусты, хотя приложение работает. Три гипотезы.

<details><summary>Ответ</summary>

Приложение пишет в файл внутри контейнера; логи уходят в другой драйвер;
приложение буферизует вывод (нет flush / нет `PYTHONUNBUFFERED`);
логирование отключено уровнем.

</details>

**D3.** Диск ноды забит на 100%, `/var/lib/docker` — 80 ГБ логов. Что делать сейчас
и что настроить потом?

<details><summary>Ответ</summary>

Сейчас: найти самые большие файлы (`du -sh /var/lib/docker/containers/*`),
при необходимости `truncate -s 0` для логов конкретного контейнера или пересоздать
контейнер; затем настроить `max-size`/`max-file`, централизованный сбор и алерт на диск.

</details>

**D4.** После перезагрузки сервера нет логов за предыдущие дни. Причина?

<details><summary>Ответ</summary>

`Storage=volatile` в journald (или журнал не сохраняется/усечён по размеру).

</details>

**D5.** Под удалён автоскейлером, а нужно понять, почему он падал. Что спасёт?

<details><summary>Ответ</summary>

Централизованный сбор логов: логи уже в Loki/ES, даже если пода нет.

</details>

**D6.** `kubectl logs` показывает только последние 10 минут. Почему?

<details><summary>Ответ</summary>

Сработала ротация файлов логов kubelet'ом (`containerLogMaxSize`/`Files`),
либо контейнер недавно перезапустился.

</details>

**D7.** Нужно понять, кто удалил Deployment в кластере. Куда смотреть?

<details><summary>Ответ</summary>

Kubernetes audit log (если включён), события кластера, логи CI/CD
и системы контроля версий (GitOps — коммит в репозитории).

</details>

**D8.** В логах nginx все клиенты имеют один IP (адрес балансировщика). Как исправить?

<details><summary>Ответ</summary>

Передавать реальный адрес клиента: `X-Forwarded-For`/`X-Real-IP`,
настроить `set_real_ip_from`/`real_ip_header` в nginx, включить proxy protocol
на балансировщике.

</details>

**D9.** Приложение логирует в stdout, но в Loki попадают только части строк. Гипотезы?

<details><summary>Ответ</summary>

Разрыв длинных строк (лимит длины строки у драйвера/агента), отсутствие
multiline, буферизация приложения, ограничения размера записи в Loki.

</details>

**D10.** Инцидент был вчера, логи уже удалены retention'ом. Как избежать повторения?

<details><summary>Ответ</summary>

Увеличить retention для критичных потоков, снимать «слепки» логов
инцидента в постмортем, настроить архив в объектное хранилище,
делать выгрузку логов при срабатывании critical-алертов.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Откуда берутся логи в Kubernetes?

<details><summary>Ответ</summary>

Приложения пишут в stdout/stderr, runtime складывает это в файлы на ноде
(`/var/log/pods`, симлинки в `/var/log/containers`), агент-DaemonSet читает
и отправляет в хранилище.

</details>

**2.** Что произойдёт с логами при удалении пода?

<details><summary>Ответ</summary>

Файлы удаляются вместе с подом — остаются только те логи, которые успел
собрать агент.

</details>

**3.** Как посмотреть логи упавшего контейнера?

<details><summary>Ответ</summary>

`kubectl logs <pod> --previous` (или в централизованном хранилище).

</details>

**4.** Где логи Docker и как их ротировать?

<details><summary>Ответ</summary>

По умолчанию `json-file` в `/var/lib/docker/containers/<id>/`;
ротация — `max-size`/`max-file` в `daemon.json`.

</details>

**5.** Что такое journald и чем он удобен?

<details><summary>Ответ</summary>

Журнал systemd с метаданными и индексом: удобный фильтр по юниту, времени,
приоритету, вывод в JSON для сборщиков.

</details>

**6.** Как найти причину, если процесс был убит системой?

<details><summary>Ответ</summary>

`journalctl -k`/`dmesg` (OOM killer), `docker inspect` (`OOMKilled`),
`kubectl describe pod` (Last State), код выхода сервиса.

</details>

**7.** Почему приложение должно писать в stdout?

<details><summary>Ответ</summary>

Чтобы логи забирал runtime и агент, чтобы они не терялись с контейнером
и не требовали томов.

</details>

**8.** Где смотреть, если под не стартует?

<details><summary>Ответ</summary>

`kubectl describe pod` и события кластера, затем логи kubelet.

</details>

**9.** Какие логи относятся к аудиту?

<details><summary>Ответ</summary>

Входы и sudo, auditd, audit log Kubernetes, аудит облака, логи CI/CD.

</details>

**10.** Как понять, что запрос долго обрабатывался на бэкенде, а не в прокси?

<details><summary>Ответ</summary>

Сравнить `request_time` и `upstream_response_time` в логах nginx/ingress.

</details>

---

### 🎯 Чек-лист

- [ ] Свободно смотрю логи через `journalctl` с фильтрами
- [ ] Умею найти OOM и причину падения процесса
- [ ] Настроил ротацию логов Docker и знаю про драйверы
- [ ] ⭐ Знаю, где лежат логи подов и что будет при их удалении
- [ ] Пользуюсь `kubectl logs --previous` и `describe` при падениях
- [ ] Понимаю, почему приложение должно писать в stdout
- [ ] Настроил JSON-логи nginx и умею читать `upstream_response_time`
- [ ] Собираю события кластера, а не только логи
- [ ] Выделил аудит-логи в отдельный поток
- [ ] Есть своя памятка «где искать логи»
