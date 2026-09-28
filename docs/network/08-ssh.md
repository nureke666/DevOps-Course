---
title: "08. SSH"
description: "Ключи, ~/.ssh/config, проброс портов, агент, known_hosts, hardening sshd — конспект и задачи"
---

# 08. SSH — ключи, конфиг, туннели, hardening

> Роадмап → 2.5 Сети → протокол **SSH**.
> **После темы ты умеешь:** настроить вход по ключам, писать `~/.ssh/config`, пробрасывать порты
> через jump-host, пользоваться агентом и закрыть сервер от перебора.
> ⭐ Это протокол, через который ты будешь работать каждый день.

---

## 🗺️ Схема: как устанавливается SSH-соединение

```text:no-line-numbers
   КЛИЕНТ                                              СЕРВЕР (sshd:22)
      │─── TCP-соединение ────────────────────────────────►│
      │◄── баннер версии ─────────────────────────────────►│
      │                                                     │
      │◄── ① ключ ХОСТА (host key) ───────────────────────  │
      │   клиент сверяет с ~/.ssh/known_hosts               │
      │   • нет записи → вопрос «continue connecting?»      │
      │   • не совпала → ⚠️ WARNING: REMOTE HOST ID CHANGED │
      │                                                     │
      │═══ ② обмен ключами (ECDH) → сеансовый ключ ════════ │
      │                                                     │
      │─── ③ аутентификация ПОЛЬЗОВАТЕЛЯ ─────────────────►│
      │    publickey → password → keyboard-interactive      │
      │    (порядок задаёт PreferredAuthentications)        │
      │                                                     │
      │═══ ④ шифрованный канал: shell, exec, sftp, порты ══ │
```

⭐ Два разных ключа, которые путают: **host key** аутентифицирует *сервер* (known_hosts),
**user key** аутентифицирует *тебя* (authorized_keys).

---

## 1. Ключи: создать, разложить, проверить

```bash
ssh-keygen -t ed25519 -C "nurik@work"          # ⭐ современный выбор: короткий и быстрый
ssh-keygen -t rsa -b 4096 -C "legacy"          # если старый сервер не умеет ed25519

ls -l ~/.ssh/
# id_ed25519      ← ПРИВАТНЫЙ ключ (никому, права 600)
# id_ed25519.pub  ← публичный (кладётся на серверы)

ssh-copy-id user@host                          # правильный способ разложить ключ
# вручную: содержимое .pub добавить в ~/.ssh/authorized_keys на сервере

ssh-keygen -lf ~/.ssh/id_ed25519.pub           # отпечаток (fingerprint)
ssh-keygen -y -f ~/.ssh/id_ed25519             # восстановить публичный из приватного
```

**Права — источник половины проблем:**

| Путь | Права |
|------|-------|
| `~/.ssh` | `700` |
| `~/.ssh/authorized_keys` | `600` |
| Приватный ключ | `600` (иначе `UNPROTECTED PRIVATE KEY FILE` и отказ) |
| Домашний каталог | Не должен быть доступен на запись группе/всем (иначе sshd игнорирует ключи) |

```bash
ssh -vvv user@host        # ⭐ если ключ «не работает» — здесь видно, какой ключ предложен и что ответил сервер
sudo journalctl -u ssh -f # на сервере: точная причина отказа
```

---

## 2. `~/.ssh/config` — то, что экономит часы

```text:no-line-numbers
Host *
    ServerAliveInterval 30           # держать соединение живым через NAT
    ServerAliveCountMax 3
    AddKeysToAgent yes
    HashKnownHosts no

Host bastion
    HostName 203.0.113.10
    User devops
    Port 2222
    IdentityFile ~/.ssh/id_ed25519

Host prod-*                          # ⭐ шаблоны
    User deploy
    ProxyJump bastion                # ходить через бастион автоматически
    IdentityFile ~/.ssh/id_prod
    IdentitiesOnly yes               # не перебирать все ключи агента

Host prod-db
    HostName 10.0.5.20

Host github.com
    User git
    IdentityFile ~/.ssh/id_github
    IdentitiesOnly yes
```

```bash
ssh prod-db          # вместо ssh -J devops@203.0.113.10:2222 deploy@10.0.5.20 -i ~/.ssh/id_prod
ssh -G prod-db       # какие настройки реально применятся
```

---

## 3. Проброс портов — самая практичная часть

