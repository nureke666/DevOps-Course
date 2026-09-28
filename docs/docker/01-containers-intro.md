---
title: "01. Контейнеры и архитектура Docker"
description: "Контейнер как процесс Linux, namespaces, cgroups, архитектура docker: CLI → API → dockerd → containerd → runc"
---

# 01. Контейнеры: что это на самом деле + архитектура Docker

> Роадмап «Просто DevOps» → 3. Docker → Теория → Контейнеры → Архитектура
> **После темы ты умеешь:** объяснить разницу контейнера и виртуалки на уровне ядра,
> назвать технологии изоляции, нарисовать путь от `docker run` до процесса,
> и сказать, зачем существуют Podman/containerd/Buildah.

---

## 🗺️ Схема: виртуализация vs контейнеризация

```text:no-line-numbers
        ВИРТУАЛИЗАЦИЯ (VM)                     КОНТЕЙНЕРИЗАЦИЯ
┌───────────────────────────────┐    ┌───────────────────────────────┐
│  App A    │  App B            │    │  App A    │  App B            │
├───────────┼───────────────────┤    ├───────────┼───────────────────┤
│ bins/libs │ bins/libs         │    │ bins/libs │ bins/libs         │
├───────────┼───────────────────┤    ├───────────┴───────────────────┤
│ ГОСТЕВОЕ  │ ГОСТЕВОЕ ЯДРО     │ ←  │   Container Runtime           │
│ ЯДРО+ОС   │ +ОС (сотни МБ/ГБ) │    │   (containerd/runc)           │
├───────────┴───────────────────┤    ├───────────────────────────────┤
│        Гипервизор (KVM)       │    │        ОДНО ЯДРО ХОСТА        │ ← ключевое отличие
├───────────────────────────────┤    ├───────────────────────────────┤
│        ЯДРО ХОСТА / ОС        │    │        ОС ХОСТА               │
├───────────────────────────────┤    ├───────────────────────────────┤
│           ЖЕЛЕЗО              │    │           ЖЕЛЕЗО              │
└───────────────────────────────┘    └───────────────────────────────┘

  Старт: десятки секунд                 Старт: миллисекунды
  Вес:   гигабайты                      Вес:   мегабайты
  Изоляция: аппаратная (сильная)        Изоляция: ядром (слабее)
  Своё ядро у каждой VM                 Ядро ОБЩЕЕ → нельзя Windows-контейнер на Linux
```

**Формулировка для собеса (вопрос №1 в роадмапе):**
> Виртуализация эмулирует **железо**: гипервизор даёт каждой VM своё ядро и свою ОС.
> Контейнеризация виртуализирует **ОС**: контейнеры — это обычные процессы хоста,
> которым ядро через namespaces показало урезанную картину мира, а через cgroups
> ограничило ресурсы. Отсюда: контейнер легче и быстрее, но изоляция слабее
> (общее ядро = общая поверхность атаки, эксплойт в ядре пробивает все контейнеры),
> и нельзя запустить ОС с другим ядром.

**Контейнер — это НЕ мини-виртуалка.** Это процесс. Проверяется одной командой:

```bash
docker run -d --name demo nginx
ps aux | grep nginx            # ← процессы контейнера ВИДНЫ на хосте как обычные процессы
sudo ls -l /proc/$(pgrep -f "nginx: master" | head -1)/ns/    # его namespaces
```

---

## 1. За счёт чего работает изоляция (вопрос №2 в роадмапе)

Три кита + обвес:

### Namespaces — «что процесс видит»

| Namespace | Что изолирует | Проверить |
|-----------|---------------|-----------|
| `pid` | Дерево процессов. Внутри контейнера главный процесс = **PID 1** | `docker exec c ps aux` |
| `net` | Сетевые интерфейсы, IP, порты, таблицы маршрутизации, iptables | `docker exec c ip a` |
| `mnt` | Точки монтирования, своя корневая ФС | `docker exec c mount` |
| `uts` | Hostname и domainname | `docker exec c hostname` |
| `ipc` | Разделяемая память, семафоры, очереди сообщений | `ipcs` |
| `user` | Маппинг UID/GID (root в контейнере ≠ root на хосте) | rootless/userns-remap |
| `cgroup` | Прячет реальные пути cgroup хоста | `cat /proc/1/cgroup` |
| `time` | Смещение системного времени (ядро 5.6+, докером почти не используется) | — |

```bash
# Namespaces голыми руками, без докера — «докер за 30 секунд»
sudo unshare --pid --fork --mount-proc --uts --net --mount bash
hostname mini-container
ps aux            # видно только bash и ps → PID namespace работает
ip a              # только lo → net namespace работает
exit
```

### cgroups (control groups) — «сколько процесс может взять»

Ограничивают и учитывают CPU, память, дисковый I/O, PIDs, сеть.

```bash
docker run -d --name lim --memory=100m --cpus=0.5 --pids-limit=50 nginx
docker inspect lim --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'

# cgroups v2 (современные системы): всё в одной иерархии
cat /sys/fs/cgroup/system.slice/docker-*.scope/memory.max     2>/dev/null
cat /sys/fs/cgroup/docker/*/memory.max                        2>/dev/null
docker info | grep -i "cgroup"        # Cgroup Driver: systemd | Version: 2
```

> Превысил `--memory` → **OOM-killer убивает процесс**, контейнер падает с кодом `137`.
> Это самая частая «загадочная» смерть контейнера (см. тему 11).

