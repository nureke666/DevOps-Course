---
title: "10. Безопасность контейнеров"
description: "Non-root, capabilities, seccomp, секреты, сканирование образов (trivy/hadolint/cosign), rootless docker"
---

# 10. Безопасность контейнеров

> Роадмап: best practice'ы Dockerfile + вопрос «за счёт каких технологий ядра обеспечивается
> изоляция». Эта тема — практическая сторона того и другого.
> **После темы ты умеешь:** собрать образ, который не стыдно пустить в прод: без root,
> без секретов, с минимумом прав, проверенный сканером.

---

## 🗺️ Схема: слои защиты

```text:no-line-numbers
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 1. ОБРАЗ        база из доверенного источника, пин версии, минимум   │
 │                 пакетов, без секретов, сканирование CVE, подпись     │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 2. КОНТЕЙНЕР    non-root USER, --read-only, --cap-drop=ALL,          │
 │                 no-new-privileges, seccomp, лимиты ресурсов          │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 3. СЕТЬ         не публиковать лишнее, internal-сети, TLS,           │
 │                 iptables/DOCKER-USER                                 │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 4. ДЕМОН/ХОСТ   не раздавать docker.sock и группу docker,            │
 │                 rootless docker, обновления ядра, аудит              │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 5. ПРОЦЕСС      секреты из хранилища, ротация, RBAC в registry,      │
 │                 сканирование в CI, политика admission на деплое      │
 └──────────────────────────────────────────────────────────────────────┘
```

---

## 1. Главное: контейнер — не граница безопасности

Ядро **общее** с хостом. Побег из контейнера возможен при: уязвимости ядра/runtime,
`--privileged`, монтировании `docker.sock` или хостовых путей, лишних capabilities.
Отсюда следует: **контейнер по умолчанию считается менее изолированным, чем VM**,
и его конфигурацию надо ужимать осознанно.

```bash
# Наглядно, почему --privileged и монтирование / — это отдача хоста
docker run --rm -it --privileged -v /:/host alpine chroot /host sh   # ← ты root на ХОСТЕ
```

---

## 2. Не работай от root

```dockerfile
# Debian/Ubuntu
RUN groupadd -r app && useradd -r -g app -u 10001 -d /app -s /sbin/nologin app
# Alpine
RUN addgroup -S app && adduser -S -u 10001 -G app app

RUN mkdir -p /app/data && chown -R app:app /app
USER app          # всё, что ниже, и рантайм — от app
```
```bash
docker run --user 10001:10001 myapp          # перебить на запуске
docker inspect myapp --format '{{.Config.User}}'
docker exec myapp id
```

| Почему это важно | |
|---|---|
| root в контейнере = **UID 0 на хосте** (без user namespace) | Уязвимость + смонтированный каталог → компрометация хоста |
| Многие CVE эксплуатируются только от root | Non-root отсекает целый класс атак |
| Требование политик безопасности и k8s PSS/PSA | `runAsNonRoot: true` не пустит образ, который запускается от root |

> Побочный эффект: непривилегированный процесс не может слушать порты < 1024.
> Решение — слушать 8080 и публиковать `-p 80:8080` (или выдать `CAP_NET_BIND_SERVICE`).

---

## 3. Capabilities, seccomp, привилегии

```bash
docker run -d \
  --cap-drop=ALL \                          # снять все
  --cap-add=NET_BIND_SERVICE \              # вернуть только нужное
  --security-opt no-new-privileges:true \   # запрет повышения прав через setuid
  --read-only \                             # неизменяемая корневая ФС
  --tmpfs /tmp --tmpfs /run \
  --pids-limit=200 --memory=512m --cpus=1 \
  myapp:1.0
```

| Capability | Зачем обычно нужна |
|-----------|--------------------|
| `NET_BIND_SERVICE` | Слушать порт < 1024 |
| `CHOWN`, `SETUID`, `SETGID`, `FOWNER` | Нужны entrypoint'ам, которые понижают привилегии |
| `NET_RAW` | ping, raw-сокеты (по умолчанию есть — часто можно снять) |
| `SYS_ADMIN`, `SYS_MODULE`, `SYS_PTRACE` | ⚠️ Почти всегда означают «дай мне хост» |

```bash
docker run --rm alpine grep Cap /proc/1/status         # что реально есть
docker inspect c --format '{{.HostConfig.Privileged}} {{.HostConfig.CapAdd}}'
```

> **`--privileged` — красный флаг.** Он снимает почти всю защиту (все capabilities,
> доступ к устройствам, отключение seccomp/AppArmor). Если он «нужен» — почти всегда
> задача решается точечно: `--device`, конкретная capability, `--cap-add=SYS_NICE` и т. п.

---

## 4. Секреты

| Способ | Оценка |
|--------|--------|
| `ENV` / `ARG` в Dockerfile | ❌ Видно в `docker history` и `inspect` у всех, кто скачал образ |
| `COPY secret.key` | ❌ Остаётся в слое навсегда, даже после `rm` |
| Переменные окружения в рантайме | ⚠️ Приемлемо, но видны в `docker inspect`, в `/proc/<pid>/environ`, утекают в дампы и логи |
| `--env-file` | ⚠️ То же самое, но хотя бы не в истории shell |
| **BuildKit secret** (`RUN --mount=type=secret`) | ✅ Для сборки |
| **Файл, смонтированный в tmpfs** / docker secrets (Swarm) / k8s Secret | ✅ Для рантайма |
| **Внешнее хранилище** (Vault, AWS/GCP Secret Manager, SOPS) | ✅✅ Правильный путь |

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci
```
```bash
docker build --secret id=npmrc,src=$HOME/.npmrc -t app .
docker history --no-trunc app | grep -i secret     # пусто ✅