```bash
# ① Локальный (-L): «притащить» удалённый порт к себе
ssh -L 5432:localhost:5432 user@dbhost
#   localhost:5432 у меня  →  localhost:5432 на dbhost
psql -h 127.0.0.1 -p 5432      # подключаешься как будто БД локальная

# То же, но БД на третьей машине, доступной с dbhost:
ssh -L 5432:10.0.5.20:5432 user@bastion

# ② Удалённый (-R): отдать СВОЙ порт наружу
ssh -R 8080:localhost:3000 user@public-host
#   public-host:8080 → мой localhost:3000 (показать коллеге локальную разработку)

# ③ Динамический (-D): SOCKS5-прокси
ssh -D 1080 user@bastion
curl --socks5-hostname localhost:1080 http://internal.service/

# ④ Jump host
ssh -J bastion user@10.0.5.20        # современный способ
ssh -A user@bastion                  # ⚠️ проброс агента — удобно, но небезопасно на чужих хостах

# Полезные флаги
ssh -f -N -L 5432:localhost:5432 user@dbhost   # в фон, без шелла
ssh -o ExitOnForwardFailure=yes ...            # падать, если порт занят
```

| Флаг | Мнемоника |
|------|-----------|
| `-L` | **L**ocal: слушаю **у себя**, отдаю на удалённой стороне |
| `-R` | **R**emote: слушает **сервер**, отдаёт на моей стороне |
| `-D` | **D**ynamic: SOCKS-прокси |
| `-J` | **J**ump: через промежуточный хост |

⚠️ По умолчанию проброшенный порт слушается только на `127.0.0.1`.
Открыть для сети — `-L 0.0.0.0:5432:...` плюс `GatewayPorts yes` на сервере (для `-R`).

---