### Capabilities, seccomp, LSM — «что процессу разрешено делать»

| Механизм | Что делает |
|----------|-----------|
| **Capabilities** | Дробит права root на ~40 кусков. Докер по умолчанию оставляет 14 из них, убирая опасные (`SYS_ADMIN`, `SYS_MODULE`, `SYS_TIME`…) |
| **seccomp** | Фильтр системных вызовов. Дефолтный профиль докера блокирует ~44 syscall из ~350 |
| **AppArmor / SELinux** | MAC-политики поверх обычных прав (`docker-default` профиль) |
| **`no-new-privileges`** | Запрещает повышение прав через setuid-бинарники внутри контейнера |

### Файловая система: chroot → pivot_root + OverlayFS

Контейнер получает свой корень (`/`) из образа: слои образа монтируются read-only,
сверху — тонкий writable-слой контейнера (подробно в теме 02).

**Итоговая формулировка для собеса:**
> Изоляция контейнеров обеспечивается механизмами ядра Linux: **namespaces** (что видно),
> **cgroups** (сколько ресурсов), **capabilities + seccomp + AppArmor/SELinux** (что можно делать),
> **pivot_root/OverlayFS** (своя корневая ФС). Docker — это удобная обёртка над этими
> возможностями, а не отдельная технология изоляции.

---

## 2. Архитектура Docker

```text:no-line-numbers
 ┌──────────────────┐    docker run nginx
 │  Docker CLI      │──────────┐
 │  (docker client) │          │ HTTP-запрос к Docker API
 └──────────────────┘          │ по unix-сокету /var/run/docker.sock
                               │ (или tcp://, если включён удалённый доступ)
                               ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  dockerd — Docker Daemon (главный процесс, работает от root) │
 │  образы · сети · тома · сборка · API                         │
 └───────────────────────────┬──────────────────────────────────┘
                             │ gRPC
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  containerd — высокоуровневый runtime (CRI-совместимый)      │
 │  жизненный цикл контейнеров, pull образов, снапшоты          │
 └───────────────────────────┬──────────────────────────────────┘
                             │ на каждый контейнер
                             ▼
                  ┌─────────────────────┐
                  │  containerd-shim    │ ← держит контейнер живым,
                  └──────────┬──────────┘   если dockerd перезапустили
                             ▼
                  ┌─────────────────────┐
                  │  runc (OCI runtime) │ ← создаёт namespaces/cgroups,
                  └──────────┬──────────┘   делает exec и УМИРАЕТ
                             ▼
                  ┌─────────────────────┐
                  │  Процесс приложения │ ← обычный процесс ядра хоста
                  └─────────────────────┘
```

| Компонент | Роль |
|-----------|------|
| **Docker Client (CLI)** | Интерфейс командной строки. Сам ничего не запускает — только шлёт запросы в API |
| **Docker API** | REST-интерфейс общения CLI и демона (сокет `/var/run/docker.sock`) |
| **Docker Daemon (dockerd)** | Главный процесс: управляет образами, контейнерами, сетями, томами, сборкой |
| **containerd** | Управляет жизненным циклом контейнеров; используется и Kubernetes'ом напрямую |
| **runc** | Эталонная реализация OCI Runtime Spec: собственно создаёт контейнер |
| **shim** | Прослойка, благодаря которой контейнеры переживают рестарт демона |

```bash
# Увидеть это вживую
systemctl status docker containerd
pstree -p $(pgrep -x dockerd) | head
docker run -d --name a nginx && pstree -p $(pgrep -f containerd-shim | head -1)

# CLI действительно ходит в API — можно обойтись без него
curl --unix-socket /var/run/docker.sock http://localhost/version | jq .
curl --unix-socket /var/run/docker.sock http://localhost/containers/json | jq '.[].Names'
```

> ⚠️ Отсюда сразу вывод по безопасности: кто имеет доступ к `docker.sock` — тот root на хосте.
> Никогда не монтируй сокет в контейнер «просто чтобы работало» (тема 10).

**Клиент-серверность на практике:** `DOCKER_HOST=ssh://user@server docker ps` покажет
контейнеры удалённой машины — CLI локальный, демон удалённый.

---

## 3. OCI — почему всё это совместимо

**Open Container Initiative** — стандарты, благодаря которым образ, собранный докером,
запускается в Kubernetes через containerd, а образ из Buildah работает в докере.

| Спецификация | О чём |
|--------------|-------|
| **image-spec** | Формат образа: слои, манифест, конфиг |
| **runtime-spec** | Как runtime должен запускать контейнер (`config.json`, bundle) |
| **distribution-spec** | Как registry отдаёт и принимает образы (HTTP API) |

```text:no-line-numbers
Dockerfile ──build──► OCI image ──push──► Registry ──pull──► любой OCI runtime
   (docker/buildah/kaniko)                              (docker/containerd/CRI-O/podman)
```

---

## 4. Альтернативы Docker (роадмап: «не одним докером едины»)