# Проверить, не утёк ли секрет в чужой образ
docker history --no-trunc <img> | grep -iE 'password|token|secret|key'
docker image inspect <img> --format '{{json .Config.Env}}'
trivy image --scanners secret <img>
```

---

## 5. Сканирование и supply chain

```bash
# CVE
trivy image --severity HIGH,CRITICAL --exit-code 1 myapp:1.0     # ← ломает CI при находках
docker scout cves myapp:1.0
grype myapp:1.0

# Секреты и мисконфиги
trivy image --scanners secret,misconfig myapp:1.0
trivy config Dockerfile
hadolint Dockerfile

# SBOM и подпись
trivy image --format cyclonedx -o sbom.json myapp:1.0
docker sbom myapp:1.0
cosign sign --key cosign.key registry/myapp@sha256:…
cosign verify --key cosign.pub registry/myapp@sha256:…
```

**Как это ставят в пайплайн:**
```text:no-line-numbers
build → trivy (fail on CRITICAL) → push → cosign sign → deploy (admission проверяет подпись)
                                                        + периодический rescan уже
                                                          опубликованных образов
```
> Важно: уязвимости появляются **после** публикации образа. Поэтому нужны регулярная
> пересборка (обновление базового образа) и повторное сканирование того, что уже в проде.

---

## 6. Демон и хост

```bash
# Кто может управлять докером — тот root
getent group docker                     # ⚠️ ревизуй состав группы
ls -l /var/run/docker.sock
```

**Rootless Docker** — демон работает от обычного пользователя (user namespaces):

```bash
curl -fsSL https://get.docker.com/rootless | sh
systemctl --user enable --now docker
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
docker info | grep -i rootless
```
Ограничения rootless: порты < 1024 (решается `net.ipv4.ip_unprivileged_port_start`),
некоторые сетевые режимы, `--privileged`, overlay-сети, производительность сети чуть ниже.

```json
// /etc/docker/daemon.json — разумные настройки
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true,
  "no-new-privileges": true,
  "userland-proxy": false,
  "default-ulimits": { "nofile": { "Name": "nofile", "Hard": 65535, "Soft": 65535 } }
}
```

Дополнительно: `docker-bench-security` (проверка по CIS Benchmark), обновления ядра и докера,
аудит `auditd` на `/var/lib/docker` и сокет, отдельный раздел под `/var/lib/docker`.

---

## 7. Чек-лист прод-образа и прод-запуска

**Образ**
- [ ] База официальная, тег зафиксирован (лучше — дайджест)
- [ ] `-slim`/`-alpine`/distroless, ничего лишнего
- [ ] Multi-stage: компиляторов и исходников нет
- [ ] `.dockerignore` (нет `.git`, `.env`, ключей)
- [ ] Нет секретов в слоях, `ENV`, `ARG`
- [ ] `USER` непривилегированный, UID ≥ 10000
- [ ] `HEALTHCHECK`, exec-форма `ENTRYPOINT`/`CMD`
- [ ] OCI-метки (source, revision, version)
- [ ] Прошёл `hadolint` и сканер (0 CRITICAL)

**Запуск**
- [ ] `--read-only` + tmpfs для изменяемых путей
- [ ] `--cap-drop=ALL` + точечные `--cap-add`
- [ ] `--security-opt no-new-privileges:true`
- [ ] Лимиты `--memory`, `--cpus`, `--pids-limit`
- [ ] Нет `--privileged`, нет монтирования `docker.sock` и `/`
- [ ] Порты наружу только у точки входа, БД — в `internal` сети
- [ ] Секреты из внешнего хранилища, не в образе
- [ ] Ротация логов, restart policy, мониторинг

---

## 💼 Как это в DevOps

- Сканирование и линт — **шаги пайплайна с падением сборки**, а не «посмотрим потом».
- В Kubernetes это формализовано: Pod Security Standards, `securityContext`
  (`runAsNonRoot`, `readOnlyRootFilesystem`, `capabilities.drop`), NetworkPolicy,
  admission-контроллеры (Kyverno/Gatekeeper) — но пишется всё ровно про то же, что здесь.
- «Собрать образ» и «собрать безопасный образ» отличаются десятком строк — и именно эти
  строки отличают джуна от инженера на собеседовании.

---

## 🧪 Мини-лаба: превращаем небезопасный образ в прод-готовый

```bash
mkdir -p ~/docker-lab/10 && cd ~/docker-lab/10
echo "DB_PASSWORD=hunter2" > .env
printf 'flask==3.0.3\n' > requirements.txt
cat > app.py <<'EOF'
import os
print("app started, user:", os.getuid())
import time; time.sleep(3600)
EOF

# --- 1. КАК НЕ НАДО
cat > Dockerfile.bad <<'EOF'
FROM python:3.12
ARG DB_PASSWORD
ENV DB_PASSWORD=${DB_PASSWORD}
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD python app.py
EOF
docker build -q -f Dockerfile.bad --build-arg DB_PASSWORD=hunter2 -t sec:bad .
docker run --rm sec:bad python -c "import os;print('UID:',os.getuid())"     # 0 — root!
docker history --no-trunc sec:bad | grep -i hunter2 | head -1               # секрет в истории
docker run --rm sec:bad cat /app/.env                                       # .env внутри образа
docker image inspect sec:bad --format '{{json .Config.Env}}' | grep -o hunter2