## 4. Агент и passphrase

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519           # ввести passphrase один раз
ssh-add -l                          # какие ключи загружены
ssh-add -D                          # выгрузить все
ssh-add -t 3600 ~/.ssh/id_prod      # ключ живёт в агенте час
```

Приватный ключ должен быть с passphrase — иначе украденный файл сразу даёт доступ.
Агент держит расшифрованный ключ в памяти, чтобы не вводить пароль каждый раз.

⚠️ **Agent forwarding (`-A`)**: root на промежуточном хосте может использовать твой агент,
пока ты подключён. На бастионах используют `ProxyJump` вместо `-A`.

---

## 5. known_hosts и предупреждение о смене ключа

```bash
ssh-keygen -F host                        # есть ли запись
ssh-keygen -R host                        # удалить запись (после легальной пересборки сервера)
ssh-keyscan -H host >> ~/.ssh/known_hosts # добавить заранее (для автоматизации)
```

```text:no-line-numbers
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @
```

Это либо MITM, либо (в 99% случаев) сервер пересоздан/переехал IP. Правильная реакция:
выяснить причину, сверить fingerprint с тем, кто пересоздавал, и только потом `ssh-keygen -R`.
В автоматизации — заранее раскладывать known_hosts, а не ставить `StrictHostKeyChecking=no`
бездумно.

---

## 6. Hardening сервера (`/etc/ssh/sshd_config`)

```text:no-line-numbers
Port 22                          # смена порта — не защита, но убирает шум в логах
PermitRootLogin no               # ⭐ обязательно
PasswordAuthentication no        # ⭐ только ключи
PubkeyAuthentication yes
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 30
AllowUsers deploy devops         # или AllowGroups ssh-users
X11Forwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
AllowTcpForwarding no            # если пробросы не нужны
Banner /etc/issue.net
```

```bash
sudo sshd -t                     # ⭐ ПРОВЕРИТЬ конфиг перед перезапуском
sudo systemctl reload ssh
# ⚠️ Не закрывай текущую сессию, пока не проверил вход НОВОЙ сессией!
```

**Дополнительно:** `fail2ban` (бан по числу неудачных попыток), файрвол с ограничением
источников, 2FA, аудит `journalctl -u ssh | grep -i fail`, запрет входа для сервисных аккаунтов
(`--shell /usr/sbin/nologin`).

```bash
# Кто ломится
sudo journalctl -u ssh --since today | grep -i "failed password" | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn | head
sudo lastb | head            # неудачные входы
last | head                  # успешные
```

---

## 7. SSH в автоматизации

```bash
ssh -n user@host 'uptime'                           # ⭐ -n в циклах: не съедать stdin
ssh -o BatchMode=yes user@host true                 # без интерактивных запросов (для скриптов)
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new user@host 'cmd'
scp -r ./dist user@host:/opt/app/
rsync -avz --delete ./dist/ user@host:/opt/app/     # ⭐ лучше scp: инкрементально и с удалением
ssh user@host 'bash -s' < local_script.sh           # выполнить локальный скрипт удалённо
```

- Ansible — это, по сути, SSH + Python на той стороне (блок Ansible, тема 02).
- В CI приватный ключ хранится в секретах и добавляется в агент на время job.
- `ControlMaster`/`ControlPersist` ускоряют серию подключений к одному хосту в разы:

```text:no-line-numbers
Host *
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
```

---

## 💼 Как это в DevOps

- Вход по ключам и отключённые пароли — базовое требование к любому серверу.
- `ProxyJump` через бастион — стандартная схема доступа к приватным подсетям.
- Проброс портов — как ты попадаешь в БД/Grafana/панель, закрытые от интернета.
- `~/.ssh/config` с шаблонами `prod-*`/`stage-*` — must have, когда серверов больше пяти.
- SSH-ключи деплоя (deploy keys) в GitLab/GitHub и `known_hosts` в раннерах — частая точка отказа CI.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web

# 1. Ключи
ssh-keygen -t ed25519 -N '' -f ~/.ssh/lab_key -C lab
ssh-keygen -lf ~/.ssh/lab_key.pub

# 2. Разложить на соседа (пароль vagrant)
ssh-copy-id -i ~/.ssh/lab_key.pub -o StrictHostKeyChecking=accept-new vagrant@192.168.56.11
ssh -i ~/.ssh/lab_key vagrant@192.168.56.11 'hostname; whoami'

# 3. Отладка аутентификации
ssh -vvv -i ~/.ssh/lab_key vagrant@192.168.56.11 true 2>&1 | grep -E 'Offering|Authentications that can continue|Authenticated'

# 4. Сломать права и увидеть эффект
chmod 644 ~/.ssh/lab_key
ssh -i ~/.ssh/lab_key vagrant@192.168.56.11 true      # UNPROTECTED PRIVATE KEY FILE
chmod 600 ~/.ssh/lab_key

# 5. ~/.ssh/config
cat >> ~/.ssh/config <<'EOS'
Host app
    HostName 192.168.56.11
    User vagrant
    IdentityFile ~/.ssh/lab_key
    IdentitiesOnly yes
EOS
chmod 600 ~/.ssh/config
ssh app 'uptime'
ssh -G app | grep -E '^(hostname|user|identityfile)'

# 6. Проброс портов: поднимем сервис на соседе и «притащим» его к себе
ssh app 'nohup python3 -m http.server 8000 >/dev/null 2>&1 &' ; sleep 1
ssh -f -N -L 9000:localhost:8000 app
curl -s -o /dev/null -w 'через туннель: %{http_code}\n' http://127.0.0.1:9000/
ss -tlnp | grep 9000
pkill -f 'ssh -f -N -L 9000'

# 7. SOCKS-прокси
ssh -f -N -D 1080 app
curl -s --socks5-hostname 127.0.0.1:1080 -o /dev/null -w 'через SOCKS: %{http_code}\n' http://192.168.56.11:8000/
pkill -f 'ssh -f -N -D 1080'
ssh app 'pkill -f http.server'

# 8. Агент
eval "$(ssh-agent -s)"; ssh-add ~/.ssh/lab_key; ssh-add -l; ssh app true && echo "без указания ключа — из агента"

# 9. known_hosts
ssh-keygen -F 192.168.56.11 | head -2
ssh-keyscan -t ed25519 192.168.56.11 2>/dev/null | head -1

# 10. ControlMaster — замерить эффект
time ssh app true
cat >> ~/.ssh/config <<'EOS'
Host *
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 2m
EOS
ssh app true; time ssh app true           # второй раз — заметно быстрее

# 11. Кто ломился в SSH
sudo journalctl -u ssh --since "-1 day" | grep -ci "failed password" || echo "0 неудачных попыток"

# 12. Уборка
pkill -f 'ssh -f -N' 2>/dev/null; rm -f ~/.ssh/lab_key*; sed -i '/Host app/,+4d' ~/.ssh/config
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `ssh-keygen -t ed25519 -C "comment"` | Создать пару ключей |
| `ssh-copy-id user@host` | Разложить публичный ключ |
| `ssh -vvv user@host` | ⭐ Отладка аутентификации |
| `ssh -i key user@host` | Конкретный ключ |
| `ssh -J bastion user@host` | Через jump-host |
| `ssh -L 5432:localhost:5432 host` | Локальный проброс (к себе) |
| `ssh -R 8080:localhost:3000 host` | Удалённый проброс (наружу) |
| `ssh -D 1080 host` | SOCKS5-прокси |
| `ssh -f -N ...` | В фон, без шелла |
| `ssh -n host 'cmd'` | ⭐ В циклах: не читать stdin |
| `ssh-add -l` / `-D` / `-t 3600` | Агент: список / очистить / с TTL |
| `ssh-keygen -R host` | Удалить запись из known_hosts |
| `ssh -G host` | Какой конфиг применится |
| `sshd -t` | ⭐ Проверить sshd_config перед reload |
| `rsync -avz src/ host:/dst/` | Копирование лучше scp |

---

## 🧠 Что запомнить

1. Host key аутентифицирует сервер (known_hosts), user key — тебя (authorized_keys).
2. Права: `~/.ssh` 700, ключ 600, `authorized_keys` 600; иначе sshd молча откажет.
3. `ssh -vvv` + `journalctl -u ssh` на сервере отвечают на 99% вопросов «почему не пускает».
4. `~/.ssh/config` с шаблонами и `ProxyJump` заменяет длинные команды и скрипты-обёртки.
5. `-L` слушает у тебя, `-R` — на сервере, `-D` даёт SOCKS-прокси.
6. `-A` (agent forwarding) опасен на чужих хостах — предпочитай `ProxyJump`.
7. Приватный ключ — с passphrase, в памяти держит агент; ключ без пароля = пропуск для любого,
   кто получил файл.
8. Hardening: `PermitRootLogin no`, `PasswordAuthentication no`, `MaxAuthTries`, fail2ban.
9. Перед `reload ssh` всегда `sshd -t`, и не закрывай текущую сессию, пока не проверил новую.
10. В скриптах: `-n`, `BatchMode=yes`, `ConnectTimeout`, заранее подготовленный known_hosts.
11. `ControlMaster` + `ControlPersist` кратно ускоряют серию команд к одному хосту.

---

## Задачи

> Стенд: `web` (192.168.56.10) и `app` (192.168.56.11).
> ⚠️ Перед hardening'ом сделай снапшот: закрыть себе SSH — классика жанра.

---

### Блок A. Теория

**A1.** Опиши установку SSH-соединения по шагам. В какой момент проверяется known_hosts?

<details><summary>Ответ</summary>

TCP-соединение → обмен баннерами версий → сервер предъявляет host key, клиент сверяет
его с `~/.ssh/known_hosts` → обмен ключами (ECDH) и создание сеансового ключа →
аутентификация пользователя (publickey/password) → шифрованный канал (shell, exec, sftp,
проброс портов). known_hosts проверяется **до** аутентификации пользователя.

</details>

**A2.** Чем host key отличается от user key? Где лежит каждый?

<details><summary>Ответ</summary>

Host key — пара ключей сервера (`/etc/ssh/ssh_host_*`), доказывает клиенту, что это
тот самый сервер; хранится у клиента в `known_hosts`. User key — твоя пара; публичная часть
лежит в `~/.ssh/authorized_keys` на сервере, приватная — у тебя.

</details>

**A3.** Какие права должны быть на `~/.ssh`, приватный ключ и `authorized_keys`? Что будет при неверных?

<details><summary>Ответ</summary>

`~/.ssh` — 700, приватный ключ — 600, `authorized_keys` — 600, домашний каталог —
без права записи для группы/остальных. Иначе клиент откажется использовать ключ
(`UNPROTECTED PRIVATE KEY FILE`), а sshd проигнорирует `authorized_keys` (StrictModes).

</details>

**A4.** Чем ed25519 лучше RSA? Когда всё же нужен RSA?

<details><summary>Ответ</summary>

Ed25519 короче, быстрее, безопаснее при меньшей длине и не зависит от качества
генератора так, как RSA. RSA 4096 нужен для старых серверов и железа, не поддерживающего
ed25519 (OpenSSH < 6.5).

</details>

**A5.** Что делает `ssh-copy-id` и как сделать то же вручную?

<details><summary>Ответ</summary>

Копирует публичный ключ в `~/.ssh/authorized_keys` на сервере с правильными правами.
Вручную: `cat ~/.ssh/id_ed25519.pub | ssh user@host 'mkdir -p ~/.ssh && chmod 700 ~/.ssh &&
cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'`.