| Инструмент | Что это | Зачем нужен / чем лучше |
|------------|---------|-------------------------|
| **containerd** | Низкоуровневый runtime, вынут из докера | Стандарт для Kubernetes. Дефолтный CRI начиная с k8s 1.24 (после отказа от dockershim) |
| **CRI-O** | Runtime только под Kubernetes | Минимальный, ничего лишнего; используется в OpenShift |
| **Podman** | Полная замена CLI докера (`alias docker=podman`) | **Без демона** и **rootless из коробки**, умеет **pods** (как в k8s), генерит systemd-юниты. Дефолт в RHEL/Fedora |
| **Buildah** | Только сборка образов | Собирает без демона и без root; можно собирать скриптом, а не Dockerfile'ом |
| **Skopeo** | Работа с образами в registry | Копировать/инспектировать/подписывать образы **без скачивания и без демона** |
| **Kaniko** (архивирован в 2025) | Сборка образов внутри Kubernetes | Собирал в поде без привилегий и без docker.sock — была классика для CI в k8s; upstream заархивирован, жив только форк Chainguard (security-фиксы) |
| **BuildKit** | Современный движок сборки (внутри докера и отдельно — `buildkitd`) | Параллельная сборка, кэш-маунты, секреты при сборке, multi-arch; rootless-режим — замена kaniko в CI |
| **nerdctl** | CLI для containerd с синтаксисом докера | Работать с containerd так же, как с докером |
| **gVisor / Kata** | Усиленные runtime'ы | Изоляция ближе к VM (user-space ядро / микро-VM) для недоверенного кода |

**Ответ на собесе «почему не докер?»:**
безопасность (демон от root ↔ daemonless/rootless podman),
Kubernetes (ему нужен CRI — containerd/CRI-O, docker-shim удалён),
сборка в CI без привилегий (rootless BuildKit/buildah; kaniko архивирован в 2025),
и просто лицензия/политика компании (Docker Desktop платный для крупных компаний).

---

## 🔧 Установка и первые команды

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

docker version          # Client + Server (API version, версии containerd/runc)
docker info             # ⭐ storage driver, cgroup version, кол-во образов/контейнеров, Docker Root Dir
docker system df        # сколько места занято
docker run --rm hello-world
```

Что произошло при `docker run hello-world`:
```text:no-line-numbers
CLI → API → dockerd: образа локально нет
           → pull из Docker Hub (registry)
           → создать контейнер из образа
           → containerd → shim → runc: namespaces+cgroups+rootfs
           → запустить процесс, вывести stdout в твой терминал
           → процесс завершился → контейнер в статусе Exited → --rm удалил его
```

---

## 💼 Как это в DevOps

- **Главная ценность контейнера — воспроизводимость.** «У меня работает» умирает: образ содержит
  приложение вместе с зависимостями и версией рантайма; он одинаков на ноуте, в CI и в проде.
- **Иммутабельность:** образ не правят — пересобирают. Контейнер считается одноразовым:
  упал — перезапустили новый из того же образа. Данные не хранят внутри (тема 07).
- **Docker — вход в Kubernetes.** В k8s ты почти не используешь docker CLI, но каждый под — это
  контейнеры из образов, которые кто-то собрал и положил в registry. Понимание слоёв, тегов
  и registry там нужно ежедневно.
- **Где в пайплайне:** `git push` → CI собирает образ → тег → push в registry → деплой
  (k8s/compose) тянет образ по тегу/дайджесту.

---

## 🧪 Мини-лаба: доказать, что контейнер — это процесс

```bash
# 1. Запустить и найти на хосте
docker run -d --name lab01 --memory=64m --cpus=0.5 nginx
PID=$(docker inspect -f '{{.State.Pid}}' lab01); echo "PID на хосте: $PID"
ps -o pid,ppid,user,comm -p $PID
sudo cat /proc/$PID/cgroup

# 2. Namespaces: свои у контейнера, общие с хостом — нет
sudo ls -l /proc/$PID/ns/
sudo ls -l /proc/1/ns/          # сравни номера инодов: разные = изолирован

# 3. Внутри контейнера главный процесс — PID 1
docker exec lab01 ps aux
docker exec lab01 hostname      # uts namespace
docker exec lab01 ip a          # net namespace: свой eth0 и IP

# 4. Войти в namespaces контейнера с хоста, без docker exec
sudo nsenter -t $PID -n ip a            # только сетевой namespace
sudo nsenter -t $PID -a hostname 2>/dev/null || sudo nsenter -t $PID -m -u -i -n -p hostname

# 5. cgroups ограничивают реально
docker exec lab01 cat /sys/fs/cgroup/memory.max 2>/dev/null || \
docker exec lab01 cat /sys/fs/cgroup/memory/memory.limit_in_bytes
docker stats --no-stream lab01

# 6. OOM в прямом эфире (код выхода 137)
docker run --rm --memory=20m python:3-alpine python -c "x=' '*100_000_000" ; echo "exit=$?"

# 7. Архитектура: запрос мимо CLI
curl -s --unix-socket /var/run/docker.sock http://localhost/containers/json | jq '.[].Image'

# 8. Уборка
docker rm -f lab01
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker version` | Версии клиента и **сервера** (демона) |
| `docker info` | Storage driver, cgroup driver/version, root dir, счётчики |
| `docker system df` | Сколько места едят образы/контейнеры/тома/кэш |
| <code v-pre>docker inspect -f '{{.State.Pid}}' NAME</code> | PID главного процесса контейнера на хосте |
| `ps aux \| grep <процесс>` | Процессы контейнера видны с хоста |
| `sudo ls -l /proc/PID/ns/` | Namespaces процесса |
| `sudo nsenter -t PID -n ip a` | Войти в сетевой namespace контейнера с хоста |
| `sudo unshare --pid --fork --mount-proc bash` | Сделать «контейнер» руками |
| `docker stats` | Потребление ресурсов в реальном времени |
| `curl --unix-socket /var/run/docker.sock http://localhost/version` | Сходить в Docker API напрямую |