# --- 2. КАК НАДО
cat > .dockerignore <<'EOF'
.env
.git
__pycache__/
Dockerfile*
EOF
cat > Dockerfile <<'EOF'
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS builder
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM base AS runtime
LABEL org.opencontainers.image.source="https://git.local/me/app"
ENV PATH="/opt/venv/bin:$PATH"
RUN groupadd -r app && useradd -r -g app -u 10001 -d /app -s /sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app.py .
USER app
HEALTHCHECK --interval=30s CMD ["python","-c","print('ok')"]
ENTRYPOINT ["python"]
CMD ["app.py"]
EOF
docker build -q -t sec:good .
docker run --rm sec:good -c "import os;print('UID:',os.getuid())"     # 10001 ✅
docker run --rm sec:good -c "print(open('/app/.env').read())" 2>&1 | tail -1   # файла нет ✅
docker history --no-trunc sec:good | grep -ci hunter2                 # 0 ✅

# --- 3. Жёсткий запуск
docker run -d --name hard \
  --read-only --tmpfs /tmp \
  --cap-drop=ALL \
  --security-opt no-new-privileges:true \
  --memory=256m --cpus=0.5 --pids-limit=100 \
  sec:good
docker exec hard sh -c 'echo x > /etc/test' 2>&1 | head -1         # Read-only file system
docker exec hard grep Cap /proc/1/status
docker exec hard id
docker inspect hard --format 'ro={{.HostConfig.ReadonlyRootfs}} caps-drop={{.HostConfig.CapDrop}}'
docker rm -f hard

# --- 4. Секреты в сборке правильно
cat > Dockerfile.secret <<'EOF'
# syntax=docker/dockerfile:1
FROM alpine:3.20
RUN --mount=type=secret,id=dbpass \
    sh -c 'echo "секрет прочитан, длина: $(wc -c < /run/secrets/dbpass)"'
EOF
echo -n "hunter2" > /tmp/dbpass
docker build -f Dockerfile.secret --secret id=dbpass,src=/tmp/dbpass --no-cache \
  --progress=plain -t sec:secret . 2>&1 | grep длина
docker history --no-trunc sec:secret | grep -ci hunter2             # 0 ✅
rm -f /tmp/dbpass

# --- 5. Сканирование
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.74.0 image --severity HIGH,CRITICAL --quiet sec:bad  | tail -5
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.74.0 image --severity HIGH,CRITICAL --quiet sec:good | tail -5
docker run --rm -i hadolint/hadolint < Dockerfile

# --- 6. Демонстрация опасности (ТОЛЬКО на учебной машине!)
docker run --rm --privileged -v /:/host alpine ls /host/etc/shadow && \
  echo "⚠️ вот почему privileged + монтирование / = отдача хоста"
getent group docker