</details>

**A6.** Что означает `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED` и как правильно реагировать?

<details><summary>Ответ</summary>

Ключ хоста не совпал с сохранённым: либо сервер пересоздан/переустановлен/сменил IP,
либо MITM. Правильно: выяснить причину у того, кто управляет сервером, сверить fingerprint
из консоли облака, затем `ssh-keygen -R host` и подключиться заново.

</details>

**A7.** Объясни `-L`, `-R`, `-D` и `-J` — что слушает и куда идёт трафик в каждом случае.

<details><summary>Ответ</summary>

`-L localport:target:targetport` — слушает у клиента, трафик уходит через сервер к target.
`-R remoteport:target:targetport` — слушает на сервере, трафик идёт к клиенту и дальше на target.
`-D port` — SOCKS5-прокси на клиенте, весь трафик выходит из сервера.
`-J host` — установить соединение через промежуточный хост.

</details>

**A8.** Зачем нужен ssh-agent? Чем опасен agent forwarding?

<details><summary>Ответ</summary>

Агент хранит расшифрованные приватные ключи в памяти, чтобы не вводить passphrase
на каждое подключение. Forwarding (`-A`) даёт удалённому хосту доступ к твоему агенту:
root на нём может подписывать запросы твоим ключом, пока сессия жива.