---

## 🧠 Что запомнить

1. **Контейнер — это процесс Linux**, а не лёгкая виртуалка. Общее ядро с хостом.
2. Изоляция = **namespaces** (видимость) + **cgroups** (ресурсы) + **capabilities/seccomp/LSM** (права)
   + **pivot_root/OverlayFS** (своя корневая ФС).
3. VM: своё ядро, сильная изоляция, гигабайты, секунды старта.
   Контейнер: общее ядро, изоляция слабее, мегабайты, миллисекунды.
4. Архитектура: **CLI → Docker API (сокет) → dockerd → containerd → shim → runc → процесс**.
5. Демон работает от **root**; доступ к `/var/run/docker.sock` = root на хосте.
6. **OCI** (image/runtime/distribution spec) делает образы переносимыми между докером,
   containerd, podman, CRI-O.
7. Внутри контейнера приложение — **PID 1**, а значит само отвечает за сигналы и зомби-процессы (тема 06).
8. Альтернативы не «лучше/хуже», а под задачу: containerd/CRI-O — для k8s, podman — daemonless+rootless,
   buildah/rootless BuildKit — сборка без привилегий (kaniko архивирован в 2025), skopeo — работа
   с registry, gVisor/Kata — усиленная изоляция.
9. Контейнер **одноразовый**: состояние — наружу (volumes/БД), образ — иммутабельный.
10. Код выхода **137** = убит SIGKILL, чаще всего OOM из-за `--memory`.

---

## Задачи

> Уборка после лаб: `docker rm -f $(docker ps -aq) 2>/dev/null; docker system prune -f`
> ⭐ Блоки A и E — это ровно первые два вопроса из роадмапа по собесам. Отвечай вслух, не про себя.

---

### Блок A. Теория

**A1.** Объясни разницу виртуализации и контейнеризации так, как будешь отвечать на собесе.
Три ключевых отличия минимум.

<details><summary>Ответ</summary>

Виртуализация эмулирует железо: гипервизор даёт каждой VM **собственное ядро** и полную ОС.
Контейнеризация виртуализирует ОС: контейнер — **процесс хоста**, изолированный namespaces и
ограниченный cgroups, ядро **общее**. Отличия: (1) ядро своё vs общее; (2) вес гигабайты vs мегабайты
и старт секунды vs миллисекунды; (3) изоляция аппаратная (сильная) vs ядром (слабее, общая
поверхность атаки).

</details>

**A2.** Почему нельзя запустить Windows-контейнер на Linux-хосте, а Windows-VM — можно?

<details><summary>Ответ</summary>

Контейнер использует ядро хоста, а бинарники Windows требуют ядра Windows и его syscall'ов.
VM же несёт своё ядро, гипервизор даёт ей виртуальное железо — поэтому гостевая ОС может быть любой.

</details>

**A3.** За счёт каких технологий ядра Linux обеспечивается изоляция контейнеров? Назови 4 группы.

<details><summary>Ответ</summary>

(1) namespaces — изоляция видимости; (2) cgroups — ограничение и учёт ресурсов;
(3) capabilities + seccomp + AppArmor/SELinux — ограничение разрешённых действий и syscall'ов;
(4) pivot_root/chroot + OverlayFS — собственная корневая файловая система.

</details>

**A4.** Что изолируют namespaces: `pid`, `net`, `mnt`, `uts`, `ipc`, `user`? По одной фразе на каждый.

<details><summary>Ответ</summary>

`pid` — дерево процессов; `net` — интерфейсы, IP, порты, маршруты, iptables;
`mnt` — точки монтирования и своя ФС; `uts` — hostname/domainname;
`ipc` — разделяемая память и семафоры; `user` — маппинг UID/GID (root внутри ≠ root снаружи).

</details>

**A5.** Что делают cgroups и чем они отличаются по задаче от namespaces?

<details><summary>Ответ</summary>

cgroups ограничивают и учитывают **ресурсы** (CPU, память, I/O, кол-во процессов).
Namespaces отвечают на вопрос «что процесс видит», cgroups — «сколько он может взять».
Это ортогональные механизмы, контейнер использует оба.

</details>

**A6.** Что такое capabilities и зачем они нужны, если есть обычные права root?

<details><summary>Ответ</summary>

Capabilities дробят всемогущество root примерно на 40 отдельных привилегий
(`NET_BIND_SERVICE`, `NET_RAW`, `SYS_ADMIN`, `CHOWN`…). Процесс может получить только нужную часть
прав вместо полного root. Docker по умолчанию оставляет контейнеру урезанный набор (~14),
убирая самые опасные.

</details>

**A7.** Нарисуй словами путь от `docker run nginx` до работающего процесса. Назови все компоненты.

<details><summary>Ответ</summary>

`docker run nginx` → CLI формирует HTTP-запрос к **Docker API** через сокет
`/var/run/docker.sock` → **dockerd** проверяет наличие образа (нет — тянет из registry), создаёт
конфиг контейнера → по gRPC зовёт **containerd** → containerd поднимает **containerd-shim** →
shim вызывает **runc** → runc создаёт namespaces, cgroups, монтирует rootfs из слоёв и делает
`exec` процесса → runc завершается, процесс остаётся под shim'ом.