# --- 7. Уборка
docker rmi sec:bad sec:good sec:secret 2>/dev/null
cd ~ && rm -rf ~/docker-lab/10
```

---

## 📌 Шпаргалка

| Что | Как |
|-----|-----|
| Non-root в образе | `useradd -r -u 10001 app` + `USER app` |
| Non-root на запуске | `--user 10001:10001` |
| Убрать все привилегии | `--cap-drop=ALL --cap-add=<нужное>` |
| Запретить повышение прав | `--security-opt no-new-privileges:true` |
| Неизменяемая ФС | `--read-only --tmpfs /tmp` |
| Лимиты | `--memory --cpus --pids-limit --ulimit` |
| Секрет при сборке | `RUN --mount=type=secret,id=X` + `--secret id=X,src=file` |
| Проверить секреты в образе | `docker history --no-trunc`, `trivy image --scanners secret` |
| Сканер CVE | `trivy image --severity HIGH,CRITICAL --exit-code 1` |
| Линтер | `hadolint Dockerfile` |
| Подпись | `cosign sign/verify` |
| Аудит хоста | `docker-bench-security` |
| Rootless | `dockerd-rootless-setuptool.sh install` |
| Что реально дано контейнеру | <code v-pre>docker inspect --format '{{.HostConfig.Privileged}} {{.HostConfig.CapAdd}} {{.HostConfig.Binds}}'</code> |

---

## 🧠 Что запомнить

1. Контейнер — **не граница безопасности**: ядро общее, изоляция слабее VM.
2. `--privileged`, `-v /:/host`, `-v /var/run/docker.sock` — три способа отдать хост.
3. Членство в группе `docker` эквивалентно root.
4. **Non-root обязателен**: `USER` в образе + `runAsNonRoot` в оркестраторе.
5. Секреты **никогда** не попадают в образ: ни `ARG`, ни `ENV`, ни `COPY`.
   Для сборки — BuildKit secret, для рантайма — внешнее хранилище.
6. То, что попало в слой, достаётся из образа навсегда — `rm` не помогает.
7. Минимальная база (slim/distroless) = меньше CVE, меньше поверхность атаки.
8. `--cap-drop=ALL` + точечные `--cap-add` + `no-new-privileges` + `--read-only` — база
   безопасного запуска.
9. Лимиты ресурсов — это тоже безопасность (защита от DoS соседями).
10. Сканирование и линт — **шаги CI с падением сборки**, плюс регулярный rescan прод-образов.
11. Подпись образов + проверка на деплое защищает от подмены в registry.
12. Rootless-докер и Podman — способ убрать root-демон с хоста.

---

## Задачи

> ⚠️ Эксперименты с `--privileged` и монтированием `/` делай **только на учебной машине/VM**.

---

### Блок A. Теория

**A1.** Почему говорят, что контейнер — не граница безопасности? Сравни с VM.

<details><summary>Ответ</summary>

Контейнеры делят **ядро** с хостом: уязвимость в ядре или runtime, а также ошибочная
конфигурация дают побег на хост. У VM своё ядро и аппаратная изоляция — поверхность
взаимодействия с хостом значительно меньше. Контейнер — механизм **изоляции процессов**,
а не средство защиты от недоверенного кода; для этого используют VM, gVisor, Kata.

</details>

**A2.** Назови три конфигурации, которые фактически отдают контейнеру весь хост.

<details><summary>Ответ</summary>

`--privileged`; монтирование `/` (или `/etc`, `/root`) с записью; монтирование
`/var/run/docker.sock`. Сюда же — `--pid=host`/`--net=host` с широкими правами и
`--cap-add=SYS_ADMIN`.

</details>

**A3.** Почему членство в группе `docker` = root на хосте?

<details><summary>Ответ</summary>

Через сокет отдаются команды демону, который работает от root и не проверяет права
на уровне API: можно поднять привилегированный контейнер с `-v /:/host` и стать root
на хосте. Проверки «пользователь X не имеет права запускать привилегированные контейнеры» нет.

</details>

**A4.** Что плохого в том, что процесс в контейнере работает от root?

<details><summary>Ответ</summary>

UID 0 внутри = UID 0 на хосте (если не включены user namespaces): при побеге или
через смонтированные пути можно менять файлы хоста; внутри контейнера root может ставить
пакеты, менять конфиги, снимать ограничения приложения; многие эксплойты требуют root.
Плюс политики (k8s PSS, корпоративные стандарты) такие образы просто не пропустят.

</details>

**A5.** Как создать непривилегированного пользователя в Debian-образе и в Alpine?
Какое ограничение появится?

<details><summary>Ответ</summary>

Debian: `RUN groupadd -r app && useradd -r -g app -u 10001 -d /app -s /sbin/nologin app`.
Alpine: `RUN addgroup -S app && adduser -S -u 10001 -G app app`. Ограничение: нельзя
привязываться к портам < 1024 (нужна `CAP_NET_BIND_SERVICE`), и нужно заранее выдать права
на каталоги, куда приложение пишет.

</details>

**A6.** Что такое capabilities? Какие обычно снимают, какие оставляют?

<details><summary>Ответ</summary>

Разбиение прав root на отдельные привилегии. Обычно снимают всё (`--cap-drop=ALL`)
и добавляют точечно: `NET_BIND_SERVICE` (порт < 1024), `CHOWN`/`SETUID`/`SETGID`
(для entrypoint'ов, понижающих привилегии), `NET_RAW` (ping). Никогда не выдают
`SYS_ADMIN`, `SYS_MODULE`, `SYS_PTRACE` без веской причины.

</details>

**A7.** Что делает `--security-opt no-new-privileges:true`?

<details><summary>Ответ</summary>

Запрещает процессу и его потомкам получать новые привилегии — в частности,
не срабатывают setuid-бинарники (например, `sudo`, `su`, уязвимые setuid-утилиты).
Отсекает типовой путь эскалации внутри контейнера.

</details>

**A8.** Что даёт `--read-only` и почему к нему нужен `--tmpfs`?

<details><summary>Ответ</summary>

Делает корневую ФС контейнера доступной только для чтения: нельзя подменить бинарники,
положить веб-шелл, изменить конфиги. Большинству приложений всё же нужны временные каталоги
(`/tmp`, `/run`, кэши), поэтому их явно монтируют как tmpfs или volume — так изменяемая
область ограничена и известна.

</details>

**A9.** Почему `ARG`/`ENV` не подходят для секретов? Как проверить, что секрет утёк в образ?

<details><summary>Ответ</summary>

Оба сохраняются в конфиге/истории образа и видны через `docker history`,
`docker image inspect`, а также любому, кто скачал образ. Проверка:
`docker history --no-trunc <img> | grep -iE 'pass|token|secret|key'`,
<code v-pre>docker image inspect &lt;img&gt; --format '{{json .Config.Env}}'</code>,
`trivy image --scanners secret <img>`, а также распаковка слоёв из `docker save`.

</details>

**A10.** Как правильно передать секрет **в сборку**? А **в рантайм**?

<details><summary>Ответ</summary>

В сборку — BuildKit: `RUN --mount=type=secret,id=x` + `docker build --secret id=x,src=file`
(или `--mount=type=ssh`). В рантайм — переменные окружения из секрет-хранилища CI/облака,
docker secrets (Swarm), k8s Secret, файлы, смонтированные в tmpfs, а лучше — прямая интеграция
приложения с Vault/Secret Manager с ротацией.

</details>

**A11.** Что такое seccomp-профиль и что он делает по умолчанию в докере?

<details><summary>Ответ</summary>

Фильтр системных вызовов ядра. Дефолтный профиль докера блокирует несколько десятков
опасных syscall (`mount`, `kexec_load`, `ptrace` в старых версиях, `bpf` и др.), оставляя всё,
что нужно обычным приложениям. Отключается `--security-opt seccomp=unconfined` — это плохая идея.

</details>

**A12.** Зачем сканировать образы, если они уже прошли сканирование при сборке?

<details><summary>Ответ</summary>

Уязвимости публикуются постоянно: образ, чистый на момент сборки, через месяц может
иметь критические CVE. Нужны периодическое пересканирование того, что уже в registry/проде,
и регулярная пересборка с обновлённым базовым образом.

</details>

**A13.** Что такое SBOM и зачем он нужен?

<details><summary>Ответ</summary>

Software Bill of Materials — машиночитаемый список всех компонентов и версий в образе
(CycloneDX/SPDX). Позволяет мгновенно ответить «затронуты ли мы новой CVE в libX»,
нужен для комплаенса и анализа цепочки поставки.

</details>

**A14.** Что такое подпись образа (cosign) и где проверяется подпись?

<details><summary>Ответ</summary>

Криптографическая подпись образа (по дайджесту) ключом или keyless через OIDC.
Проверяется на деплое: admission-контроллер в k8s (Kyverno, Gatekeeper, Connaisseur)
или шаг пайплайна перед выкаткой. Защищает от подмены образа в registry.

</details>

**A15.** Что такое rootless docker? Какие у него ограничения?

<details><summary>Ответ</summary>

Режим, где демон и контейнеры работают от обычного пользователя с помощью
user namespaces — root в контейнере отображается на непривилегированного пользователя хоста.
Ограничения: порты < 1024 (нужна настройка sysctl), нет `--privileged`, ограниченная поддержка
overlay-сетей и некоторых драйверов хранилища, чуть ниже производительность сети
(slirp4netns/rootlesskit).

</details>

**A16.** Почему лимиты ресурсов — это тоже вопрос безопасности?

<details><summary>Ответ</summary>

Контейнер без лимитов может исчерпать память/CPU/PID/диск хоста и положить соседей —
это отказ в обслуживании, в том числе умышленный (fork-бомба, лог-бомба). Лимиты
локализуют аварию одним контейнером.

</details>

**A17.** Перечисли чек-лист безопасного прод-образа (минимум 8 пунктов).

<details><summary>Ответ</summary>

Официальная база с зафиксированным тегом/дайджестом; минимальная база;
multi-stage без сборочных инструментов; `.dockerignore`; отсутствие секретов в слоях и `ENV`;
non-root `USER` с UID ≥ 10000; exec-форма и `HEALTHCHECK`; OCI-метки; пройденные линтер и
сканер; отсутствие лишних пакетов и утилит; фиксированные версии зависимостей; подпись образа.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker run --user 10001:10001 myapp
B2.  docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE nginx
B3.  docker run --security-opt no-new-privileges:true myapp
B4.  docker run --read-only --tmpfs /tmp --tmpfs /run nginx:alpine
B5.  docker run --privileged -v /:/host alpine chroot /host sh
B6.  docker history --no-trunc app | grep -i password
B7.  trivy image --severity CRITICAL --exit-code 1 app:1.0
B8.  trivy image --scanners secret app:1.0
B9.  docker run --rm -i hadolint/hadolint < Dockerfile
B10. cosign verify --key cosign.pub reg/app@sha256:...
B11. docker inspect c --format '{{.HostConfig.Privileged}} {{.HostConfig.CapAdd}}'
B12. docker run --rm alpine grep Cap /proc/1/status
B13. docker run --rm --pids-limit=50 alpine sh -c ':(){ :|:& };:'
B14. getent group docker
B15. docker run --rm -v /var/run/docker.sock:/var/run/docker.sock docker ps
```