</details>

**A9.** Что делает `IdentitiesOnly yes` и зачем он нужен?

<details><summary>Ответ</summary>

Запрещает предлагать серверу все ключи из агента и каталога, кроме указанного
`IdentityFile`. Спасает от `Too many authentication failures` (сервер разрывает соединение
после MaxAuthTries попыток) и от «непонятно, каким ключом зашли».

</details>

**A10.** Как работает `ProxyJump` и чем он лучше `-A` + двойного ssh?

<details><summary>Ответ</summary>

`ProxyJump` устанавливает соединение до конечного хоста **через** бастион, при этом
аутентификация на конечном хосте происходит с локальной машины: приватный ключ и агент
на бастион не попадают. `-A` же открывает агент бастиону.

</details>

**A11.** Назови 6 директив hardening в `sshd_config` и что делает каждая.

<details><summary>Ответ</summary>

`PermitRootLogin no` — запрет root; `PasswordAuthentication no` — только ключи;
`MaxAuthTries 3` — попыток на соединение; `AllowUsers/AllowGroups` — белый список;
`LoginGraceTime` — время на аутентификацию; `ClientAliveInterval/CountMax` — отключение
мёртвых сессий; `X11Forwarding no`, `AllowTcpForwarding no` — отключение лишних возможностей.

</details>

**A12.** Почему в скриптах используют `ssh -n` и `BatchMode=yes`?

<details><summary>Ответ</summary>

`-n` перенаправляет stdin из `/dev/null`, иначе ssh «съест» список хостов,
который читает цикл. `BatchMode=yes` запрещает интерактивные запросы (пароль, подтверждение
ключа) — скрипт падает сразу, а не висит.

</details>

**A13.** Что дают `ControlMaster` и `ControlPersist`?

<details><summary>Ответ</summary>

Мультиплексирование: первое соединение создаёт управляющий сокет, последующие
переиспользуют его без нового TCP+TLS-хендшейка и аутентификации; `ControlPersist` держит
мастер-соединение открытым заданное время после выхода.

</details>

**A14.** Как SSH используется в Ansible и в CI?

<details><summary>Ответ</summary>

