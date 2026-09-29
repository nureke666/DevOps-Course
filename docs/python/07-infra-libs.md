---
title: "07. Инфраструктурные библиотеки: SSH, Docker, Kubernetes, S3, Prometheus"
description: "Блок → Python для DevOps → тема 7 из 8."
---

# 07. Инфраструктурные библиотеки: SSH, Docker, Kubernetes, S3, Prometheus

> Блок → **Python для DevOps** → тема 7 из 8.
> Смежные блоки: [Docker](/docker/03-dockerfile), [Kubernetes](/kubernetes/),
> [S3](/cloud/04-s3-storage), [exporter'ы](/monitoring/04-exporters).
>
> **После темы ты умеешь:** выполнять команды на пачке хостов по SSH (paramiko/fabric), управлять
> контейнерами через docker SDK, читать состояние кластера официальным kubernetes-клиентом
> (поды, рестарты, события), работать с S3-совместимым хранилищем через boto3 (на MinIO)
> и отдавать свои метрики через `prometheus_client` — exporter'ом и через textfile collector.

---

## 🗺️ Карта темы

```text
                                Python-скрипт
   ┌───────────────┬───────────────┼────────────────┬──────────────────┐
 paramiko/fabric  docker         kubernetes        boto3              prometheus_client
 SSH → хосты      Docker API     API-сервер k8s    S3 API             /metrics или .prom
 (порт 22)        (docker.sock)  (kubeconfig или   (AWS, MinIO,       (Prometheus забирает
                                 ServiceAccount)   Ceph, облака)      сам — pull)
      │               │                │                │                  │
 аналог в CLI:   docker ...       kubectl ...       aws s3 / mc        node_exporter
 ssh, pssh                                                             textfile collector
```text
**CLI через subprocess или SDK?** Если в шелле задача решалась бы через `... -o json | jq` — бери SDK:
получаешь объекты вместо текста, типизированные исключения и не зависишь от формата вывода утилиты.
Разовая простая команда (`kubectl rollout status`) — можно и через `subprocess`.

---

## 1. SSH: paramiko и fabric

**paramiko** — низкоуровневый SSH-клиент:

```python
import paramiko

def run_remote(host: str, command: str, user: str = "deploy", timeout: int = 30) -> tuple[int, str, str]:
    with paramiko.SSHClient() as client:
        client.load_system_host_keys()                          # ~/.ssh/known_hosts
        client.set_missing_host_key_policy(paramiko.RejectPolicy())   # неизвестный хост → отказ
        client.connect(host, username=user, timeout=10)         # ключи: ssh-agent и ~/.ssh/id_*
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode()                            # ⭐ сначала прочитать вывод,
        err = stderr.read().decode()
        code = stdout.channel.recv_exit_status()                #    потом код выхода
        return code, out, err
```text
Пачка хостов параллельно:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

hosts = ["web1", "web2", "db1"]
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = {pool.submit(run_remote, h, "df -h / | tail -1"): h for h in hosts}
    for fut in as_completed(futures):
        host = futures[fut]
        try:
            code, out, err = fut.result()
            print(f"{host:&lt;8} {'✅' if code == 0 else '❌'} {out.strip() or err.strip()}")
        except (paramiko.SSHException, OSError) as e:          # auth, таймаут, отказ соединения
            print(f"{host:<8} ❌ нет подключения: {e}")
```text
⚠️ `AutoAddPolicy()` — это `StrictHostKeyChecking=no`: подмену сервера не заметишь.
⚠️ paramiko **не читает** `~/.ssh/config` (алиасы, `ProxyJump`, порты) — это делает fabric.

**fabric** — удобная обёртка над paramiko: читает `~/.ssh/config`, умеет sudo, put/get, группы хостов.

```python
from fabric import Connection, ThreadingGroup
from fabric.exceptions import GroupException

c = Connection("web1", user="deploy", connect_timeout=10)
r = c.run("systemctl is-active nginx", hide=True, warn=True)   # warn=True: не бросать на коде ≠ 0
print(r.exited, r.stdout.strip())
c.put("nginx.conf", "/tmp/nginx.conf")
c.sudo("nginx -t", hide=True)                  # нужен sudo без пароля или настройка пароля
c.sudo("systemctl reload nginx", hide=True)    # ⚠️ не «a && b» в одном sudo: под sudo пойдёт только a

group = ThreadingGroup("web1", "web2", "web3", user="deploy", connect_timeout=10)
try:
    results = group.run("uptime", hide=True, warn=True)
except GroupException as e:
    results = e.result                                          # часть хостов недоступна
for conn, res in results.items():
    print(f"{conn.host}: {res if isinstance(res, Exception) else res.stdout.strip()}")
```text&gt; Команды на пачке хостов — да. Настройка серверов (пакеты, конфиги, идемпотентность) — это Ansible,
> а не цикл на fabric.

---

## 2. Docker SDK (`docker`)

```python
import docker
from docker.errors import DockerException, NotFound

client = docker.from_env()             # DOCKER_HOST или /var/run/docker.sock; нет демона → DockerException

for c in client.containers.list(all=True):
    print(f"{c.short_id} {c.name:&lt;25} {c.status:<10} {c.attrs['Config']['Image']}")

web = client.containers.run(
    "nginx:alpine", name="py-web", detach=True,
    ports={"80/tcp": 8081}, labels={"owner": "py-lab"},
    restart_policy={"Name": "unless-stopped"},
)
web.reload()                           # ⭐ attrs/status кэшируются — обновить перед проверкой
print(web.status, web.health)          # health: healthy / unhealthy / starting / unknown
print(web.logs(tail=20, timestamps=True).decode())
res = web.exec_run("nginx -t")         # ExecResult(exit_code, output)
print(res.exit_code, res.output.decode())
web.stop(timeout=10)
web.remove()
```text
Типовые задачи:

```python
# перезапустить unhealthy-контейнеры
for c in client.containers.list(filters={"health": "unhealthy"}):
    log.warning("рестарт %s", c.name)
    c.restart(timeout=10)

# убрать остановленные контейнеры своей лабы и «висячие» образы
for c in client.containers.list(all=True, filters={"status": "exited", "label": "owner=py-lab"}):
    c.remove()
client.images.prune(filters={"dangling": True})

try:
    client.containers.get("nope")
except NotFound:
    ...
```text
⚠️ Доступ к `docker.sock` = root на хосте. Скрипт или контейнер с примонтированным сокетом —
такой же привилегированный, как root.

---

## 3. ⭐ Kubernetes: официальный клиент

```python
from kubernetes import client, config
from kubernetes.client import ApiException

def load_kube(context: str | None = None) -&gt; None:
    try:
        config.load_incluster_config()             # внутри пода: токен ServiceAccount
    except config.ConfigException:
        config.load_kube_config(context=context)   # снаружи: ~/.kube/config / KUBECONFIG

load_kube(context="kind-py")                       # ⭐ контекст явно — не прод по ошибке
v1 = client.CoreV1Api()

pods = v1.list_namespaced_pod("default", label_selector="app=web", _request_timeout=10)
for pod in pods.items:
    statuses = pod.status.container_statuses or []        # у Pending-подов — None
    restarts = sum(cs.restart_count for cs in statuses)
    waiting = [cs.state.waiting.reason for cs in statuses if cs.state and cs.state.waiting]
    print(f"{pod.metadata.name:&lt;40} {pod.status.phase:<10} restarts={restarts} {','.join(waiting)}")
```text
⚠️ Поля в Python-объектах — **snake_case**: `containerStatuses` → `container_statuses`,
`restartCount` → `restart_count`. Структура та же, что в `kubectl get pod -o yaml`.

```python
# все неймспейсы, фильтр на стороне сервера
failed = v1.list_pod_for_all_namespaces(field_selector="status.phase=Failed")

# события пода — «почему он падает»
events = v1.list_namespaced_event("default", field_selector=f"involvedObject.name={name}")
for e in sorted(events.items, key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp):
    print(e.type, e.reason, e.message)

# удалить под: сначала серверный dry-run (проверит права и валидность, ничего не удалит)
v1.delete_namespaced_pod(name, "default", dry_run="All")
v1.delete_namespaced_pod(name, "default", grace_period_seconds=30)

# rollout restart деплоймента — то же, что делает kubectl
from datetime import datetime, timezone
patch = {"spec": {"template": {"metadata": {"annotations": {
    "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()&#125;&#125;&#125;&#125;}
client.AppsV1Api().patch_namespaced_deployment("web", "default", patch)

try:
    v1.read_namespaced_pod("nope", "default")
except ApiException as e:
    if e.status == 404: ...                        # e.status, e.reason, e.body (JSON)
```text
Следить за изменениями вместо опроса:

```python
from kubernetes import watch

w = watch.Watch()
for ev in w.stream(v1.list_namespaced_pod, namespace="default", timeout_seconds=300):
    pod = ev["object"]
    print(ev["type"], pod.metadata.name, pod.status.phase)     # ADDED / MODIFIED / DELETED
```text
Внутри кластера скрипту нужен ServiceAccount с правами (Role/RoleBinding) — ровно на те verbs,
что он использует: `pods: get, list, delete`, `events: list`. Подробно — [17_rbac.md](/kubernetes/17-rbac).

⚠️ Удалять можно только поды, которыми управляет контроллер (есть `metadata.owner_references` —
ReplicaSet/StatefulSet/Job): их пересоздадут. «Голый» под удаляется навсегда.

---

## 4. boto3 + S3-совместимое хранилище (MinIO)

```bash
docker run -d --name minio -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin123 \
  pgsty/silo:RELEASE.2026-09-16T00-00-00Z server /data --console-address ":9001"   # форк MinIO: официальный образ больше не скачивается
export AWS_ACCESS_KEY_ID=minioadmin AWS_SECRET_ACCESS_KEY=minioadmin123 S3_ENDPOINT=http://localhost:9000
```text&gt; Код boto3 одинаков для AWS, MinIO, Ceph и S3 облачных провайдеров — меняются только endpoint и ключи.

```python
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ.get("S3_ENDPOINT"),     # для AWS не задают; ключи boto3 берёт из AWS_* env
    region_name="us-east-1",
    config=Config(
        s3={"addressing_style": "path"},            # MinIO: http://host:9000/bucket/key
        retries={"max_attempts": 5, "mode": "standard"},
        connect_timeout=5, read_timeout=60,
    ),
)
bucket = "backups"

try:
    s3.head_bucket(Bucket=bucket)
except ClientError as e:
    if e.response["Error"]["Code"] == "404":
        s3.create_bucket(Bucket=bucket)
    else:
        raise                                        # 403 — нет прав, это не «нет бакета»

s3.upload_file("db.sql.gz", bucket, "pg/2026-09-27/db.sql.gz",       # большие файлы — multipart сам
               ExtraArgs={"Metadata": {"sha256": digest&#125;&#125;)
s3.download_file(bucket, "pg/2026-09-27/db.sql.gz", "/tmp/restore.sql.gz")

paginator = s3.get_paginator("list_objects_v2")      # ⭐ один вызов отдаёт максимум 1000 объектов
for page in paginator.paginate(Bucket=bucket, Prefix="pg/"):
    for obj in page.get("Contents", []):             # пусто → ключа Contents нет вовсе
        print(obj["Key"], obj["Size"], obj["LastModified"])   # LastModified — aware datetime (UTC)

url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
```text
Ротация — удалить объекты старше N дней:

```python
from datetime import datetime, timedelta, timezone

cutoff = datetime.now(timezone.utc) - timedelta(days=14)
old = [{"Key": o["Key"]}
       for page in paginator.paginate(Bucket=bucket, Prefix="pg/")
       for o in page.get("Contents", []) if o["LastModified"] < cutoff]
for i in range(0, len(old), 1000):                   # delete_objects — до 1000 ключей за вызов
    s3.delete_objects(Bucket=bucket, Delete={"Objects": old[i:i + 1000], "Quiet": True})
```text
В проде ротацию лучше отдать самому хранилищу — lifecycle-правилам бакета
(см. [04_s3_storage.md](/cloud/04-s3-storage)), а скрипт оставить для проверки.

---

## 5. prometheus_client: свои метрики

**A. Exporter — долгоживущий процесс с `/metrics`:**

```python
import logging, time
from prometheus_client import Counter, Gauge, start_http_server

log = logging.getLogger("backup_exporter")
BACKUP_AGE = Gauge("backup_age_seconds", "Возраст последнего бэкапа", ["bucket", "prefix"])
CHECKS = Counter("backup_exporter_checks", "Проверки хранилища", ["result"])   # → ..._checks_total

def collect_once() -> None:
    newest = max(o["LastModified"] for page in paginator.paginate(Bucket="backups", Prefix="pg/")
                 for o in page.get("Contents", []))
    BACKUP_AGE.labels("backups", "pg/").set(time.time() - newest.timestamp())

if __name__ == "__main__":
    start_http_server(9101)                    # http://localhost:9101/metrics (в фоновом потоке)
    while True:
        try:
            collect_once()
            CHECKS.labels("ok").inc()
        except Exception:
            log.exception("проверка не удалась")
            CHECKS.labels("error").inc()
        time.sleep(60)
```text
**B. Collector — значения считаются в момент scrape** (нет устаревших данных и своего цикла):

```python
import shutil, time
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.registry import Collector

class DiskCollector(Collector):
    def collect(self):
        g = GaugeMetricFamily("mount_used_ratio", "Доля занятого места", labels=["mount"])
        for mount in ("/", "/var"):
            u = shutil.disk_usage(mount)
            g.add_metric([mount], u.used / u.total)
        yield g

REGISTRY.register(DiskCollector())
start_http_server(9101)
while True:
    time.sleep(3600)                           # главный поток должен жить
```text
⚠️ `collect()` вызывается на **каждый** scrape: тяжёлые запросы (к API, S3) кэшируй,
иначе упрёшься в `scrape_timeout`.

**C. Textfile collector — для cron-задач и бэкапов:**

```python
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile

registry = CollectorRegistry()
Gauge("backup_last_success_timestamp_seconds", "Время последнего успешного бэкапа",
      registry=registry).set_to_current_time()
Gauge("backup_size_bytes", "Размер последнего бэкапа", registry=registry).set(archive.stat().st_size)
write_to_textfile("/var/lib/node_exporter/textfile/backup.prom", registry)   # атомарно: tmp + rename
```text
Алерт на такую метрику: `time() - backup_last_success_timestamp_seconds > 26 * 3600`.
Для задач без постоянного хоста (CI, k8s Job) — Pushgateway: `push_to_gateway("pushgateway:9091", job="backup", registry=registry)`.

| Способ | Когда |
|--------|-------|
| Exporter с циклом | Опрос внешней системы раз в N секунд, данные нужны всегда |
| Collector | Дешёвые значения, которые должны быть свежими на момент scrape |
| Textfile | Периодические задачи на хосте с node_exporter (бэкап, cron) |
| Pushgateway | Короткоживущие задачи без хоста: CI, k8s Job |

Правила имён и лейблов (базовые единицы, `_total`, `_seconds`, никаких id в лейблах) —
в [04_exporters.md](/monitoring/04-exporters). `Counter` сам добавляет `_total`
и серию `_created`.

---

## 6. Грабли

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| paramiko `AutoAddPolicy` | Подмена хоста не обнаружится | `load_system_host_keys()` + `RejectPolicy` |
| paramiko: `recv_exit_status()` до чтения вывода | Зависание на большом выводе (буфер канала полон) | Сначала `read()`, потом код |
| SSH без `timeout` | Скрипт висит на мёртвом хосте | `timeout=` в `connect` и `exec_command` |
| docker: проверка `c.status` без `reload()` | Устаревшее состояние | `c.reload()` |
| docker.sock в контейнер «для удобства» | Полный root на хосте | Только осознанно, минимальный круг |
| k8s: `load_kube_config()` без контекста | Скрипт уборки пошёл в прод-кластер | `context="..."` явно, вывод контекста в лог |
| k8s: `pod.status.containerStatuses` | `AttributeError` — поля snake_case | `container_statuses` |
| k8s: `container_statuses` = `None` | `TypeError` на Pending-подах | `or []` |
| k8s: удаление «голого» пода | Под не пересоздастся | Проверять `owner_references` |
| boto3: `list_objects_v2` без paginator | Видно только первые 1000 объектов | `get_paginator` |
| boto3: `page["Contents"]` | `KeyError` на пустом префиксе | `page.get("Contents", [])` |
| boto3 + MinIO без `addressing_style: path` | Запросы на `bucket.localhost` → DNS-ошибки | `Config(s3={"addressing_style": "path"})` |
| Новый boto3 и старое S3-совместимое хранилище | Ошибки при загрузке из-за новых контрольных сумм | `Config(request_checksum_calculation="when_required", response_checksum_validation="when_required")` |
| Лейбл метрики с id/URL | Взрыв кардинальности | Ограниченный набор значений |
| Тяжёлая работа в `collect()` | Таймауты scrape | Кэш / фоновый цикл |
| `.prom`-файл пишется напрямую | node_exporter читает половину файла | `write_to_textfile` (атомарно) |

---

## 💼 Как это в DevOps

- SSH-массовые команды (fabric/paramiko) — для разовых операций и сбора информации, пока нет Ansible,
  или внутри инструментов (например, собрать версии ядра со 100 хостов в CSV).
- docker SDK — уборка ресурсов на CI-раннерах, самописные health-watchdog'и, интеграционные тесты,
  поднимающие контейнеры из pytest.
- kubernetes-клиент — «уборщики» (Evicted, CrashLoopBackOff), отчёты по рестартам и лимитам,
  операторы (`kopf`), кастомные контроллеры и проверки в CI перед деплоем.
- boto3 — бэкапы и их ротация, раздача артефактов, presigned-ссылки, проверки «бэкап свежий»;
  один и тот же код работает с AWS и с MinIO/Ceph во внутреннем контуре.
- prometheus_client — самый короткий путь от «хочу видеть это на графике» до алерта: textfile
  для cron-задач, маленький exporter для внешней системы, у которой нет своего.

---

## 📌 Шпаргалка

| Хочу | Код |
|------|-----|
| SSH-команда | `SSHClient()` → `load_system_host_keys()` → `connect(host, username=..., timeout=10)` → `exec_command` |
| Код выхода SSH | `stdout.read()`, затем `stdout.channel.recv_exit_status()` |
| Файл по SSH | `client.open_sftp().put(local, remote)` / `Connection(...).put(...)` |
| Много хостов | `ThreadingGroup(*hosts).run(cmd, hide=True, warn=True)` |
| Docker-клиент | `docker.from_env()` |
| Контейнеры | `client.containers.list(all=True, filters={...})` |
| Запустить | `client.containers.run(img, detach=True, ports={"80/tcp": 8081})` |
| Логи / exec | `c.logs(tail=50)` / `c.exec_run("cmd")` |
| k8s-конфиг | `config.load_incluster_config()` / `config.load_kube_config(context=...)` |
| Поды | `CoreV1Api().list_namespaced_pod(ns, label_selector="app=x")` |
| Рестарты | `sum(cs.restart_count for cs in pod.status.container_statuses or [])` |
| События пода | `list_namespaced_event(ns, field_selector=f"involvedObject.name={name}")` |
| Удалить под | `delete_namespaced_pod(name, ns, dry_run="All")` → без `dry_run` |
| S3-клиент | `boto3.client("s3", endpoint_url=..., config=Config(s3={"addressing_style": "path"}))` |
| Загрузить / скачать | `s3.upload_file(f, bucket, key)` / `s3.download_file(bucket, key, f)` |
| Все объекты | `s3.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=p)` |
| Удалить пачкой | `s3.delete_objects(Bucket=b, Delete={"Objects": [{"Key": k}, ...]})` (≤ 1000) |
| Exporter | `Gauge(...)`, `start_http_server(9101)` |
| Метрика из cron | `CollectorRegistry()` + `write_to_textfile(path.prom, registry)` |

---

## 🧠 Что запомнить

1. SDK вместо `subprocess + парсинг вывода`, когда нужен структурированный результат.
2. SSH: проверка ключей хостов (`RejectPolicy`), таймауты, сначала вывод — потом код выхода.
3. fabric читает `~/.ssh/config` и даёт группы хостов; для настройки серверов — Ansible.
4. docker SDK = Docker API; `reload()` перед проверкой состояния; сокет = root.
5. k8s-клиент: in-cluster или kubeconfig **с явным контекстом**; поля snake_case; `container_statuses or []`.
6. Удаление в k8s — сначала `dry_run="All"`, только поды с владельцем, минимальные RBAC-права.
7. boto3 с MinIO: `endpoint_url` + path-style; ключи — из env; `list_objects_v2` только через paginator.
8. Ротацию бэкапов в S3 лучше отдать lifecycle-правилам, скрипт — для контроля.
9. Метрики: exporter (цикл/collector) для внешних систем, textfile — для cron, Pushgateway — для CI/Job.
10. Никаких id и URL в лейблах метрик; тяжёлое в `collect()` — кэшировать.

➡️ Дальше: [08_packaging_quality.md](/python/08-packaging-quality) · Задачи: 07_infra_libs_tasks.md


---

### Блок A. Теория


**A1.** Когда брать SDK, а когда достаточно `subprocess` с CLI? Приведи по примеру.

<details><summary>Ответ</summary>

SDK — когда нужен структурированный результат и логика (отчёт по подам, ротация в S3).
CLI — разовая простая команда без разбора вывода (`kubectl rollout status deploy/web`, `pg_dump`).

</details>

**A2.** ⭐ Почему `AutoAddPolicy` в paramiko — плохая идея? Что использовать вместо?

<details><summary>Ответ</summary>

Любой ключ неизвестного хоста принимается и запоминается — подмену сервера (MITM) не заметишь.
Правильно: `load_system_host_keys()` + `RejectPolicy`, ключи хостов заранее в `known_hosts`
(`ssh-keyscan` из доверенной сети или из инвентаря).

</details>

**A3.** Почему код выхода удалённой команды в paramiko читают после чтения stdout/stderr?

<details><summary>Ответ</summary>

Если вывод большой, буфер канала заполняется, удалённая команда блокируется на записи
и не завершается — `recv_exit_status()` ждёт вечно. Чтение вывода освобождает буфер.

</details>

**A4.** Чем fabric удобнее paramiko? Когда вместо fabric нужен Ansible?

<details><summary>Ответ</summary>

Читает `~/.ssh/config`, простые `run/sudo/put/get`, группы хостов с параллельным запуском,
результаты с кодами. Ansible — когда нужна идемпотентная настройка серверов, инвентарь, роли, отчёт об изменениях.

</details>

**A5.** Как docker SDK находит демон? Почему доступ к `docker.sock` приравнивают к root?

<details><summary>Ответ</summary>

`DOCKER_HOST` или `/var/run/docker.sock`. Через Docker API можно запустить привилегированный
контейнер с примонтированным `/` хоста — это полный root.

</details>

**A6.** Зачем `container.reload()`?

<details><summary>Ответ</summary>

Объект контейнера хранит снимок `attrs` на момент получения; `reload()` перечитывает состояние.

</details>

**A7.** ⭐ Как kubernetes-клиент выбирает конфигурацию внутри и снаружи кластера? Чем опасен вызов `load_kube_config()` без аргументов?

<details><summary>Ответ</summary>

`load_incluster_config()` — токен и CA ServiceAccount из `/var/run/secrets/kubernetes.io/serviceaccount`;
снаружи — `load_kube_config()` из `KUBECONFIG`/`~/.kube/config` и `current-context`. Без явного контекста
скрипт работает с тем кластером, который сейчас выбран в `kubectl` — возможно, с продом.

</details>

**A8.** Почему в Python-объектах k8s поля называются `container_statuses`, а не `containerStatuses`?

<details><summary>Ответ</summary>

Клиент сгенерирован из OpenAPI и следует Python-соглашению snake_case; JSON-имена из API
преобразуются в атрибуты моделей.

</details>

**A9.** Как найти поды в `CrashLoopBackOff` через клиент? Где это видно в объекте пода?

<details><summary>Ответ</summary>

`pod.status.container_statuses[i].state.waiting.reason == "CrashLoopBackOff"`
(`state.waiting` может быть `None`, `container_statuses` — тоже).

</details>

**A10.** Что делает `dry_run="All"` в вызовах API k8s?

<details><summary>Ответ</summary>

Сервер выполняет запрос полностью (аутентификация, RBAC, валидация, admission), но ничего не сохраняет.
Проверка «удалилось бы и хватит ли прав».

</details>

**A11.** Какие RBAC-права нужны скрипту, который читает поды и события и удаляет поды в одном неймспейсе?

<details><summary>Ответ</summary>

Role в неймспейсе: `pods` — `get`, `list`, `delete`; `events` — `list` (и `watch`, если используется watch);
RoleBinding на ServiceAccount скрипта.

</details>

**A12.** Что нужно поменять в boto3, чтобы работать с MinIO вместо AWS?

<details><summary>Ответ</summary>

`endpoint_url="http://minio:9000"`, ключи MinIO (через `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`),
`region_name`, обычно `Config(s3={"addressing_style": "path"})`.

</details>

**A13.** ⭐ Почему `list_objects_v2` без paginator — ошибка?

<details><summary>Ответ</summary>

Один вызов отдаёт не больше 1000 объектов; остальные — по `ContinuationToken`. Без paginator
скрипт видит только первую тысячу.

</details>

**A14.** Чем отличаются exporter с циклом, custom collector, textfile collector и Pushgateway? Когда что?

<details><summary>Ответ</summary>

Exporter с циклом — периодически опрашивает систему и держит последние значения; collector —
считает в момент scrape (свежо, но должно быть быстро); textfile — cron-задачи на хосте с node_exporter;
Pushgateway — короткие задачи без постоянного хоста (CI, k8s Job).

</details>

**A15.** Почему нельзя класть в лейблы метрик имена объектов, id пользователей или URL?

<details><summary>Ответ</summary>

Каждое уникальное значение лейбла — отдельный временной ряд; неограниченные значения раздувают
память и диск Prometheus и замедляют запросы.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1.
```text
```text:no-line-numbers
client = paramiko.SSHClient()
```text
```text:no-line-numbers
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```text
```text:no-line-numbers
client.connect(host, username="root", password="P@ssw0rd")
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
_, stdout, _ = client.exec_command("journalctl -u app --no-pager")   # вывод на 50 МБ
```text
```text:no-line-numbers
code = stdout.channel.recv_exit_status()
```text
```text:no-line-numbers
out = stdout.read()
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
c = client.containers.get("web")
```text
```text:no-line-numbers
c.stop()
```text
```text:no-line-numbers
print(c.status)
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
config.load_kube_config()
```text
```text:no-line-numbers
for pod in v1.list_pod_for_all_namespaces().items:
```text
```text:no-line-numbers
    if pod.status.phase != "Running":
```text
```text:no-line-numbers
        v1.delete_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
for pod in v1.list_namespaced_pod("default").items:
```text
```text:no-line-numbers
    restarts = sum(cs.restartCount for cs in pod.status.container_statuses)
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
r = s3.list_objects_v2(Bucket="backups", Prefix="pg/")
```text
```text:no-line-numbers
for obj in r["Contents"]:
```text
```text:no-line-numbers
    print(obj["Key"])
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
s3 = boto3.client("s3", endpoint_url="localhost:9000")
```text
```text:no-line-numbers
# B8.
```text
```text:no-line-numbers
REQS = Counter("app_requests_total", "Запросы", ["path", "user_id"])
```text
```text:no-line-numbers
REQS.labels(path=request.path, user_id=user.id).inc()
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
class S3Collector(Collector):
```text
```text:no-line-numbers
    def collect(self):
```text
```text:no-line-numbers
        objs = list_all_objects("backups")           # 300 тыс. объектов, ~40 секунд
```text
```text:no-line-numbers
        yield GaugeMetricFamily("backup_objects", "Число объектов", value=len(objs))
```text
```text:no-line-numbers
# B10.
```text
```text:no-line-numbers
Path("/var/lib/node_exporter/textfile/backup.prom").write_text(generate_latest(registry).decode())
```text
```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
group = ThreadingGroup("web1", "web2", "web-dead")
```text
```text:no-line-numbers
for conn, res in group.run("uptime", hide=True).items():
```text
```text:no-line-numbers
    print(conn.host, res.stdout)
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
e = v1.list_namespaced_event("default").items[0]
```text
```text:no-line-numbers
print(e.last_timestamp.isoformat())
```text
---

### Блок C. Практика


### C1. 🔑 SSH на пачку хостов (paramiko)
**1.** Реализуй `run_remote(host, port, command)` по образцу из конспекта (добавь порт).

<details><summary>Ответ</summary>

Порт — параметр `client.connect(host, port=port, ...)`. Без записи в `known_hosts` —
`SSHException: Server '[127.0.0.1]:2222' not found in known_hosts`.

</details>

**2.** Добавь хосты стенда в `known_hosts` (`ssh-keyscan -p 2221 127.0.0.1 >> ~/.ssh/known_hosts`).
**3.** Параллельно выполни на обоих `uptime` и `df -h /`, выведи таблицу хост/код/вывод.

<details><summary>Ответ</summary>

Счётчик рестартов — `c.attrs["RestartCount"]`, время старта — `c.attrs["State"]["StartedAt"]`.

</details>

**4.** Останови `ssh2` и убедись, что скрипт пишет «нет подключения» за ~10 секунд, а не висит.
**5.** Удали запись о хосте из `known_hosts` — что скажет `RejectPolicy`?

<details><summary>Ответ</summary>

```python
def crashloop(pod) -> bool:
    return any(cs.state and cs.state.waiting and cs.state.waiting.reason == "CrashLoopBackOff"
               for cs in pod.status.container_statuses or [])
```text
</details>

### C2. fabric
**1.** Опиши хосты стенда в `~/.ssh/config` (`Host lab1`, `Port 2221`, `User deploy`).

<details><summary>Ответ</summary>

Порт — параметр `client.connect(host, port=port, ...)`. Без записи в `known_hosts` —
`SSHException: Server '[127.0.0.1]:2222' not found in known_hosts`.

</details>

**2.** Через `ThreadingGroup("lab1", "lab2")` выполни `uname -a` и загрузи файл `put`.
**3.** Останови один контейнер и обработай `GroupException` — выведи успешные и упавшие хосты отдельно.

<details><summary>Ответ</summary>

Счётчик рестартов — `c.attrs["RestartCount"]`, время старта — `c.attrs["State"]["StartedAt"]`.

</details>

### C3. 🔑 Отчёт и уборка Docker
Напиши `docker_report.py`:
- таблица: имя, образ, статус, health, `RestartCount` (из `attrs`), время старта;
- `--prune --label owner=py-lab` — удалить остановленные контейнеры с этим лейблом, по умолчанию dry-run,
  с `--apply` — по-настоящему;
- код выхода 1, если есть `unhealthy` или `restarting`.

### C4. Watchdog
Запусти «больной» контейнер: `docker run -d --name sick --health-cmd='exit 1' --health-interval=5s nginx:alpine`.
Напиши watchdog, который раз в 30 секунд перезапускает `unhealthy`-контейнеры с лейблом `autoheal=true`
(добавь лейбл при запуске) и логирует действия. Корректно завершается по SIGTERM.

### C5. 🔑 Отчёт по подам
`pods_report.py --context kind-py [--namespace NS] [--min-restarts N]`:
- все поды (или неймспейса), фаза, суммарные рестарты, причины `waiting` (`CrashLoopBackOff`, `ImagePullBackOff`);
- сортировка по рестартам, `--json` для машинного вывода;
- код выхода 1, если есть поды в `CrashLoopBackOff`.

### C6. События
Для каждого пода с рестартами > 0 выведи последние 5 событий (`type`, `reason`, `message`),
отсортированных по времени. Учти, что `last_timestamp` бывает `None`.

### C7. Rollout restart и ожидание
Сделай rollout restart деплоймента `web` через `patch_namespaced_deployment` и дождись через `watch`,
пока все новые поды станут `Ready` (условие `Ready=True` в `pod.status.conditions`). Таймаут — 120 секунд.

### C8. 🔑 Бэкап в MinIO
`s3_backup.py upload FILE` / `list` / `verify KEY` / `rotate --keep-days N [--apply]`:
- при загрузке — sha256 в метаданных (`ExtraArgs={"Metadata": {...&#125;&#125;`), ключ `pg/YYYY-MM-DD/имя`;
- `verify` скачивает объект во временный файл и сверяет sha256 с метаданными (`head_object`);
- `rotate` — через paginator, dry-run по умолчанию, `delete_objects` пачками по 1000.
Проверь на 1500 маленьких объектах, что `list` видит все.

### C9. 🔑 Метрики бэкапа
**1.** В `s3_backup.py upload` после успеха пиши textfile-метрики: время последнего успеха и размер.

<details><summary>Ответ</summary>

Порт — параметр `client.connect(host, port=port, ...)`. Без записи в `known_hosts` —
`SSHException: Server '[127.0.0.1]:2222' not found in known_hosts`.

</details>

**2.** Напиши exporter на `:9101`, отдающий `backup_age_seconds` и `backup_objects` по префиксу в MinIO,
   с кэшированием результата на 60 секунд.
**3.** Проверь `curl -s localhost:9101/metrics | grep backup_`.

<details><summary>Ответ</summary>

Счётчик рестартов — `c.attrs["RestartCount"]`, время старта — `c.attrs["State"]["StartedAt"]`.

</details>

**4.** (Если есть стенд из блока мониторинга) добавь job в Prometheus и алерт «бэкап старше 26 часов».
### C10. Collector
Напиши `DiskCollector`, отдающий `mount_used_ratio{mount}` для всех точек монтирования из `/proc/mounts`
с реальными ФС (`ext4`, `xfs`, `btrfs`). Сравни значения с `df`.

---

### Блок D. Инциденты


**D1.** Скрипт «собрать версии пакетов со 120 серверов» висит час на одном хосте. Что добавить?

<details><summary>Ответ</summary>

`timeout` в `connect` и `exec_command` (или `connect_timeout` в fabric), параллельный запуск
с общим лимитом времени, отдельная обработка недоступных хостов.

</details>

**D2.** После переустановки сервера paramiko-скрипт падает с `Server '...' not found in known_hosts` (или `BadHostKeyException`). Коллега предлагает `AutoAddPolicy`. Как правильно?

<details><summary>Ответ</summary>

Сверить новый ключ хоста по доверенному каналу (консоль облака, инвентарь, cloud-init),
обновить `known_hosts` (`ssh-keygen -R host` + `ssh-keyscan`). `AutoAddPolicy` отключает защиту навсегда.

</details>

**D3.** «Уборщик» подов, запущенный с ноутбука «на стенд», удалил поды в проде. Как это возможно и как защититься?

<details><summary>Ответ</summary>

`load_kube_config()` взял `current-context` — на ноутбуке в этот момент был выбран прод.
Явный `context=` (или отдельный kubeconfig), вывод кластера/контекста в лог перед действием,
dry-run по умолчанию, у людей — права только на чтение прода.

</details>

**D4.** Скрипт удалил зависший под, и он не вернулся. В чём разница с остальными подами?

<details><summary>Ответ</summary>

У пода не было контроллера (`owner_references` пуст) — создан вручную или `kubectl run`.
Никто не пересоздаёт такие поды. Удалять только поды с владельцем (ReplicaSet/StatefulSet/Job).

</details>

**D5.** CronJob со скриптом падает: `403 Forbidden: pods is forbidden: User "system:serviceaccount:ops:default" cannot list resource "pods"`. Что сделать?

<details><summary>Ответ</summary>

Создать ServiceAccount, Role (pods: get/list/delete, events: list) и RoleBinding;
указать `serviceAccountName` в шаблоне пода CronJob.

</details>

**D6.** Скрипт ротации в S3 пишет «найдено 1000 объектов», хотя их 7000, и удаляет не то, что ожидалось. Что не так?

<details><summary>Ответ</summary>

Нет paginator: `list_objects_v2` вернул первые 1000 ключей (в лексикографическом порядке),
решение о ротации принято по неполным данным. `get_paginator("list_objects_v2")`.

</details>

**D7.** После обновления boto3 загрузка бэкапов во внутреннее S3-совместимое хранилище стала падать с ошибками про контрольные суммы/неподдерживаемые заголовки. Как починить, не откатываясь?

<details><summary>Ответ</summary>

Новые версии boto3 по умолчанию добавляют контрольные суммы к запросам; не все S3-совместимые
хранилища это поддерживают. `Config(request_checksum_calculation="when_required", response_checksum_validation="when_required")`
или переменные `AWS_REQUEST_CHECKSUM_CALCULATION` / `AWS_RESPONSE_CHECKSUM_VALIDATION` = `when_required`.

</details>

**D8.** После добавления самописного exporter'а `scrape_duration_seconds` у job'а — 15 секунд, таргет периодически `down`. Почему?

<details><summary>Ответ</summary>

Тяжёлая работа в `collect()` на каждый scrape (походы в API/S3). Кэш, фоновый цикл,
увеличенный `scrape_interval` для этого job'а.

</details>

**D9.** Память Prometheus выросла втрое после выката нового exporter'а. В коде лейбл `key` с именем объекта S3. Объясни и исправь.

<details><summary>Ответ</summary>

Каждое имя объекта — новый временной ряд, их сотни тысяч. Убрать `key` из лейблов,
агрегировать (число объектов и возраст последнего по префиксу).

</details>

**D10.** Docker-watchdog перезапускает контейнеры, которые только что стартовали и ещё не прошли healthcheck. Что учесть?

<details><summary>Ответ</summary>

Статус `starting` и `start_period` healthcheck'а; пауза после старта (по `State.StartedAt`),
порог «unhealthy N проверок подряд», лимит рестартов в час, `reload()` перед решением.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как выполнить команду на 100 серверах из Python?

<details><summary>Ответ</summary>

fabric `ThreadingGroup` или paramiko + `ThreadPoolExecutor` с таймаутами; для регулярных задач — Ansible.

</details>

**2.** Чем paramiko отличается от fabric?

<details><summary>Ответ</summary>

paramiko — низкоуровневый SSH (каналы, SFTP); fabric — удобная обёртка: `~/.ssh/config`, `run/sudo/put`, группы.

</details>

**3.** Как из Python получить список контейнеров и перезапустить нездоровые?

<details><summary>Ответ</summary>

`docker.from_env().containers.list(filters={"health": "unhealthy"})` → `c.restart()`.

</details>

**4.** Как Python-скрипт внутри пода получает доступ к API Kubernetes?

<details><summary>Ответ</summary>

`config.load_incluster_config()` — токен ServiceAccount, права через Role/RoleBinding.

</details>

**5.** Как найти поды с большим числом рестартов?

<details><summary>Ответ</summary>

`list_pod_for_all_namespaces()` → сумма `restart_count` по `container_statuses` → сортировка.

</details>

**6.** Как безопасно удалять ресурсы в k8s из скрипта?

<details><summary>Ответ</summary>

Явный контекст, dry-run (`dry_run="All"`), фильтры (неймспейсы, владелец), минимальный RBAC, логирование действий.

</details>

**7.** Как работать с MinIO через boto3?

<details><summary>Ответ</summary>

`boto3.client("s3", endpoint_url="http://minio:9000", config=Config(s3={"addressing_style": "path"}))`, ключи из env.

</details>

**8.** Как получить все объекты бакета, если их больше 1000?

<details><summary>Ответ</summary>

`s3.get_paginator("list_objects_v2").paginate(Bucket=..., Prefix=...)`.

</details>

**9.** Как отдать метрику из cron-скрипта в Prometheus?

<details><summary>Ответ</summary>

Textfile collector: `write_to_textfile("/var/lib/node_exporter/textfile/x.prom", registry)`; для CI — Pushgateway.

</details>

**10.** Как написать свой exporter?

<details><summary>Ответ</summary>

`prometheus_client`: метрики `Gauge`/`Counter` + `start_http_server(port)` и цикл опроса,
    или custom collector; правильные имена, ограниченные лейблы, кэш тяжёлых запросов.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Выполняю команды на пачке хостов через paramiko/fabric с таймаутами и проверкой ключей
- [ ] Управляю контейнерами через docker SDK: список, run, logs, exec, уборка
- [ ] Подключаюсь к k8s in-cluster и по kubeconfig с явным контекстом
- [ ] Строю отчёт по подам: фазы, рестарты, CrashLoopBackOff, события
- [ ] Удаляю ресурсы k8s только после dry-run и с проверкой владельца
- [ ] Знаю минимальные RBAC-права для своих скриптов
- [ ] Работаю с MinIO/S3 через boto3: upload/download, paginator, delete_objects, presigned URL
- [ ] Отдаю метрики через exporter, collector и textfile
- [ ] Контролирую кардинальность лейблов и скорость `collect()`
- [ ] Понимаю, когда SDK, а когда CLI через subprocess