</details>

**A8.** Чем занимается `containerd`, а чем `runc`? Почему runc завершается сразу после старта контейнера?

<details><summary>Ответ</summary>

containerd — высокоуровневый runtime: жизненный цикл контейнеров, загрузка образов,
снапшоты, передача в runc. runc — низкоуровневый: читает OCI-бандл (`config.json` + rootfs),
создаёт namespaces/cgroups и делает `exec`. После `exec` его работа окончена — процесс контейнера
уже запущен, держать его не нужно, поэтому runc выходит.

</details>

**A9.** Зачем нужен `containerd-shim`?

<details><summary>Ответ</summary>

shim становится родителем процесса контейнера и держит его stdio и код выхода. Благодаря
ему контейнеры **не умирают при перезапуске dockerd/containerd**, а PID 1 контейнера не становится
сиротой у init хоста.

</details>

**A10.** Что такое Docker API и где он слушает по умолчанию?

<details><summary>Ответ</summary>

Docker API — REST-интерфейс демона, которым пользуется CLI. По умолчанию слушает
unix-сокет `/var/run/docker.sock`; может слушать TCP (`tcp://0.0.0.0:2375/2376`) — без TLS это
дыра, через которую машину забирают за минуту.

</details>

**A11.** Почему добавление пользователя в группу `docker` эквивалентно выдаче root-прав на хосте?

<details><summary>Ответ</summary>

Через сокет можно попросить демон (работающий от root) запустить контейнер
с `--privileged` и смонтированным `/` хоста — и получить полный доступ к хостовой ФС:
`docker run -v /:/host --privileged alpine chroot /host sh`. Отдельных проверок прав у API нет.

</details>

**A12.** Что такое OCI? Назови три спецификации и что каждая описывает.

<details><summary>Ответ</summary>

Open Container Initiative — набор стандартов: **image-spec** (формат образа: слои,
манифест, конфиг), **runtime-spec** (как runtime запускает контейнер из бандла),
**distribution-spec** (HTTP-API registry). Благодаря им образ докера запускается в containerd,
podman, CRI-O и наоборот.

</details>

**A13.** Podman, Buildah, Skopeo, containerd, CRI-O, kaniko — по одному предложению, зачем каждый.

<details><summary>Ответ</summary>

Podman — daemonless/rootless замена docker CLI, умеет pods;
Buildah — сборка образов без демона и root;
Skopeo — копирование/инспекция/подпись образов в registry без скачивания;
containerd — runtime-стандарт, в том числе для Kubernetes;
CRI-O — минимальный runtime специально под Kubernetes;
kaniko — сборка образов внутри Kubernetes-пода без привилегий (архивирован в 2025, жив только
форк Chainguard с security-фиксами; для новых пайплайнов — rootless BuildKit или buildah).

</details>

**A14.** Kubernetes «отказался от Docker» — что это на самом деле значило?

<details><summary>Ответ</summary>

Kubernetes убрал **dockershim** — прослойку для общения с докером, т.к. появился стандарт CRI,
а Docker его не реализует (containerd внутри докера — реализует). Образы, собранные докером,
работают как работали: они OCI-совместимые. Перестали использовать Docker **как runtime на нодах**,
а не «образы Docker».

</details>

**A15.** Какой PID у главного процесса внутри контейнера и почему это важно?

<details><summary>Ответ</summary>

PID 1. Важно потому, что PID 1 в Linux особенный: он обязан пересылать сигналы дочерним
процессам и «усыновлять» зомби. Если приложение не умеет этого (типично для shell-скриптов и
`CMD` в shell-форме), контейнер не реагирует на `docker stop` и убивается SIGKILL через 10 секунд
(тема 06).

</details>

**A16.** Контейнер «легче» виртуалки. За счёт чего конкретно — назови две причины.

<details><summary>Ответ</summary>

(1) Нет гостевого ядра и гостевой ОС — не нужно грузить и держать в памяти второй kernel,
systemd, драйверы; (2) слои образа переиспользуются и монтируются copy-on-write, одинаковые слои
на диске хранятся один раз.

</details>

**A17.** В каком случае контейнеров **недостаточно** и нужна именно виртуалка? Три ситуации.

<details><summary>Ответ</summary>

(1) Нужна другая ОС/ядро (Windows-нагрузка на Linux-хосте, другая версия ядра или
kernel-модуль); (2) нужна сильная изоляция для недоверенного кода/мультитенантности
(или тогда gVisor/Kata); (3) нагрузка, требующая своего ядра и системных настроек:
свои модули ядра, специфичный sysctl, эмуляция железа, legacy-софт целиком с ОС.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker version
B2.  docker info | grep -i cgroup
B3.  docker system df
B4.  docker inspect -f '{{.State.Pid}}' web
B5.  sudo ls -l /proc/$(docker inspect -f '{{.State.Pid}}' web)/ns/
B6.  sudo nsenter -t 12345 -n ip a
B7.  sudo unshare --pid --fork --mount-proc bash
B8.  docker run --rm --memory=20m alpine free -m
B9.  docker stats --no-stream
B10. curl -s --unix-socket /var/run/docker.sock http://localhost/containers/json
B11. DOCKER_HOST=ssh://user@srv docker ps
B12. docker run --rm --cap-drop=ALL alpine id
B13. pstree -p $(pgrep -x dockerd)
B14. docker run --rm alpine cat /proc/1/cgroup
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Версии клиента и сервера отдельно. Если блок Server отсутствует — демон не запущен
     или нет прав на сокет.