Ansible подключается по SSH и выполняет Python-модули на целевом хосте
(`ansible_ssh_common_args`, ControlPersist по умолчанию). В CI приватный ключ берут
из секретов, добавляют в агент на время job и заранее готовят `known_hosts`.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  ssh-keygen -t ed25519 -C "ci@runner"
B2.  ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host
B3.  ssh -vvv user@host
B4.  ssh -J bastion user@10.0.5.20
B5.  ssh -f -N -L 5432:10.0.5.20:5432 bastion
B6.  ssh -R 8080:localhost:3000 public-host
B7.  ssh -D 1080 bastion
B8.  ssh -G prod-db
B9.  ssh-keygen -R 192.168.56.11
B10. ssh-keyscan -H host >> ~/.ssh/known_hosts
B11. ssh -o BatchMode=yes -o ConnectTimeout=5 host true
B12. sshd -t
```

- **B1.** Создаёт пару ed25519 с комментарием.
- **B2.** Копирует указанный публичный ключ на сервер.
- **B3.** Подробный лог подключения: какие ключи предлагаются, что отвечает сервер.
- **B4.** Подключение к 10.0.5.20 через бастион.
- **B5.** Фоновый туннель: локальный 5432 → 10.0.5.20:5432 через bastion.
- **B6.** Открывает на `public-host` порт 8080, ведущий на локальный 3000.
- **B7.** Поднимает SOCKS5-прокси на localhost:1080.
- **B8.** Печатает итоговую конфигурацию для хоста `prod-db`.
- **B9.** Удаляет запись из known_hosts.
- **B10.** Заранее добавляет ключ хоста (для автоматизации).
- **B11.** Неинтерактивная проверка доступности с таймаутом.
- **B12.** Проверяет синтаксис sshd_config — обязательный шаг перед reload.

**B13.** В чём разница между этими двумя командами и когда какая нужна?
```bash
ssh -L 5432:localhost:5432 user@db
ssh -L 5432:10.0.5.20:5432 user@bastion
```

<details><summary>Ответ</summary>

Первая: БД находится на самом сервере `db` (`localhost` резолвится **на стороне
сервера**). Вторая: подключаемся к бастиону, а он проксирует трафик на третью машину
10.0.5.20 — так ходят в приватные подсети.

</details>

---

### Блок C. Практика

**C1. Ключи с нуля.** Создай пару ed25519 с passphrase, разложи на соседнюю ВМ, запрети
там аутентификацию по паролю и убедись, что вход по ключу работает, а по паролю — нет.

<details><summary>Ответ</summary>

`ssh-keygen -t ed25519` (с passphrase) → `ssh-copy-id` → на сервере
`PasswordAuthentication no` + `sudo sshd -t && sudo systemctl reload ssh`.
Проверка: `ssh -o PreferredAuthentications=password user@host` → `Permission denied
(publickey)`.

</details>

**C2. Отладка «ключ не работает».** Сломай по очереди и найди причину через `ssh -vvv`
и логи сервера: (1) права 644 на приватный ключ; (2) права 777 на домашний каталог сервера;
(3) неверная строка в `authorized_keys`; (4) не тот пользователь.
Для каждого случая выпиши, какая строка в выводе указывает на проблему.

<details><summary>Ответ</summary>

(1) `Permissions 0644 for '...' are too open` — на клиенте; (2) в логе sshd
`Authentication refused: bad ownership or modes for directory /home/user`;
(3) `Failed publickey for user` и в `-vvv` — предложенный ключ отвергнут;
(4) `Invalid user`/`Permission denied` сразу после `Offering public key`.

</details>

**C3. Конфиг.** Напиши `~/.ssh/config` с: общим блоком `Host *`, бастионом, шаблоном `prod-*`
через `ProxyJump`, отдельным ключом для GitHub. Проверь `ssh -G`.

<details><summary>Ответ</summary>

См. пример конфига в конспекте; проверка — `ssh -G prod-db | grep -E
'^(hostname|user|proxyjump|identityfile)'`.

</details>

**C4. Локальный проброс.** Подними на `app` сервис, доступный только на `127.0.0.1`,
и достучись до него с `web` через туннель. Докажи, что напрямую он недоступен.

<details><summary>Ответ</summary>

На `app`: `python3 -m http.server 8000 --bind 127.0.0.1`.
С `web`: `curl http://192.168.56.11:8000/` → отказ; `ssh -f -N -L 9000:localhost:8000 app`
и `curl http://127.0.0.1:9000/` → 200.

</details>

**C5. Обратный проброс.** Запусти локальный сервис на `web` и открой к нему доступ с `app`
через `-R`. Объясни, зачем на сервере нужен `GatewayPorts`.

<details><summary>Ответ</summary>

`ssh -f -N -R 9000:localhost:8000 app` открывает порт на `app`. По умолчанию он
слушает только `127.0.0.1` на сервере; чтобы к нему могли подключаться другие хосты,
на сервере нужен `GatewayPorts yes` (или `clientspecified`).

</details>

**C6. SOCKS.** Подними `-D 1080` и походи через прокси curl'ом во внутреннюю сеть.
Покажи разницу `--socks5` и `--socks5-hostname` (где резолвится DNS).

<details><summary>Ответ</summary>

`--socks5` резолвит имя **локально** и отправляет прокси IP; `--socks5-hostname`
передаёт имя прокси, и DNS-резолв происходит на той стороне — это важно для внутренних зон,
которые локально не резолвятся.

</details>

**C7. Jump host.** Сделай из `web` бастион: с ноутбука (или из третьего namespace)
ходи на `app` только через него. Настрой так, чтобы работала команда `ssh app-internal`.

<details><summary>Ответ</summary>

В `~/.ssh/config`:
```text:no-line-numbers
Host bastion
    HostName 192.168.56.10
    User vagrant
Host app-internal
    HostName 192.168.56.11
    User vagrant
    ProxyJump bastion
```

</details>

**C8. Агент.** Создай ключ с passphrase, покажи, что без агента пароль спрашивается каждый раз,
добавь в агент с TTL 60 секунд и покажи, что после истечения снова спрашивает.

<details><summary>Ответ</summary>

Без агента passphrase спрашивается при каждом подключении. `ssh-add -t 60 key` —
в течение минуты вход без пароля, затем ключ удаляется из агента (`ssh-add -l` пуст).