<details><summary>Ответ</summary>

**B1.** Запустить процесс от UID/GID 10001 независимо от `USER` в образе.
**B2.** Снять все capabilities и вернуть только возможность слушать привилегированный порт.
**B3.** Запретить получение новых привилегий (setuid не сработает).
**B4.** Неизменяемая корневая ФС + tmpfs для того, что nginx должен писать.
**B5.** ⚠️ Полный доступ к файловой системе хоста с правами root — демонстрация опасности.
**B6.** Поиск утёкших секретов в истории слоёв.
**B7.** Сканирование с падением (exit 1) при критических уязвимостях — шаг для CI.
**B8.** Поиск секретов внутри образа сканером.
**B9.** Линтер Dockerfile.
**B10.** Проверка подписи образа по дайджесту.
**B11.** Показать, запущен ли контейнер привилегированным и какие capabilities добавлены.
**B12.** Показать битовые маски capabilities процесса PID 1 внутри контейнера.
**B13.** Fork-бомба, ограниченная cgroup pids: контейнер задохнётся, хост выживет.
**B14.** Показать, кто состоит в группе `docker` (то есть у кого фактически root).
**B15.** Управление докером хоста из контейнера через смонтированный сокет.

</details>

**B16.** Чем `--user 1001` при запуске отличается от `USER app` в Dockerfile?
Что победит, если заданы оба?

<details><summary>Ответ</summary>

`USER app` — часть образа, применяется по умолчанию; `--user 1001` — решение уровня
запуска. Побеждает флаг запуска: он перекрывает `USER` из образа. При этом `--user` не меняет
права на файлы — процесс может потерять доступ к каталогам, созданным под другим UID.

</details>

---

### Блок C. Практика

#### C1. 🔑 Из небезопасного образа — в прод-готовый (главное задание)

Дан образ с набором проблем: работает от root, секрет в `ARG`/`ENV`, `.env` внутри,
жирная база, нет healthcheck, shell-форма CMD.

1. Зафиксируй все проблемы, доказав каждую командой
   (UID, `docker history`, наличие файла, размер, `docker inspect`).
2. Перепиши Dockerfile по всем правилам.
3. Докажи, что каждая проблема устранена (теми же командами).
4. Запусти контейнер «жёстко»: `--read-only`, `--cap-drop=ALL`, `no-new-privileges`, лимиты.
5. Прогони `hadolint` и `trivy`, добейся отсутствия CRITICAL.
6. Сравни размер и число уязвимостей «до/после» таблицей.

<details><summary>Ответ</summary>

Полная мини-лаба — см. выше в этом же конспекте. Ключевые проверки:

```bash
# «до»:
docker run --rm sec:bad python -c "import os;print(os.getuid())"       # 0
docker history --no-trunc sec:bad | grep -i hunter2
docker run --rm sec:bad cat /app/.env
docker images sec:bad --format '{{.Size}}'
# «после»:
docker run --rm sec:good -c "import os;print(os.getuid())"             # 10001
docker history --no-trunc sec:good | grep -ci hunter2                  # 0
docker images sec:good --format '{{.Size}}'
```

</details>

#### C2. Доказать, что секрет остаётся в слоях

1. Собери образ, где секрет копируется файлом и потом удаляется `RUN rm`.
2. Покажи, что внутри контейнера файла нет.
3. Извлеки секрет из слоёв образа (`docker save` + распаковка + grep).
4. Повтори с `--build-arg` — найди секрет в `docker history`.
5. Сделай правильно через `RUN --mount=type=secret` и покажи, что секрета нет нигде.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/10c2 && cd ~/docker-lab/10c2
echo "SUPER_SECRET_TOKEN_123" > token.txt
printf 'FROM alpine:3.20\nCOPY token.txt /token\nRUN rm -f /token\n' > Dockerfile.leak
docker build -q --no-cache -f Dockerfile.leak -t leak:1 .
docker run --rm leak:1 ls /token 2>&1 | head -1          # файла нет
docker save leak:1 -o img.tar && mkdir -p x && tar xf img.tar -C x
grep -r "SUPER_SECRET" x 2>/dev/null | head -1           # ⚠️ секрет найден в слое
rm -rf x img.tar

printf 'FROM alpine:3.20\nARG TOKEN\nRUN echo "use $TOKEN" > /dev/null\n' > Dockerfile.arg
docker build -q --no-cache -f Dockerfile.arg --build-arg TOKEN=SUPER_SECRET_TOKEN_123 -t leak:2 .
docker history --no-trunc leak:2 | grep -o SUPER_SECRET_TOKEN_123 | head -1   # ⚠️ в истории

cat > Dockerfile.ok <<'EOF'
# syntax=docker/dockerfile:1
FROM alpine:3.20
RUN --mount=type=secret,id=token sh -c 'wc -c < /run/secrets/token > /tmp/len'
EOF
docker build -q --no-cache -f Dockerfile.ok --secret id=token,src=token.txt -t leak:3 .
docker history --no-trunc leak:3 | grep -ci SUPER_SECRET        # 0 ✅
docker save leak:3 -o img3.tar && mkdir -p y && tar xf img3.tar -C y
grep -rc "SUPER_SECRET" y 2>/dev/null | grep -v ':0' | head -1 || echo "в слоях чисто ✅"
rm -rf y img3.tar token.txt
```

</details>

#### C3. Capabilities

1. Посмотри, какие capabilities есть у контейнера по умолчанию.
2. Запусти с `--cap-drop=ALL` и найди, что перестало работать (ping, chown, bind на 80).
3. Верни минимально необходимый набор для каждого случая.
4. Запусти nginx на порту 80 от непривилегированного пользователя (подсказка: `NET_BIND_SERVICE`).

<details><summary>Ответ</summary>

```bash
docker run --rm alpine grep Cap /proc/1/status
docker run --rm --cap-drop=ALL alpine ping -c1 8.8.8.8 2>&1 | head -1        # нельзя
docker run --rm --cap-drop=ALL --cap-add=NET_RAW alpine ping -c1 8.8.8.8 | head -1   # можно
docker run --rm --cap-drop=ALL alpine chown nobody /tmp 2>&1 | head -1       # нельзя
docker run --rm --cap-drop=ALL --cap-add=CHOWN alpine chown nobody /tmp && echo chown-ok
docker run -d --name np --user 101:101 --cap-drop=ALL --cap-add=NET_BIND_SERVICE \
  -p 8080:80 nginxinc/nginx-unprivileged:alpine 2>/dev/null || \
docker run -d --name np --cap-drop=ALL --cap-add=NET_BIND_SERVICE -p 8080:80 nginx:alpine
sleep 2; curl -sI localhost:8080 | head -1; docker rm -f np
```

</details>

#### C4. read-only контейнер

Переведи работающий nginx (или своё приложение) в режим `--read-only`:
найди все пути, куда ему нужно писать, и подключи их как tmpfs/volume.
Докажи, что в остальные места запись невозможна.

<details><summary>Ответ</summary>

```bash
docker run -d --name ro --read-only -p 8080:80 nginx:alpine; sleep 2
docker logs ro | tail -3                                  # ошибки записи в /var/cache/nginx
docker rm -f ro
docker run -d --name ro --read-only --tmpfs /var/cache/nginx --tmpfs /run --tmpfs /tmp \
  -p 8080:80 nginx:alpine; sleep 2
curl -sI localhost:8080 | head -1                          # 200 ✅
docker exec ro sh -c 'echo x > /usr/share/nginx/html/h.html' 2>&1 | head -1   # ro ✅
docker rm -f ro
```

</details>

#### C5. Опасные конфигурации (учебная VM!)

1. Покажи, как из контейнера с `--privileged -v /:/host` прочитать `/etc/shadow` хоста.
2. Покажи, как из контейнера с примонтированным `docker.sock` запустить новый контейнер
   и получить доступ к ФС хоста.
3. Сформулируй, что предложить разработчику вместо монтирования сокета.

<details><summary>Ответ</summary>

```bash
docker run --rm --privileged -v /:/host alpine head -2 /host/etc/shadow
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock docker:cli \
  docker run --rm -v /:/h alpine ls /h/root 2>/dev/null | head -3