B2.  Показывает Cgroup Driver (systemd/cgroupfs) и Cgroup Version (1/2) — важно для k8s и лимитов.
B3.  Сводка занятого места: образы, контейнеры, тома, build cache, сколько из этого reclaimable.
B4.  PID главного процесса контейнера web на хосте.
B5.  Список namespaces этого процесса (символические ссылки с номерами инодов).
B6.  Выполнить ip a внутри сетевого namespace процесса 12345 — увидеть интерфейсы контейнера
     с хоста, без docker exec (работает даже если в образе нет ip).
B7.  Создать новый PID+mount namespace с перемонтированным /proc — «ручной контейнер»:
     внутри ps покажет только свои процессы.
B8.  Запустить alpine с лимитом 20 МБ. free -m при этом покажет память ХОСТА —
     классическая ловушка (см. D4).
B9.  Разовый снимок потребления CPU/памяти/сети/IO всеми контейнерами.
B10. Список контейнеров в JSON напрямую из Docker API, минуя CLI.
B11. Локальный CLI управляет УДАЛЁННЫМ демоном по SSH — показывает клиент-серверность.
B12. Запустить alpine, сняв все capabilities. id отработает (не требует привилегий),
     а вот ping/chown — уже нет.
B13. Дерево процессов демона: видно containerd-shim'ы дочерних контейнеров.
B14. Показать cgroup-путь PID 1 внутри контейнера — видно, что процесс помещён в свою группу.
```

</details>

**B15.** Чем `docker exec -it c sh` принципиально отличается от `nsenter -t PID -a sh` с хоста?

<details><summary>Ответ</summary>

`docker exec` просит **демон** создать новый процесс внутри контейнера: применяются
все его настройки (user, env, рабочая директория, seccomp, cgroup-лимиты). `nsenter` — это
инструмент хоста: ты вручную входишь в выбранные namespaces, **минуя докер и его лимиты/профили**,
можешь войти только в часть namespaces и использовать бинарники хоста (полезно, когда образ
`distroless`/`scratch` и внутри вообще нет shell).

</details>

---

### Блок C. Практика

#### C1. 🔑 Контейнер — это процесс (главное задание)

Запусти `nginx` в контейнере и **докажи пятью разными способами**, что это обычный процесс хоста
в namespaces, а не виртуальная машина:

1. Найди PID процесса контейнера на хосте и покажи его в `ps` хоста.
2. Покажи, что namespaces контейнера отличаются от namespaces PID 1 хоста (сравни иноды).
3. Покажи, что PID этого же процесса **внутри** контейнера — 1.
4. Войди в сетевой namespace контейнера с хоста через `nsenter`, не используя `docker exec`.
5. Покажи cgroup контейнера и его лимит памяти.

<details><summary>Ответ</summary>

```bash
docker run -d --name web --memory=128m nginx
PID=$(docker inspect -f '{{.State.Pid}}' web)

ps -o pid,ppid,user,comm -p $PID                 # 1) процесс виден на хосте
sudo ls -l /proc/$PID/ns/ ; sudo ls -l /proc/1/ns/   # 2) иноды namespaces отличаются
docker exec web ps aux | head -3                 # 3) внутри тот же nginx — PID 1
sudo nsenter -t $PID -n ip a                     # 4) сетевой namespace контейнера с хоста
sudo cat /proc/$PID/cgroup                       # 5) cgroup
cat /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' web).scope/memory.max \
  2>/dev/null || docker exec web cat /sys/fs/cgroup/memory.max
```

</details>

#### C2. Контейнер руками, без докера

Через `unshare` создай окружение с собственными PID, UTS и mount namespace.
Внутри: смени hostname, покажи `ps aux` (должно быть 2-3 процесса), выйди.
Объясни, почему без `--mount-proc` в `ps` виден весь хост.

<details><summary>Ответ</summary>

```bash
sudo unshare --pid --fork --mount-proc --uts bash
  hostname mini
  hostname
  ps aux            # только bash и ps
  exit
```

Без `--mount-proc` `/proc` остаётся хостовым: `ps` читает `/proc` и показывает процессы хоста,
хотя namespace уже новый. PID namespace изолирует дерево, но не содержимое `/proc`.

</details>

#### C3. cgroups и OOM

1. Запусти контейнер с лимитом 50 МБ памяти.
2. Заставь процесс внутри съесть 200 МБ.
3. Зафиксируй код выхода и статус контейнера.
4. Найди подтверждение OOM в `docker inspect` и в логах ядра хоста.

<details><summary>Ответ</summary>

```bash
docker run --name oom --memory=50m python:3-alpine \
  python -c "b=bytearray(200*1024*1024)"