</details>

**C9. Hardening.** На `app` примени: запрет root, только ключи, `MaxAuthTries 3`,
`AllowUsers`, `ClientAliveInterval`. Проверь `sshd -t`, перезагрузи, **не закрывая текущую
сессию**, и проверь вход новой сессией. Затем поставь fail2ban и покажи бан после трёх
неудачных попыток.

<details><summary>Ответ</summary>

Ключевые команды: правка `/etc/ssh/sshd_config`, `sudo sshd -t`,
`sudo systemctl reload ssh`, проверка новой сессией из другого терминала.
fail2ban: `sudo apt install fail2ban`, jail `sshd` включён по умолчанию,
проверка — `sudo fail2ban-client status sshd`.

</details>

**C10. Массовое выполнение.** Напиши скрипт, который по списку хостов параллельно (не более 5
одновременно) выполняет команду через SSH, собирает вывод в отдельные файлы и печатает таблицу
«хост / код возврата / первая строка вывода». Не забудь `-n`, таймауты и `BatchMode`.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail
cmd="${1:?нужна команда}"; shift
run_one() {
  local h="$1"
  ssh -n -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
      "$h" "$2" >"/tmp/out.$h" 2>&1
  printf '%-20s %-4s %s\n' "$h" "$?" "$(head -1 "/tmp/out.$h")"
}
export -f run_one
printf '%s\n' "$@" | xargs -P 5 -I{} bash -c 'run_one "$@"' _ {} "$cmd"
```

</details>

**C11. ControlMaster.** Замерь время 10 последовательных `ssh host true` без мультиплексирования
и с ним. Приведи цифры.

<details><summary>Ответ</summary>

Типично: без мультиплексирования каждое подключение 0.2-0.5 с (хендшейк+аутентификация),
с `ControlMaster` — 0.02-0.05 с. На 100 хостах/командах разница в минуты.

</details>

**C12. known_hosts в автоматизации.** Подготовь known_hosts заранее через `ssh-keyscan`
и объясни, почему это лучше, чем `StrictHostKeyChecking=no` в CI.

<details><summary>Ответ</summary>

`StrictHostKeyChecking=no` принимает **любой** ключ, то есть отключает защиту
от MITM. `ssh-keyscan` + сохранённый в артефактах/секретах known_hosts даёт и автоматизацию,
и проверку подлинности; компромисс — `accept-new` (принимать только новые, но не изменившиеся).

</details>

---

### Блок D. Инциденты

**D1.** После пересборки сервера Ansible падает на всех задачах с ошибкой host key.
Что произошло и как правильно решить (не отключая проверку насовсем)?

<details><summary>Ответ</summary>

Сервер пересоздан, host key новый. Правильно: убрать старую запись
(`ssh-keygen -R host`), добавить новую через `ssh-keyscan` в известный файл, а в Ansible
использовать `StrictHostKeyChecking=accept-new` или заранее раскладывать known_hosts,
а не отключать проверку глобально.

</details>

**D2.** Разработчик говорит: «ключ добавил, всё равно просит пароль». Порядок диагностики?

<details><summary>Ответ</summary>

`ssh -vvv` на клиенте (предлагается ли нужный ключ, нет ли `Too many authentication
failures`), права на ключ и `~/.ssh`, содержимое `authorized_keys` на сервере (одна строка,
без переносов), `journalctl -u ssh` на сервере (bad ownership/modes, `AuthorizedKeysFile`),
не отключён ли `PubkeyAuthentication`, тот ли пользователь.

</details>

**D3.** CI-джоба зависает на `ssh deploy@host 'deploy.sh'` и падает по таймауту 1 час.
Две вероятные причины и как их исключить.

<details><summary>Ответ</summary>

(1) Интерактивный запрос (подтверждение host key или пароль) — лечится `BatchMode=yes`
и подготовленным known_hosts; (2) удалённая команда ушла в фон, но держит открытым stdout/stderr,
и ssh не закрывает сессию — запускать с `nohup … >/dev/null 2>&1 &` или через systemd-run.
Плюс всегда задавать `ConnectTimeout` и таймаут job.

</details>

**D4.** Соединения по SSH рвутся каждые 5 минут простоя. Что настроить и на какой стороне?

<details><summary>Ответ</summary>

Простаивающие соединения рвёт NAT/файрвол. На клиенте — `ServerAliveInterval 30`,
на сервере — `ClientAliveInterval 60`. Это отправляет keepalive-пакеты чаще idle-таймаута.

</details>

**D5.** После правки `sshd_config` и `systemctl restart ssh` никто не может зайти,
включая тебя (сессия ещё жива). Что делать прямо сейчас и как было правильно?

<details><summary>Ответ</summary>

Текущая сессия жива — не закрывать её. Проверить `sudo sshd -t`, найти ошибку,
исправить конфиг, перезапустить. Если сессия уже потеряна — консоль гипервизора/облака
или recovery. Правильно было: `sshd -t` до рестарта, запуск второго sshd на другом порту
для страховки (`/usr/sbin/sshd -p 2222`) и проверка новой сессией перед закрытием старой.

</details>

**D6.** В логах тысячи `Failed password for root` с разных IP. Что предпринять?

<details><summary>Ответ</summary>

Убедиться, что `PermitRootLogin no` и `PasswordAuthentication no` (тогда перебор
бесполезен), поставить fail2ban, ограничить доступ по IP/через бастион на уровне файрвола
или security group, при желании сменить порт (уменьшит шум). Настроить алерт на всплеск.

</details>

**D7.** Скрипт-цикл по 30 хостам отрабатывает только на первом. Что забыли?

<details><summary>Ответ</summary>

`ssh` без `-n` прочитал весь список хостов из stdin цикла. Добавить `-n`
(или `< /dev/null`).

</details>

**D8.** Проброшенный порт `-L 5432:localhost:5432` работает с той же машины,
но коллега с соседнего хоста подключиться не может. Почему?

<details><summary>Ответ</summary>

Проброшенный порт по умолчанию слушает только на `127.0.0.1` клиента.
Нужно `-L 0.0.0.0:5432:...` (и понимать риск: порт станет доступен всей сети).

</details>

**D9.** После включения `AllowTcpForwarding no` сломался деплой. Как это связано?

<details><summary>Ответ</summary>

Деплой использовал проброс портов (например, туннель к БД или `rsync` через ssh
с форвардингом) — запрет `AllowTcpForwarding` его сломал. Решение: разрешить форвардинг
точечно для конкретного пользователя через `Match User deploy`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как работает аутентификация по ключам в SSH?

<details><summary>Ответ</summary>

Клиент доказывает владение приватным ключом, подписывая challenge; сервер проверяет
подпись публичным ключом из `authorized_keys`.

</details>

**2.** Чем host key отличается от пользовательского ключа?

<details><summary>Ответ</summary>

Host key идентифицирует сервер (known_hosts), пользовательский — клиента (authorized_keys).

</details>

**3.** Что означает предупреждение о смене ключа хоста?

<details><summary>Ответ</summary>

Ключ сервера изменился: пересоздание сервера или MITM; нужно проверить причину,
а не слепо удалять запись.

</details>

**4.** Как пробросить порт через SSH? Чем `-L` отличается от `-R`?

<details><summary>Ответ</summary>

`-L` слушает локально и туннелирует на удалённую сторону; `-R` — наоборот.

</details>

**5.** Что такое ssh-agent и agent forwarding?

<details><summary>Ответ</summary>

Агент хранит расшифрованные ключи в памяти; forwarding даёт удалённой машине
пользоваться твоим агентом — рискованно.

</details>

**6.** Как настроить доступ через бастион?

<details><summary>Ответ</summary>

`ProxyJump`/`-J` в `~/.ssh/config`, ключи только на своей машине.

</details>

**7.** Какие настройки безопасности ты применишь к sshd?

<details><summary>Ответ</summary>

Запрет root и паролей, ключи, MaxAuthTries, AllowUsers, fail2ban, ограничение по IP,
ClientAlive-настройки, `sshd -t` перед reload.

</details>

**8.** Почему ключи лучше паролей?

<details><summary>Ответ</summary>

Ключ не перебирается брутфорсом, не передаётся по сети, легко отзывается и
привязывается к конкретному пользователю/машине.

</details>

**9.** Как ускорить множественные подключения к одному серверу?

<details><summary>Ответ</summary>

`ControlMaster auto` + `ControlPersist` (мультиплексирование соединений).

</details>

---

### 🎯 Чек-лист

- [ ] Создаю ключи ed25519 и раскладываю через `ssh-copy-id`
- [ ] Отлаживаю доступ через `ssh -vvv` и логи sshd
- [ ] Написал рабочий `~/.ssh/config` с ProxyJump и шаблонами
- [ ] Умею `-L`, `-R`, `-D` и объясню разницу
- [ ] Понимаю риск agent forwarding
- [ ] Провёл hardening sshd, не заблокировав себя
- [ ] Использую `-n`, `BatchMode`, таймауты в скриптах
- [ ] Ускорил подключения через ControlMaster