# Вместо сокета: buildah/rootless BuildKit для сборки (kaniko архивирован в 2025), BuildKit как отдельный сервис,
# docker-socket-proxy с белым списком эндпоинтов (только read-only), отдельный build-хост.
```

</details>

#### C6. Сканирование в пайплайне

1. Просканируй `python:3.12` и `python:3.12-slim` — сравни количество HIGH/CRITICAL.
2. Настрой команду так, чтобы она возвращала ненулевой код при наличии CRITICAL
   (готовый шаг для CI).
3. Сгенерируй SBOM для своего образа.
4. Прогони `trivy config` по Dockerfile и `hadolint` — исправь найденное.

<details><summary>Ответ</summary>

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0 image --severity HIGH,CRITICAL --quiet python:3.12      | tail -3
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0 image --severity HIGH,CRITICAL --quiet python:3.12-slim | tail -3
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0 image --severity CRITICAL --exit-code 1 --quiet myapp:1.0; echo "CI exit: $?"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0 image --format cyclonedx --quiet myapp:1.0 > sbom.json; head -c 200 sbom.json
docker run --rm -v "$PWD":/w aquasec/trivy:0.74.0 config /w/Dockerfile
docker run --rm -i hadolint/hadolint < Dockerfile
```

</details>

#### C7. Аудит хоста

1. Посмотри состав группы `docker` и права на сокет.
2. Найди все запущенные контейнеры с `Privileged=true` или смонтированным `docker.sock`
   одной командой.
3. Найди контейнеры, работающие от root.
4. Найди контейнеры без лимита памяти.
5. (Бонус) Запусти `docker-bench-security` и разбери 5 замечаний.

<details><summary>Ответ</summary>

```bash
getent group docker; ls -l /var/run/docker.sock
docker ps -q | xargs -r docker inspect --format \
  '{{.Name}} priv={{.HostConfig.Privileged}} sock={{range .Mounts}}{{if eq .Source "/var/run/docker.sock"}}YES{{end}}{{end}}'
docker ps -q | xargs -r -I{} sh -c 'printf "%s user=%s\n" "$(docker inspect -f "{{.Name}}" {})" "$(docker exec {} id -u 2>/dev/null)"'
docker ps -q | xargs -r docker inspect --format '{{.Name}} mem={{.HostConfig.Memory}}' | grep ' mem=0'
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -v /var/lib:/var/lib:ro -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /etc:/etc:ro docker/docker-bench-security 2>/dev/null | head -40
cd ~ && rm -rf ~/docker-lab/10c2
```

</details>

---

### Блок D. Инциденты

**D1.** В публичном образе компании нашли AWS-ключи. Опиши порядок действий.

<details><summary>Ответ</summary>

(1) Немедленно **отозвать и перевыпустить** ключи (IAM), проверить логи использования
на предмет несанкционированной активности; (2) удалить образ и все его теги из registry
и зеркал/кэшей (помнить: скачавшие уже имеют копию); (3) найти источник — попал через
`COPY`, `ARG` или отсутствие `.dockerignore`; (4) пересобрать без секрета
(BuildKit secret/рантайм-переменные); (5) добавить в CI сканер секретов
(gitleaks/trivy secret) с блокировкой пайплайна; (6) оформить инцидент и разбор.

</details>

**D2.** На сервере обнаружен майнер, запущенный в контейнере. Известно, что у CI-раннера
был примонтирован `docker.sock`. Восстанови цепочку и предложи защиту.

<details><summary>Ответ</summary>

Через сокет контейнер может управлять демоном (root): скомпрометированная зависимость
или чужой merge request в пайплайне позволил запустить привилегированный контейнер,
закрепиться на хосте и запустить майнер. Защита: убрать монтирование сокета; сборка через
buildah/rootless BuildKit без привилегий (kaniko архивирован в 2025); socket-proxy с ограниченным API, если доступ
действительно нужен; изолированные одноразовые раннеры; запрет запуска пайплайнов
из форков без апрува; мониторинг аномальной нагрузки.

</details>

**D3.** Security-команда требует, чтобы все контейнеры работали не от root.
Приложение при старте пишет в `/var/log/app` и слушает порт 80. Как переделать?

<details><summary>Ответ</summary>

Создать пользователя в образе, заранее создать `/var/log/app` и выдать права
(`mkdir -p /var/log/app && chown -R app:app /var/log/app` **до** `USER`), а лучше — писать
логи в stdout. Порт: слушать 8080 и публиковать `-p 80:8080`; если 80 обязателен внутри —
`--cap-add=NET_BIND_SERVICE` или образ вида `nginx-unprivileged`. Для volume — named volume
(наследует права) либо согласовать UID.

</details>

**D4.** Сканер показывает 200 CVE в образе. Приложение — маленькое Go-бинарное.
Что не так и как свести к нулю?

<details><summary>Ответ</summary>

Уязвимости почти наверняка не в приложении, а в **жирной базе** (`ubuntu`/`debian`
с сотней пакетов). Для Go-бинаря: multi-stage + `FROM scratch` или
`gcr.io/distroless/static:nonroot`, `CGO_ENABLED=0`, копирование только бинарника и
`ca-certificates` — образ на единицы мегабайт и, как правило, ноль CVE.

</details>

**D5.** После перехода на non-root приложение падает с `Permission denied` при записи
в смонтированный volume. Три способа решить.

<details><summary>Ответ</summary>

(1) Использовать named volume вместо bind (докер выставит владельца из образа);
(2) `chown` каталога на хосте под UID контейнера; (3) запускать контейнер с `--user`,
совпадающим с владельцем каталога; дополнительно — `fsGroup`/`supplementalGroups`
в Kubernetes или init-контейнер, выставляющий права.