echo "exit code: $?"                                  # 137
docker inspect oom --format '{{.State.OOMKilled}} {{.State.ExitCode}}'   # true 137
sudo dmesg -T | grep -i -m5 "killed process"          # подтверждение от ядра хоста
docker rm oom
```

</details>

#### C4. Лимит CPU

Запусти два контейнера с нагрузкой на CPU: один без ограничений, второй с `--cpus=0.2`.
Сравни в `docker stats`. Объясни, что означает `--cpus=0.5` в терминах cgroups.

<details><summary>Ответ</summary>

```bash
docker run -d --name burn-free  alpine sh -c 'while :; do :; done'
docker run -d --name burn-limit --cpus=0.2 alpine sh -c 'while :; do :; done'
docker stats --no-stream burn-free burn-limit         # ~100% vs ~20%
docker rm -f burn-free burn-limit
```

`--cpus=0.5` → cgroup `cpu.max` = `"50000 100000"`: 50 мс CPU на каждые 100 мс периода.
Это НЕ «половина ядра по номеру», а квота времени; процесс может бегать по всем ядрам.

</details>

#### C5. Архитектура клиент-сервер

1. Получи версию демона, список контейнеров и список образов **через `curl` по unix-сокету**,
   без использования `docker` CLI.
2. Останови демон (`sudo systemctl stop docker`), проверь, что запущенный контейнер
   продолжает работать. Объясни почему. Запусти демон обратно.

<details><summary>Ответ</summary>

```bash
curl -s --unix-socket /var/run/docker.sock http://localhost/version        | jq '.Version'
curl -s --unix-socket /var/run/docker.sock http://localhost/containers/json| jq '.[].Names'
curl -s --unix-socket /var/run/docker.sock http://localhost/images/json    | jq '.[].RepoTags'