</details>

**D6.** Разработчики просят `--privileged`, потому что «иначе не работает».
Как выяснить, что им реально нужно, и предложить точечное решение?

<details><summary>Ответ</summary>

Выяснить конкретное действие, которое падает (ошибка + strace/логи), и отобразить
его на минимальную привилегию: доступ к устройству → `--device`; монтирование ФС →
`--cap-add=SYS_ADMIN` только этому шагу или вынести операцию из контейнера; изменение
sysctl → `--sysctl`; профилирование → `--cap-add=SYS_PTRACE`; работа с сетью →
`NET_ADMIN`. Часто «нужен privileged» означает лишь одну capability или один `--device`.

</details>

**D7.** В образе прода нашли уязвимость в базовом образе, вышедшую **после** релиза.
Как организовать процесс, чтобы такое находилось быстро?

<details><summary>Ответ</summary>

Регулярный автоматический rescan образов в registry (Harbor/ECR/trivy по расписанию),
подписка на обновления базовых образов и автоматические PR (Renovate/Dependabot для
`FROM`-тегов), периодическая пересборка релизных образов без изменения кода,
SBOM для быстрого ответа «затронуты ли мы», алерты по новым CRITICAL для образов,
которые сейчас в проде.

</details>

**D8.** Кто-то подменил образ в registry под тем же тегом. Как это обнаружить
и как сделать невозможным?

<details><summary>Ответ</summary>

Обнаружить: сравнить дайджест работающего образа с ожидаемым
(<code v-pre>docker image inspect --format '{{index .RepoDigests 0}}'</code> vs зафиксированный в релизе),
проверить журнал аудита registry, проверить подпись `cosign verify`.
Сделать невозможным: immutable tags, деплой по дайджесту, подпись образов и её обязательная
проверка admission-контроллером, RBAC (push только у CI, робот-аккаунты), аудит и алерты
на перезапись тегов.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Насколько контейнеры изолированы и безопасны?

<details><summary>Ответ</summary>

Изоляция обеспечивается ядром (namespaces/cgroups/capabilities/seccomp/LSM), но ядро общее —
уязвимость ядра или неверная конфигурация ведут к побегу. Для недоверенного кода —
VM, gVisor, Kata.

</details>

**2.** Почему нельзя запускать контейнер от root?

<details><summary>Ответ</summary>

Root в контейнере — это UID 0 на хосте: при побеге или через монтирования он даёт доступ
к хосту; кроме того, это нарушает политики (PSS) и упрощает эксплуатацию уязвимостей.

</details>

**3.** Что такое capabilities и как их ограничить?

<details><summary>Ответ</summary>

Дробление прав root на отдельные привилегии. Ограничение: `--cap-drop=ALL` и точечный
`--cap-add`; в k8s — `securityContext.capabilities`.

</details>

**4.** Как передать секрет в образ?

<details><summary>Ответ</summary>

В сборку — BuildKit secret (`RUN --mount=type=secret`), в рантайм — переменные/файлы из
внешнего хранилища. Никогда — `ARG`, `ENV`, `COPY` в образ.

</details>

**5.** Чем опасен `--privileged`?

<details><summary>Ответ</summary>

Снимает практически всю защиту: все capabilities, доступ к устройствам хоста,
отключение seccomp/AppArmor — фактически контейнер получает хост.

</details>

**6.** Чем опасно монтирование `/var/run/docker.sock`?

<details><summary>Ответ</summary>

Сокет — API демона, работающего от root: из контейнера можно запустить привилегированный
контейнер с монтированием `/` и получить полный доступ к хосту.

</details>

**7.** Как сканировать образы на уязвимости?

<details><summary>Ответ</summary>

`trivy image`, `docker scout cves`, `grype`, встроенные сканеры registry (Harbor, ECR);
запускать в CI с падением сборки и периодически пересканировать опубликованные образы.

</details>

**8.** Что такое rootless docker?

<details><summary>Ответ</summary>

Docker, работающий без root-прав через user namespaces: root в контейнере отображается
в непривилегированного пользователя хоста. Снижает риск компрометации хоста;
есть ограничения по портам, сетям и storage.

</details>

**9.** Какие best practice'ы безопасности контейнеров ты знаешь?

<details><summary>Ответ</summary>

Минимальная доверенная база и пин версий, multi-stage, non-root, `--read-only`,
`cap-drop=ALL`, `no-new-privileges`, лимиты ресурсов, отсутствие секретов в образе,
не публиковать лишние порты, сканирование и подпись, обновление базовых образов,
не давать доступ к docker.sock.

</details>

**10.** Как обеспечить целостность образа от сборки до прода?

<details><summary>Ответ</summary>

Воспроизводимая сборка → скан → подпись (cosign) → push с immutable-тегами →
деплой по дайджесту → проверка подписи admission-контроллером → аудит и rescan.

</details>

---

### 🎯 Чек-лист

- [ ] Мои образы не запускаются от root
- [ ] Я доказал себе, что секрет из слоя достаётся, и больше так не делаю
- [ ] Умею запускать контейнер с `--read-only`, `cap-drop=ALL`, `no-new-privileges`
- [ ] Знаю, почему `--privileged` и docker.sock — это отдача хоста, и что предлагать взамен
- [ ] Встроил trivy и hadolint в пайплайн с падением сборки
- [ ] Понимаю, зачем подписывать образы и деплоить по дайджесту
- [ ] Ставлю лимиты ресурсов на все контейнеры
- [ ] Знаю про rootless docker и его ограничения