docker run -d --name survive nginx
sudo systemctl stop docker            # остановится docker.service (и docker.socket)
ps aux | grep -c "[n]ginx"            # процессы живы
sudo systemctl start docker
docker ps                             # контейнер на месте
# Причина: контейнер держит containerd-shim, он не зависит от жизни dockerd.
# (Если бы в /etc/docker/daemon.json было "live-restore": false и перезапускался containerd —
#  поведение было бы иным.)
docker rm -f survive
```

</details>

#### C6. Capabilities

1. Покажи capabilities процесса внутри обычного контейнера (`capsh --print` в образе с capsh
   или `grep Cap /proc/1/status`).
2. Запусти контейнер с `--cap-drop=ALL` и попробуй выполнить `ping 8.8.8.8` и `chown`.
3. Верни только нужную capability, чтобы `ping` заработал.

<details><summary>Ответ</summary>

```bash
docker run --rm alpine grep Cap /proc/1/status
docker run --rm --cap-drop=ALL alpine ping -c1 8.8.8.8   # ping: permission denied
docker run --rm --cap-drop=ALL --cap-add=NET_RAW alpine ping -c1 8.8.8.8   # работает
```

</details>

#### C7. Сравнение с альтернативой (опционально, если есть podman)

Установи `podman`, запусти тот же nginx, посмотри `ps aux` на хосте.
Найди отличие: от какого пользователя работает процесс и есть ли демон.

<details><summary>Ответ</summary>

```bash
sudo apt install -y podman
podman run -d --name pweb nginx
ps aux | grep "[n]ginx" | head -2      # процесс от ТВОЕГО пользователя, не от root
pgrep -x podman                        # демона нет — podman завершился, остался conmon
```

</details>

---

### Блок D. Инциденты

**D1.** Контейнер с Java-приложением внезапно умирает, `docker ps -a` показывает `Exited (137)`.
В логах приложения ничего подозрительного. Диагноз и куда смотреть?

<details><summary>Ответ</summary>

Код 137 = 128 + 9 (SIGKILL). Почти всегда — OOM-killer из-за превышения `--memory`
(или лимита в k8s). Проверить: <code v-pre>docker inspect &lt;c&gt; --format '{{.State.OOMKilled}}'</code> → `true`,
`dmesg | grep -i "killed process"`. Лечение: поднять лимит, починить утечку или задать
корректные настройки памяти рантайму (для JVM — `-XX:MaxRAMPercentage`, см. D4).
Второй, более редкий вариант: кто-то/что-то послал `kill -9` (например, `docker stop` по таймауту).

</details>

**D2.** Разработчик просит примонтировать `/var/run/docker.sock` в контейнер CI-раннера,
«чтобы собирать образы». Чем это опасно и что предложить взамен?

<details><summary>Ответ</summary>

Сокет = root на хосте: из контейнера можно поднять привилегированный контейнер с
`-v /:/host` и получить всю машину, прочитать секреты других контейнеров, подменить образы.
Взамен: **buildah/rootless BuildKit** (сборка без привилегий; kaniko архивирован в 2025), BuildKit с отдельным демоном
(`docker buildx` + remote builder), rootless-докер, или выделенный build-сервер с ограниченным доступом.

</details>

**D3.** После `sudo systemctl restart docker` все контейнеры продолжили работать,
но у коллеги на другом сервере — перезапустились. В чём может быть разница?

<details><summary>Ответ</summary>

На твоём сервере контейнеры пережили рестарт благодаря shim'ам (и/или
`"live-restore": true` в `/etc/docker/daemon.json`). У коллеги могла перезапускаться вся связка
вместе с containerd, либо старая версия докера/иные настройки, либо контейнеры имеют
`restart: always` и их специально перезапустили. Проверить: `docker info | grep -i live`,
версия докера, содержимое `daemon.json`.

</details>

**D4.** Контейнер видит в `free -m` и `nproc` ресурсы **всего хоста**, хотя лимиты выставлены.
Приложение (JVM/Node) из-за этого выжирает память. Почему так и как чинить?

<details><summary>Ответ</summary>

`free`, `nproc`, `/proc/cpuinfo` читаются из **хостового /proc** — namespaces их не
подменяют (нет «cgroup-aware procfs»). Приложение видит ресурсы хоста и строит по ним пулы/heap.
Лечение: (1) современные JVM/Node учитывают cgroup-лимиты — обновить рантайм и задать
`-XX:MaxRAMPercentage=75`; (2) явно передавать лимиты приложению переменными окружения;
(3) на хосте — `lxcfs` (подменяет `/proc` в контейнере). Смотреть реальные лимиты:
`cat /sys/fs/cgroup/memory.max`.

</details>

**D5.** На сервере растёт нагрузка, `top` показывает сотни процессов, непонятно, чьи они.
Как быстро понять, какому контейнеру принадлежит процесс с известным PID?

<details><summary>Ответ</summary>

По cgroup: `cat /proc/<PID>/cgroup` — в пути будет ID контейнера, далее
<code v-pre>docker inspect &lt;id&gt; --format '{{.Name}}'</code>. Быстрее — `docker top <c>` по каждому кандидату,
или `systemd-cgls`/`systemd-cgtop`. Обратный путь: <code v-pre>docker inspect -f '{{.State.Pid}}' &lt;c&gt;</code>.

</details>

**D6.** В компании запретили Docker Desktop и требуют собирать образы в Kubernetes-раннерах
без привилегированного режима. Какие инструменты предложишь?

<details><summary>Ответ</summary>

**BuildKit** в режиме rootless (`moby/buildkit:rootless` + `buildctl-daemonless.sh`)
или как отдельный сервис (`buildkitd` + `buildctl`), **buildah** (rootless-сборка из Dockerfile),
**Podman** для локальной разработки. Честная оговорка: rootless-сборщикам в поде обычно нужны
послабленные seccomp/AppArmor (`Unconfined`), хотя privileged — нет. **kaniko** (сборка в поде
без root) раньше был ответом по умолчанию, но в 2025 upstream архивирован — только legacy (форк
Chainguard). Всё это OCI-совместимо: полученные образы одинаково работают в k8s.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем контейнеризация отличается от виртуализации? *(вопрос №1 из роадмапа)*

<details><summary>Ответ</summary>

См. A1: своё ядро vs общее, вес и скорость старта, уровень изоляции.

</details>

**2.** За счёт каких технологий ядра Linux обеспечивается изоляция контейнеров? *(вопрос №2)*

<details><summary>Ответ</summary>

См. A3: namespaces, cgroups, capabilities/seccomp/LSM, pivot_root+OverlayFS.

</details>

**3.** Что такое namespaces и cgroups, чем отличаются?

<details><summary>Ответ</summary>

namespaces — изоляция видимости (что процесс видит), cgroups — ограничение ресурсов
(сколько он может взять).

</details>

**4.** Из каких компонентов состоит Docker? Что делает демон, что — клиент?

<details><summary>Ответ</summary>

CLI (клиент) → Docker API (unix-сокет) → dockerd (образы, сети, тома, сборка) →
containerd (жизненный цикл) → shim → runc (создаёт контейнер).

</details>

**5.** Что такое containerd и runc?

<details><summary>Ответ</summary>

containerd — высокоуровневый runtime (жизненный цикл, образы, снапшоты), runc — низкоуровневый
(создаёт namespaces/cgroups и запускает процесс по OCI runtime-spec).

</details>

**6.** Что такое OCI?

<details><summary>Ответ</summary>

Open Container Initiative: стандарты image-spec, runtime-spec, distribution-spec, обеспечивающие
совместимость образов и рантаймов разных вендоров.

</details>

**7.** Чем Podman отличается от Docker?

<details><summary>Ответ</summary>

Podman без демона (fork/exec напрямую), умеет rootless из коробки, поддерживает pods,
CLI совместим с docker. Docker — клиент-серверный с root-демоном.

</details>

**8.** Почему Kubernetes перестал использовать Docker?

<details><summary>Ответ</summary>

Удалили dockershim в пользу стандартного CRI; ноды используют containerd/CRI-O.
Образы не поменялись — они OCI.

</details>

**9.** Насколько контейнер безопасен относительно VM? Когда выбирать VM?

<details><summary>Ответ</summary>

Слабее: общее ядро, эксплойт ядра → побег из контейнера. VM выбирать для недоверенного кода,
жёсткой мультитенантности, другой ОС/ядра, регуляторных требований. Компромисс — gVisor/Kata.

</details>

**10.** Что произойдёт с контейнерами при перезапуске демона?

<details><summary>Ответ</summary>

Ничего не произойдёт: контейнеры держатся shim'ами и продолжают работать (плюс опция
`live-restore`). Управлять ими временно нельзя, пока демон не поднимется.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю разницу контейнера и VM без запинки, через namespaces и общее ядро
- [ ] Перечисляю namespaces и что каждый изолирует
- [ ] Понимаю, за что отвечают cgroups и как посмотреть реальный лимит контейнера
- [ ] Рисую цепочку CLI → API → dockerd → containerd → shim → runc
- [ ] Знаю, почему docker.sock = root, и что предлагать вместо него
- [ ] Помню, что 137 — это чаще всего OOM
- [ ] Могу войти в контейнер через nsenter, когда внутри нет shell
- [ ] Знаю, зачем существуют podman, buildah, kaniko, containerd, CRI-O
