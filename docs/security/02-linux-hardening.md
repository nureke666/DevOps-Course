---
title: "02. Харденинг Linux-сервера"
description: "Блок → Безопасность → тема 02. Опирается на"
---

# 02. Харденинг Linux-сервера

> Блок → Безопасность → тема 02. Опирается на
> [../Network/08_ssh.md](/network/08-ssh) (SSH-hardening, fail2ban) ·
> [../Network/11_firewall_iptables.md](/network/11-firewall-iptables) ·
> [../Linux/05_user_management.md](/linux/05-user-management) ·
> [../Linux/12_kernel.md](/linux/12-kernel) (sysctl) ·
> [../Ansible/11_roles.md](/ansible/11-roles). Принципы — в [01_security_mindset.md](/security/01-security-mindset).
>
> **После темы ты умеешь:** по одному чек-листу закрыть свежий сервер (доступ, обновления,
> поверхность атаки, sysctl), настроить auditd и найти в нём «кто это сделал», прочитать отказ
> AppArmor/SELinux и починить его, не выключая защиту, прогнать Lynis и объяснить hardening
> index, а затем упаковать всё в Ansible-роль.

---

## 🗺️ Карта темы

```text
                 новый сервер (sec01, Ubuntu 22.04)  ── ⚠️ сначала snapshot «clean»
                                 │
        ┌──────────── ДОСТУП ────┴───────────┐    ┌──────── ПОВЕРХНОСТЬ АТАКИ ───────┐
        │ SSH: ключи, без root, AllowGroups  │    │ минимум пакетов и сервисов       │
        │ sudo: sudoers.d, use_pty, лог      │    │ firewall: deny by default        │
        │ лишние учётки заблокированы        │    │ SUID-аудит, sysctl-харденинг     │
        └────────────────┬───────────────────┘    └────────────────┬─────────────────┘
                         └──────────────────┬──────────────────────┘
        ┌──────────── ОБНОВЛЕНИЯ ───────────┴┐    ┌──────── КОНТРОЛЬ ────────────────┐
        │ unattended-upgrades (security)     │    │ auditd: кто что трогал           │
        │ needrestart, reboot-required       │    │ AppArmor / SELinux в enforce     │
        └────────────────┬───────────────────┘    └────────────────┬─────────────────┘
                         └──────────────────┬──────────────────────┘
                                            ▼
                проверка: Lynis (hardening index) · CIS-профиль (USG / OpenSCAP)
                                            ▼
                всё выше — Ansible-роль `hardening` в git → одинаково на всех серверах
```text
---

## 1. Порядок харденинга: чек-лист нового сервера

Порядок важен: сначала то, что не даст тебе отрезать себя от сервера, потом остальное.

| # | Шаг | Минимум | Подробно |
|---|-----|---------|----------|
| 0 | Страховка | snapshot/бэкап, доступ к консоли (VNC/serial облака), вторая SSH-сессия открыта | ⚠️ всё ниже — сначала на sec01 |
| 1 | Обновления | `apt update && apt full-upgrade`, reboot при новом ядре | раздел 4 |
| 2 | Учётки и sudo | свой пользователь + ключ, sudo через `sudoers.d`, лишние учётки заблокированы | раздел 3 |
| 3 | SSH | ключи, `PermitRootLogin no`, `AllowGroups`, fail2ban | [../Network/08_ssh.md](/network/08-ssh) + раздел 2 |
| 4 | Firewall | deny incoming, SSH только из админской сети | [../Network/11_firewall_iptables.md](/network/11-firewall-iptables) + раздел 5 |
| 5 | Поверхность | лишние сервисы выключены, пакеты удалены, SUID проверены | раздел 5 |
| 6 | Ядро | sysctl-харденинг в `/etc/sysctl.d/` | раздел 6 |
| 7 | Аудит | auditd с правилами на учётки, sudo, sshd, root-команды | раздел 7 |
| 8 | MAC | AppArmor/SELinux в enforce, отказы читаются | раздел 8 |
| 9 | Логи и время | journald persistent, логи уходят с хоста, chrony/timesyncd | [../Left/03_Logging/05_log_sources.md](/logging/05-log-sources) |
| 10 | Проверка | Lynis до/после, CIS-профиль | раздел 9 |
| 11 | Код | всё это — Ansible-роль, прогон идемпотентен | раздел 10 |

> ⭐ Харденинг, сделанный руками, живёт до первого нового сервера. Цель — роль в git,
> которая даёт одинаковый результат на 1 и на 100 машинах, и проверка, которая это подтверждает.

---

## 2. SSH и доступ: что добавить к базовому hardening

Базовый `sshd_config` и fail2ban — в [../Network/08_ssh.md](/network/08-ssh) (раздел 6).
Здесь — то, на чём спотыкаются в реальной жизни.

**Смотри эффективный конфиг, а не файл.** В `sshd_config` действует правило «первое значение
выигрывает», а в Ubuntu `Include /etc/ssh/sshd_config.d/*.conf` стоит **в начале** файла.
```bash
sudo sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|allowgroups|maxauthtries)'
sudo sshd -T -C user=deploy,host=admin.lab,addr=192.168.56.1 | grep -i passwordauth   # как сработают Match-блоки
ls /etc/ssh/sshd_config.d/        # ⚠️ облачные образы кладут сюда 50-cloud-init.conf с PasswordAuthentication yes
```text
Поэтому свой drop-in называй так, чтобы он читался первым:
```sshconfig
# /etc/ssh/sshd_config.d/00-hardening.conf
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no      # в OpenSSH 8.7+ заменил ChallengeResponseAuthentication
PubkeyAuthentication yes
AllowGroups ssh-users                # группой удобнее, чем списком AllowUsers
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
```text
```bash
sudo groupadd -f ssh-users && sudo usermod -aG ssh-users vagrant   # ⚠️ СНАЧАЛА добавь себя в группу
sudo sshd -t && sudo systemctl reload ssh                          # проверка → reload
ssh sec01 true && echo "новая сессия входит"                        # старую не закрывай, пока не проверил
```text
Проверка снаружи — `ssh-audit 192.168.56.30` (пакет `ssh-audit`): покажет слабые алгоритмы
обмена ключами, MAC и шифры.

---

## 3. Пользователи и sudo

Основы (`useradd`, группы, `/etc/sudoers`) — в [../Linux/05_user_management.md](/linux/05-user-management).
Харденинг поверх них:

```bash
awk -F: '$3==0 {print $1}' /etc/passwd            # UID 0 должен быть только у root
sudo awk -F: '$2=="" {print $1}' /etc/shadow      # учётки с пустым паролем → пусто
sudo passwd -S -a | awk '$2=="P" {print $1}'      # у кого вообще есть пароль
lastlog -b 90                                     # кто не входил больше 90 дней
sudo usermod -L olduser && sudo chage -E 0 olduser   # заблокировать пароль и «истечь» учётку
sudo usermod -s /usr/sbin/nologin svc-app         # сервисной учётке shell не нужен
```text
**sudo — только через `visudo` и `sudoers.d`:**
```bash
sudo visudo -f /etc/sudoers.d/00-defaults     # visudo проверяет синтаксис ДО записи
sudo visudo -c                                # проверить все файлы sudoers разом
```text
```text
# /etc/sudoers.d/00-defaults
Defaults use_pty                          # команда в отдельном pty: фоновый процесс не перехватит терминал
Defaults logfile="/var/log/sudo.log"      # отдельный лог sudo (плюс записи в auth.log/journal)
Defaults timestamp_timeout=5              # пароль заново через 5 минут
# Defaults log_output                     # опционально: запись вывода сессий, смотреть через sudoreplay

# /etc/sudoers.d/10-deploy — точечное право вместо «всё без пароля»
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart app.service
```text
| ❌ Плохо | Почему | ✅ Лучше |
|----------|--------|----------|
| `deploy ALL=(ALL) NOPASSWD: ALL` | Утёк ключ deploy = root без вопросов | Конкретные команды с полными путями |
| `NOPASSWD: /usr/bin/vim`, `less`, `find`, `tar` | Из них выходят в shell (`:!sh`) — см. GTFOBins | Правка конфигов через `sudoedit` или Ansible |
| `systemctl restart *` | Wildcard пропустит `restart foo --now; …`-трюки и чужие юниты | Перечислить юниты |
| `/etc/sudoers.d/deploy.conf` | ⚠️ Файлы с точкой в имени и на `~` **игнорируются** | `/etc/sudoers.d/10-deploy` |

---

## 4. Обновления: unattended-upgrades, needrestart, перезагрузки

В [../Linux/08_packages.md](/linux/08-packages) пакет только установлен. Что внутри:

```text
# /etc/apt/apt.conf.d/20auto-upgrades — включатель
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";

# /etc/apt/apt.conf.d/50unattended-upgrades — политика (из пакета, не правь)
Unattended-Upgrade::Allowed-Origins { "${distro_id}:${distro_codename}-security"; ... };

# /etc/apt/apt.conf.d/52unattended-upgrades-local — твои переопределения (читается позже → выигрывает)
Unattended-Upgrade::Automatic-Reboot "false";            // true — только для stateless-узлов
Unattended-Upgrade::Automatic-Reboot-Time "03:30";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Package-Blacklist { "postgresql-"; }; // регулярки: базу обновляем руками
```text
```bash
sudo unattended-upgrade --dry-run --debug 2>&1 | tail -20   # что поставилось бы и почему
systemctl list-timers 'apt-daily*'                           # когда запускается
less /var/log/unattended-upgrades/unattended-upgrades.log
cat /var/run/reboot-required.pkgs 2>/dev/null                # есть файл → нужен ребут (обычно ядро/libc)
sudo needrestart -b                                           # какие сервисы держат старые библиотеки
```text
| Тип узла | Security-обновления | Перезагрузка |
|----------|---------------------|--------------|
| Stateless (web, воркеры за балансировщиком) | Автоматически | Автоматически в окне или rolling через Ansible (`serial: 1`) |
| Stateful (БД, брокеры) | Автоматически, кроме самой СУБД | Вручную в maintenance window, с failover |
| Узлы Kubernetes | Через обновление образа ноды / `kubectl drain` | Rolling, по одной ноде |

На Rocky/RHEL то же делает `dnf-automatic`: `upgrade_type = security` и `apply_updates = yes`
в `/etc/dnf/automatic.conf`, затем `systemctl enable --now dnf-automatic.timer`.
Сколько дней можно тянуть с патчем по severity — в [04_vuln_management.md](/security/04-vuln-management).

---

## 5. Поверхность атаки: сервисы, пакеты, SUID, firewall

Каждый слушающий порт и каждый пакет — потенциальная CVE. Не нужен — выключи и удали.
```bash
sudo ss -tulpn                                        # ⭐ что слушает, на каком адресе, какой процесс
systemctl list-units --type=service --state=running
systemctl list-unit-files --state=enabled
sudo systemctl disable --now avahi-daemon.service     # если есть — серверу не нужен
sudo systemctl mask cups.service                      # mask: не запустится даже как зависимость
sudo apt purge -y telnet rsh-client ftp && sudo apt autoremove --purge -y
```text
Правило для слушающих сервисов: БД, Redis, метрики — на `127.0.0.1` или приватном интерфейсе,
наружу — только точка входа (nginx на 443) и SSH из админской сети.

**SUID/SGID-аудит** (что это — в [../Linux/06_permissions.md](/linux/06-permissions)):
```bash
sudo find / -xdev \( -perm -4000 -o -perm -2000 \) -type f -printf '%M %u %p\n' 2>/dev/null \
  | sort -k3 > /root/suid-baseline.txt
dpkg -S /usr/bin/chfn                        # из какого пакета бинарник
# позже: сравнить с baseline — новый SUID-файл без обновления пакетов = повод для расследования
```text
**Firewall в пять строк** (разбор iptables/nftables — в
[../Network/11_firewall_iptables.md](/network/11-firewall-iptables)):
```bash
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow from 192.168.56.0/24 to any port 22 proto tcp    # SSH только из админской сети
sudo ufw allow 443/tcp
sudo ufw enable && sudo ufw status verbose
```text
> ⚠️ На стенде vagrant-libvirt `vagrant ssh` ходит через management-сеть (по умолчанию
> 192.168.121.0/24), а не через 192.168.56.30. Разреши SSH и из неё, иначе `vagrant ssh`
> отвалится (Ansible по 192.168.56.30 продолжит работать).
>
> ⚠️ Docker публикует порты в обход ufw/INPUT — см. раздел 7 в
> [../Network/11_firewall_iptables.md](/network/11-firewall-iptables). Для чувствительных
> серверов ограничивают и **исходящий** трафик: reverse shell и выгрузка данных идут наружу.

---

## 6. sysctl-харденинг ядра

Как работает `sysctl` и чем `-w` отличается от файла — в [../Linux/12_kernel.md](/linux/12-kernel).
Набор для сервера (перед применением посмотри текущие значения: `sysctl &lt;ключ&gt;`):

```ini
# /etc/sysctl.d/60-hardening.conf
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.unprivileged_bpf_disabled = 1
kernel.yama.ptrace_scope = 1
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
fs.protected_fifos = 1
fs.protected_regular = 2
fs.suid_dumpable = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.all.log_martians = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
```text
```bash
sudo sysctl --system          # применить все файлы (порядок: по имени файла, последний выигрывает)
sysctl kernel.kptr_restrict fs.suid_dumpable
```text
| Параметр | Что даёт |
|----------|----------|
| `kernel.kptr_restrict=2` | Адреса ядра в `/proc/kallsyms` скрыты даже от root — эксплойтам ядра сложнее |
| `kernel.dmesg_restrict=1` | `dmesg` только для привилегированных: там утекают адреса и детали железа |
| `kernel.unprivileged_bpf_disabled=1` | `bpf()` без привилегий запрещён (частый вектор LPE); `1` нельзя вернуть без ребута, `2` — можно |
| `kernel.yama.ptrace_scope=1` | `ptrace` только к своим потомкам: процесс не читает память соседа того же UID (`2` — только с `CAP_SYS_PTRACE`, `3` — никому и навсегда) |
| `fs.protected_hardlinks/symlinks=1` | Защита от подмены файлов ссылками в общих каталогах вроде `/tmp` |
| `fs.protected_fifos=1`, `protected_regular=2` | То же для FIFO и обычных файлов в sticky-каталогах |
| `fs.suid_dumpable=0` | SUID-процессы не пишут core dump (в дампе могут быть секреты) |
| `accept_redirects=0`, `send_redirects=0` | ICMP redirect не подменит маршрут; сервер — не роутер |
| `accept_source_route=0` | Source routing — способ обойти фильтрацию |
| `rp_filter=1` | Anti-spoofing (strict); при асимметричной маршрутизации и у некоторых CNI нужен `2` (loose) |
| `log_martians=1` | Логировать пакеты с невозможными адресами источника |
| `tcp_syncookies=1` | Сервер переживает SYN flood (L3/4-DDoS — тема [03_web_edge_security.md](/security/03-web-edge-security)) |

> ⚠️ Харденинг-наборы часто ставят `net.ipv4.ip_forward=0`. На узлах Docker и Kubernetes
> форвардинг обязан быть `1` — иначе контейнеры теряют сеть при следующем `sysctl --system`
> или ребуте.

---

## 7. auditd: кто, когда и что трогал

Однострочник `auditctl -w` есть в [../Left/03_Logging/05_log_sources.md](/logging/05-log-sources).
Здесь — как настроить так, чтобы им реально пользоваться.

```bash
sudo apt install -y auditd audispd-plugins     # audispd-plugins — отправка событий на удалённый сервер
sudo systemctl enable --now auditd
sudo auditctl -s          # enabled 1 (2 = immutable), lost — сколько событий потеряно
sudo auditctl -l          # загруженные правила
```text
Правила — файлами в `/etc/audit/rules.d/`, их склеивает `augenrules` в `/etc/audit/audit.rules`:
```text
# /etc/audit/rules.d/50-hardening.rules
## учётки, sudo, sshd: -w путь -p права(r/w/x/a) -k ключ-для-поиска
-w /etc/passwd -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/sudoers -p wa -k sudoers
-w /etc/sudoers.d/ -p wa -k sudoers
-w /etc/ssh/sshd_config -p wa -k sshd
-w /etc/ssh/sshd_config.d/ -p wa -k sshd
## команды с правами root, запущенные людьми (auid — кто залогинился; не меняется после sudo)
-a always,exit -F arch=b64 -S execve -F euid=0 -F auid>=1000 -F auid!=unset -k root_cmds
-a always,exit -F arch=b32 -S execve -F euid=0 -F auid>=1000 -F auid!=unset -k root_cmds
## загрузка модулей ядра и смена времени
-a always,exit -F arch=b64 -S init_module,finit_module,delete_module -k modules
-a always,exit -F arch=b64 -S adjtimex,settimeofday,clock_settime -k time_change

# /etc/audit/rules.d/99-finalize.rules — последним
-e 2
```text
```bash
sudo augenrules --check && sudo augenrules --load
```text
> ⚠️ `-e 2` делает правила **неизменяемыми до перезагрузки**: злоумышленник с root не выключит
> аудит тихо, но и ты не поправишь правило без ребута. На стенде включай в самом конце.

Поиск и отчёты:
```bash
sudo ausearch -k identity -i --start today            # -i: uid→имя, syscall→название, hex→текст
sudo ausearch -k root_cmds -i --start recent          # recent = последние 10 минут
sudo ausearch -ua 1000 -i --start today               # всё, что делал UID 1000 (uid/euid/auid)
sudo aureport -au --summary -i                        # аутентификации: кто, сколько, успех/провал
sudo aureport -x --summary                            # какие бинарники запускались чаще всего
sudo aureport --failed --summary -i                   # неудачные события
```text
Как читать событие: одно действие = несколько записей с общим `msg=audit(время:ID)`:
`SYSCALL` (кто: `auid=1000 uid=0 exe="/usr/bin/vim" key="identity"`), `PATH` (какой файл),
`PROCTITLE` (полная команда, с `-i` — текстом).

| Параметр | Зачем |
|----------|-------|
| `-b 8192` | Буфер событий; при `lost > 0` в `auditctl -s` — увеличить |
| `-f 1` | При сбое — сообщение в лог ядра; ⚠️ `-f 2` = kernel panic при сбое аудита |
| Не аудировать `open/read` на всё | Шторм событий, нагрузка, диск кончится |

⭐ Локальный `/var/log/audit/audit.log` root может стереть. Логи аудита уходят с хоста сразу:
плагин `au-remote` (audispd-plugins) или агент в Loki/ELK — неизменяемость логов в
[07_security_incidents_compliance.md](/security/07-security-incidents-compliance).

---

## 8. AppArmor и SELinux на практике

MAC (mandatory access control) ограничивает процесс, **даже если он root**: взломанный nginx
не прочитает `/etc/shadow`, потому что профиль/политика ему этого не разрешают.

| | AppArmor | SELinux |
|---|----------|---------|
| Где по умолчанию | Ubuntu, Debian, SUSE | RHEL, Rocky, Alma, Fedora |
| Модель | Профили по путям к бинарникам | Метки (контексты) на процессах, файлах, портах |
| Режимы | enforce / complain / unconfined | enforcing / permissive / disabled |
| Статус | `sudo aa-status` | `getenforce`, `sestatus` |
| Где отказы | `journalctl -k`: `apparmor="DENIED"` (с auditd — в audit.log) | `/var/log/audit/audit.log`: `type=AVC ... denied` |
| Ослабить одного | `aa-complain &lt;бинарник&gt;` | `semanage permissive -a httpd_t` (один домен) |

### AppArmor (sec01)
```bash
sudo apt install -y apparmor-utils              # aa-complain, aa-enforce, aa-logprof
sudo aa-status | head -15                        # сколько профилей в enforce/complain
sudo cp /usr/bin/cat /usr/local/bin/mycat
sudo tee /etc/apparmor.d/usr.local.bin.mycat >/dev/null <<'EOF'
#include &lt;tunables/global&gt;
/usr/local/bin/mycat {
  #include &lt;abstractions/base&gt;
  #include &lt;abstractions/consoles&gt;
  /tmp/** r,
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/usr.local.bin.mycat   # загрузить/перезагрузить профиль
echo hi > /tmp/a && mycat /tmp/a                 # разрешено
mycat /etc/hostname                              # Permission denied — хотя права 644
sudo journalctl -k --since "-5min" | grep 'apparmor="DENIED"'
#  apparmor="DENIED" operation="open" profile="/usr/local/bin/mycat" name="/etc/hostname" requested_mask="r" ...
sudo aa-complain /usr/local/bin/mycat && mycat /etc/hostname   # работает, в логе apparmor="ALLOWED"
sudo aa-enforce  /usr/local/bin/mycat
```text
Для реальных сервисов профиль генерируют `aa-genprof`/`aa-logprof`: запускаешь сервис в
complain, гоняешь сценарии, утилита предлагает правила по логам.

### SELinux (rocky01)
```bash
getenforce && sestatus                           # Enforcing, policy targeted
grep ^SELINUX= /etc/selinux/config               # режим после ребута
sudo dnf install -y nginx policycoreutils-python-utils   # semanage, audit2why, audit2allow
ls -Z /usr/share/nginx/html; ps -eZ | grep nginx # контекст файла и домен процесса (httpd_t)
```text
Типовой отказ: nginx раздаёт `/srv/www`, а в ответ 403.
```bash
sudo ausearch -m AVC,USER_AVC -ts recent -i
#  avc: denied { read } for comm="nginx" name="index.html"
#       scontext=system_u:system_r:httpd_t:s0 tcontext=unconfined_u:object_r:var_t:s0 tclass=file
sudo ausearch -m AVC -ts recent | audit2why      # объяснит причину и подскажет исправление
sudo semanage fcontext -a -t httpd_sys_content_t '/srv/www(/.*)?'   # правило в политику (переживёт relabel)
sudo restorecon -Rv /srv/www                     # применить к файлам
```text
| Симптом (AVC) | Исправление |
|---------------|-------------|
| Файл с чужой меткой (`var_t`, `user_home_t`) | `semanage fcontext -a -t &lt;тип&gt; '&lt;путь&gt;(/.*)?'` + `restorecon -Rv` |
| Сервис слушает нестандартный порт | `semanage port -a -t http_port_t -p tcp &lt;порт&gt;`; если порт уже за другим типом (8081 в Rocky 9 — `transproxy_port_t`) — `-m` вместо `-a` |
| nginx не может в `proxy_pass` (`name_connect`) | `sudo setsebool -P httpd_can_network_connect on` |
| Ничего не подходит | `audit2allow -a -M mymod` → **прочитай .te**, потом `semodule -i` — крайний случай |

> ⭐ «Выключить SELinux» (`setenforce 0`, `SELINUX=disabled`) — не решение, а удаление слоя
> защиты. Правильно: прочитать AVC, понять, какой метки/булева/порта не хватает, и дать ровно это.
> `chcon` меняет метку временно — первый же `restorecon` или relabel её откатит.

---

## 9. CIS Benchmark и Lynis: как проверить результат

**CIS Benchmark** — бесплатный (после регистрации) документ от Center for Internet Security
на конкретную версию ОС/софта: сотни рекомендаций с обоснованием, проверкой и исправлением.
- **Level 1** — базовый уровень, почти не ломает функциональность; **Level 2** — глубже,
  для чувствительных систем, может ломать (например, строгие опции монтирования).
- Профили **Server** и **Workstation**; рекомендации **Automated** (проверяются скриптом)
  и **Manual**.
- Инструменты: CIS-CAT (от CIS), **OpenSCAP** + SCAP Security Guide (семейство RHEL,
  `oscap xccdf eval --profile … --report report.html &lt;datastream&gt;`), **Ubuntu Security Guide**
  (нужна подписка Ubuntu Pro, бесплатная для личного использования:
  `sudo usg audit cis_level1_server`, отчёты в `/var/lib/usg/`). Версии бенчмарков меняются —
  проверь актуальную редакцию под свою ОС.

**Lynis** — open-source аудит (не привязан к одному стандарту): сотни проверок, предупреждения,
советы и итоговый **hardening index**.
```bash
sudo apt install -y lynis             # в 22.04 — ветка 3.0.x; свежая 3.1.x — из репозитория CISOfy
sudo lynis audit system --quick       # --quick: не ждать Enter между разделами
sudo grep -E '^hardening_index' /var/log/lynis-report.dat
sudo grep -E '^warning\[\]' /var/log/lynis-report.dat                 # сначала — предупреждения
sudo grep -E '^suggestion\[\]' /var/log/lynis-report.dat | cut -d'|' -f1,2 | head -20
sudo lynis show details SSH-7408      # подробности конкретной проверки из лога
```text
`/var/log/lynis.log` — полный лог прогона, `/var/log/lynis-report.dat` — машиночитаемый отчёт.

Что такое hardening index и чем он **не** является:
- ✅ Относительный показатель: сравнивай «до/после» на одной машине одной версией Lynis.
- ❌ Не процент соответствия CIS/PCI и не «безопасность в баллах»: часть советов не про твой
  сервер, а баллы можно «накрутить», не закрыв реальных дыр.
- ⭐ Сначала разбирай `warning[]`, потом `suggestion[]`; то, что осознанно не делаешь, —
  в исключения (`skip-test` в custom-профиле Lynis) с причиной.

---

## 10. Всё это — Ansible-ролью

Структура роли — в [../Ansible/11_roles.md](/ansible/11-roles). Каркас для sec01:
```text
~/labs/security/ansible/
├── inventory.ini              # sec01 ansible_host=192.168.56.30 ansible_user=vagrant ...
├── requirements.yml           # коллекции ansible.posix, community.general
├── harden.yml                 # hosts: sec01 · become: true · roles: [hardening]
└── roles/hardening/
    ├── defaults/main.yml      # всё, что настраивается
    ├── handlers/main.yml      # reload ssh, load audit rules
    ├── tasks/main.yml         # import_tasks: packages, users, ssh, sysctl, auditd, updates, firewall
    └── templates/             # 00-hardening.conf.j2, 50-hardening.rules.j2, 52unattended-upgrades-local.j2
```text
```yaml
# roles/hardening/defaults/main.yml
hardening_ssh_group: ssh-users
hardening_ssh_members: [vagrant]              # ⚠️ без себя в группе — потеряешь доступ
hardening_admin_net: 192.168.56.0/24
hardening_packages_absent: [telnet, rsh-client, ftp]
hardening_auto_reboot: false
hardening_sysctl:
  kernel.kptr_restrict: 2
  kernel.dmesg_restrict: 1
  fs.suid_dumpable: 0
  net.ipv4.conf.all.accept_redirects: 0
  net.ipv4.tcp_syncookies: 1
  # ... остальное из раздела 6; на Docker/k8s-узлах: net.ipv4.ip_forward: 1

# roles/hardening/tasks/ssh.yml
- name: SSH group exists and admins are members        # порядок: сначала группа
  ansible.builtin.user:
    name: "&#123;&#123; item &#125;&#125;"
    groups: "&#123;&#123; hardening_ssh_group &#125;&#125;"
    append: true
  loop: "&#123;&#123; hardening_ssh_members &#125;&#125;"
  # (группу создаёт предыдущая задача ansible.builtin.group)

- name: sshd hardening drop-in
  ansible.builtin.template:
    src: 00-hardening.conf.j2
    dest: /etc/ssh/sshd_config.d/00-hardening.conf
    mode: "0600"
    validate: /usr/sbin/sshd -t -f %s             # битый конфиг не попадёт на сервер
  notify: reload ssh

# roles/hardening/tasks/sysctl.yml
- name: Kernel hardening
  ansible.posix.sysctl:
    name: "&#123;&#123; item.key &#125;&#125;"
    value: "&#123;&#123; item.value &#125;&#125;"
    sysctl_file: /etc/sysctl.d/60-hardening.conf
    reload: true
  loop: "&#123;&#123; hardening_sysctl | dict2items &#125;&#125;"

# roles/hardening/tasks/firewall.yml
- name: SSH only from admin network
  community.general.ufw: { rule: allow, port: "22", proto: tcp, from_ip: "&#123;&#123; hardening_admin_net &#125;&#125;" }
- name: Default deny incoming and enable
  community.general.ufw: { state: enabled, policy: deny, direction: incoming }

# roles/hardening/handlers/main.yml
- name: reload ssh
  ansible.builtin.service: { name: ssh, state: reloaded }
- name: load audit rules
  ansible.builtin.command: augenrules --load
```text
```bash
ansible-galaxy collection install -r requirements.yml
ansible-playbook -i inventory.ini harden.yml --check --diff   # что изменится
ansible-playbook -i inventory.ini harden.yml                  # применить
ansible-playbook -i inventory.ini harden.yml                  # ⭐ второй прогон: changed=0
```text
Полный разбор с Lynis до/после — лаба 1 в [08_practice_labs.md](/softskills/08-practice-labs).

**Готовая альтернатива — коллекция `devsec.hardening`** (роли `os_hardening`, `ssh_hardening`,
`nginx_hardening`): много проверенных настроек сразу. Но прочитай README и defaults до запуска:
например, `os_hardening` по умолчанию выключает `net.ipv4.ip_forward`, и на Docker/k8s-узлах
его нужно вернуть через `sysctl_overwrite` — об этом прямо написано в README роли.

---

## 11. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `AllowGroups ssh-users`, а себя в группу не добавил | Потерял SSH-доступ | Сначала группа и участники, потом sshd; вторая сессия открыта |
| Drop-in `99-hardening.conf` | `50-cloud-init.conf` прочитан раньше: `PasswordAuthentication yes` выиграл | Имя `00-…`, проверка через `sshd -T` |
| `ufw enable` без правила для SSH | Отрезал себя | Сначала `allow 22 from …`, потом `enable`; консоль облака под рукой |
| `-e 2` на стенде в начале лабы | Правила не поменять до ребута | Включать последним |
| `setenforce 0` «чтобы заработало» | Минус целый слой защиты, навсегда | `audit2why` → fcontext/port/boolean |
| `chcon` вместо `semanage fcontext` | Метка слетит при relabel | `semanage fcontext` + `restorecon` |
| `ip_forward=0` из харденинг-набора на Docker-узле | Контейнеры без сети после ребута | Исключение в роли для Docker/k8s |
| `Automatic-Reboot "true"` на базе | Ночной ребут primary без failover | Авторебут только stateless, базы — в окне |
| fail2ban банит NAT-адрес офиса | Вся команда без SSH | `ignoreip` для админских сетей, доступ через bastion/VPN |
| Hardening index как KPI | Накрутка баллов, реальные дыры на месте | Warnings → suggestions → осознанные исключения |
| `NOPASSWD: /usr/bin/vim` | Shell с root через `:!sh` | Точечные команды, `sudoedit` |
| auditd на `open` для всей ФС | Шторм событий, `lost > 0`, диск | Точечные `-w` и syscall-правила с фильтрами |

---

## 💼 Как это в DevOps

- Харденинг живёт в **golden image** (Packer + Ansible-роль) и в роли, которая
  догоняет уже работающие серверы. Ручные правки на проде — дрейф, который роль перезапишет.
- Проверка — в CI: Lynis или OpenSCAP на свежесобранном образе, отчёт — артефакт пайплайна,
  падение по новым warnings.
- Аудиторы и безопасники спрашивают не «настроено ли», а «чем подтвердишь»: отчёт CIS/Lynis,
  конфиг в git, логи auditd в центральном хранилище.
- SELinux/AppArmor не выключают «для удобства»: Kubernetes и Docker опираются на них
  (профиль `RuntimeDefault`, метки `container_t`) — см. [06_k8s_security.md](/security/06-k8s-security).
- Типовая задача на старте работы: «пройдись по серверам и приведи к стандарту» — это ровно
  эта тема плюс инвентарь Ansible.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Эффективный конфиг sshd | `sudo sshd -T \| grep -i passwordauth` |
| Проверить sudoers | `sudo visudo -c` |
| Кто root (UID 0) | `awk -F: '$3==0' /etc/passwd` |
| Что слушает | `sudo ss -tulpn` |
| Выключить сервис насовсем | `sudo systemctl disable --now X && sudo systemctl mask X` |
| SUID-файлы | `sudo find / -xdev -perm -4000 -type f` |
| Проверить автообновления | `sudo unattended-upgrade --dry-run --debug` |
| Нужен ли ребут | `ls /var/run/reboot-required`, `sudo needrestart -b` |
| Применить sysctl | `sudo sysctl --system` |
| Загрузить audit-правила | `sudo augenrules --load && sudo auditctl -l` |
| Найти по ключу | `sudo ausearch -k identity -i --start today` |
| Отчёт по входам | `sudo aureport -au --summary -i` |
| Статус AppArmor | `sudo aa-status` |
| Отказы AppArmor | `journalctl -k \| grep 'apparmor="DENIED"'` |
| Отказы SELinux | `sudo ausearch -m AVC -ts recent \| audit2why` |
| Исправить метку | `semanage fcontext -a -t T '/p(/.*)?' && restorecon -Rv /p` |
| Аудит Lynis | `sudo lynis audit system --quick` |
| Hardening index | `sudo grep hardening_index /var/log/lynis-report.dat` |
| CIS на Ubuntu Pro | `sudo usg audit cis_level1_server` |

---

## 🧠 Что запомнить

1. Порядок: страховка (snapshot, консоль, вторая сессия) → обновления → доступ → firewall →
   поверхность → sysctl → аудит → MAC → проверка → роль в git.
2. SSH смотри через `sshd -T`: действует первое значение, drop-in `00-…` должен читаться первым.
3. sudo — точечные команды с полными путями через `visudo`; `NOPASSWD: ALL` и редакторы под sudo — дыра.
4. Security-обновления ставятся автоматически; перезагрузки — по типу узла (stateless сами, базы в окне).
5. Каждый слушающий порт и пакет — поверхность атаки: `ss -tulpn` и `systemctl list-units` на каждом сервере.
6. sysctl-набор защищает ядро и сеть, но `ip_forward` на Docker/k8s-узлах должен остаться `1`.
7. auditd отвечает на «кто это сделал» через `auid`; ключи `-k` делают поиск быстрым; логи — сразу с хоста.
8. MAC ограничивает даже root; отказ читают (`DENIED`/AVC) и чинят точечно, а не выключают защиту.
9. Hardening index — относительная метрика «до/после», а не процент безопасности.
10. Ручной харденинг не масштабируется: роль, `--check --diff`, повторный прогон с `changed=0`.

➡️ Дальше: [03_web_edge_security.md](/security/03-web-edge-security) · задачи: 02_linux_hardening_tasks.md


---

### Блок A. Теория


**A1.** Почему порядок шагов харденинга важен? Что входит в шаг 0 «страховка»?

<details><summary>Ответ</summary>

Потому что часть шагов (SSH, firewall) может отрезать тебя от сервера, а часть
(обновления) требует ребута. Сначала то, что защищает от потери доступа, потом остальное.
Страховка: snapshot/бэкап, доступ к консоли (VNC/serial облака или `virsh console`),
вторая открытая SSH-сессия.

</details>

**A2.** ⭐ Почему конфиг sshd проверяют через `sshd -T`, а не чтением `sshd_config`? Как это
связано с именем drop-in файла?

<details><summary>Ответ</summary>

В `sshd_config` действует правило «первое значение выигрывает», а `Include
/etc/ssh/sshd_config.d/*.conf` в Ubuntu стоит в начале файла. `sshd -T` печатает итоговые
значения после всех include и Match. Drop-in с `PasswordAuthentication no` должен читаться
раньше `50-cloud-init.conf`, поэтому его называют `00-…`.

</details>

**A3.** Что даёт `AllowGroups ssh-users` и что нужно сделать до того, как его включить?

<details><summary>Ответ</summary>

SSH разрешён только членам группы — удобнее списка `AllowUsers`. До включения: создать
группу и добавить в неё себя и автоматизацию (Ansible-пользователь), иначе потеряешь доступ.

</details>

**A4.** Зачем `Defaults use_pty` и `Defaults logfile` в sudoers? Почему файл
`/etc/sudoers.d/deploy.conf` не сработает?

<details><summary>Ответ</summary>

`use_pty` запускает команду в отдельном псевдотерминале: фоновый процесс, запущенный
через sudo, не перехватит терминал пользователя. `logfile` — отдельный журнал sudo помимо
auth.log/journal. Файлы в `sudoers.d` с точкой в имени или оканчивающиеся на `~` игнорируются.

</details>

**A5.** ⭐ Почему `deploy ALL=(root) NOPASSWD: /usr/bin/vim` — фактически root без пароля?

<details><summary>Ответ</summary>

Из vim запускается shell (`:!sh`), и он наследует root. То же у `less`, `find`, `tar`,
`awk` и многих других — список на GTFOBins. Правка конфигов — через `sudoedit` или Ansible.

</details>

**A6.** Чем отличаются `20auto-upgrades`, `50unattended-upgrades` и `52unattended-upgrades-local`?
Почему переопределения кладут в отдельный файл?

<details><summary>Ответ</summary>

`20auto-upgrades` включает периодическое обновление списков и запуск
unattended-upgrade; `50unattended-upgrades` — политика из пакета (origins, blacklist);
`52…-local` читается позже и переопределяет. Свой файл не затирается при обновлении пакета
и не вызывает конфликтов dpkg.

</details>

**A7.** Как политика перезагрузок после обновлений зависит от типа узла?

<details><summary>Ответ</summary>

Stateless-узлы за балансировщиком — авторебут в окне или rolling (`serial: 1`);
stateful (БД, брокеры) — обновления автоматически, кроме самой СУБД, ребут вручную в окне
с failover; узлы Kubernetes — через drain и обновление образа ноды, по одной.

</details>

**A8.** Чем `systemctl disable --now` отличается от `systemctl mask`?

<details><summary>Ответ</summary>

`disable --now` останавливает сервис и убирает автозапуск, но его может запустить
другой юнит как зависимость или человек руками. `mask` делает ссылку на `/dev/null` — юнит
невозможно запустить, пока не `unmask`.

</details>

**A9.** ⭐ Что дают `kernel.kptr_restrict=2`, `kernel.yama.ptrace_scope=1`, `fs.suid_dumpable=0`,
`net.ipv4.conf.all.rp_filter=1`?

<details><summary>Ответ</summary>

`kptr_restrict=2` скрывает адреса ядра даже от root — усложняет эксплойты ядра;
`ptrace_scope=1` разрешает ptrace только к своим потомкам — процесс не читает память соседа
того же UID; `suid_dumpable=0` — SUID-процессы не пишут core dump с секретами; `rp_filter=1` —
строгая проверка обратного пути, защита от спуфинга адреса источника.

</details>

**A10.** Почему `net.ipv4.ip_forward=0` из харденинг-набора опасен на узле Docker/Kubernetes?

<details><summary>Ответ</summary>

Контейнерная сеть работает через маршрутизацию между bridge/veth и внешним
интерфейсом. При `ip_forward=0` после `sysctl --system` или ребута контейнеры теряют доступ
наружу и снаружи.

</details>

**A11.** ⭐ Чем в auditd отличаются `uid`, `euid` и `auid`? Зачем в правиле `-F auid>=1000 -F auid!=unset`?

<details><summary>Ответ</summary>

`uid` — реальный пользователь процесса, `euid` — эффективный (после sudo/SUID станет 0),
`auid` — login UID: кто изначально залогинился, не меняется после `sudo`/`su`. Фильтр
`auid>=1000 auid!=unset` оставляет действия людей и отбрасывает системные процессы и демоны
(у них `auid` не установлен), иначе шум.

</details>

**A12.** Что делает `-e 2` в правилах auditd? Какая у этого цена?

<details><summary>Ответ</summary>

Правила становятся неизменяемыми до перезагрузки: атакующий с root не выключит аудит
незаметно (понадобится ребут — это видно). Цена: ты тоже не поменяешь правила без ребута,
поэтому `-e 2` ставят последним и включают после отладки.

</details>

**A13.** Чем модель AppArmor отличается от модели SELinux? Назови режимы каждого.

<details><summary>Ответ</summary>

AppArmor — профили по путям к бинарникам (что может этот исполняемый файл);
SELinux — метки на процессах, файлах и портах, политика разрешает доступ домена к типу.
AppArmor: enforce / complain / unconfined. SELinux: enforcing / permissive / disabled.

</details>

**A14.** ⭐ Почему «выключить SELinux» — не решение? Чем `chcon` хуже `semanage fcontext` + `restorecon`?

<details><summary>Ответ</summary>

Выключение удаляет целый слой защиты для всех сервисов, а причина обычно — одна
неправильная метка, порт или boolean. Правильно: прочитать AVC, `audit2why`, дать ровно
недостающее. `chcon` меняет метку только на файле; первый `restorecon` или полный relabel её
откатит. `semanage fcontext` записывает правило в политику, `restorecon` применяет — переживает relabel.

</details>

**A15.** Что такое CIS Benchmark? Чем Level 1 отличается от Level 2, Automated от Manual?

<details><summary>Ответ</summary>

Документ Center for Internet Security под конкретную ОС/софт: рекомендации с обоснованием,
проверкой и исправлением. Level 1 — базовый, почти не ломает функциональность; Level 2 — глубже,
для чувствительных систем, может ломать. Automated проверяются скриптом, Manual — вручную.
Инструменты: CIS-CAT, OpenSCAP + SCAP Security Guide, Ubuntu Security Guide (Ubuntu Pro).

</details>

**A16.** Что такое hardening index Lynis и чем он **не** является?

<details><summary>Ответ</summary>

Относительная оценка по проверкам Lynis: удобна для сравнения «до/после» на одной
машине одной версией Lynis. Это не процент соответствия CIS/PCI и не «безопасность в баллах»:
часть советов нерелевантна, баллы можно накрутить, не закрыв реальных дыр.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # /etc/ssh/sshd_config.d/
```text
<details><summary>Ответ</summary>

⚠️ Первое значение выигрывает: `50-cloud-init.conf` читается раньше `99-…`, пароли
остаются включены. Переименовать в `00-hardening.conf` или убрать строку из cloud-init,
проверить `sshd -T | grep passwordauth`.

</details>

```text:no-line-numbers
     50-cloud-init.conf:   PasswordAuthentication yes
```text
```text:no-line-numbers
     99-hardening.conf:    PasswordAuthentication no
```text
```text:no-line-numbers
B2.  # /etc/sudoers.d/10-deploy
```text
<details><summary>Ответ</summary>

⚠️ Wildcard разрешает любые аргументы: любой юнит, `edit` (открывает редактор под root
→ shell), `link`/`enable` своего юнита с `ExecStart=/bin/sh`. Перечислить конкретные команды
и юниты полностью.

</details>

```text:no-line-numbers
     deploy ALL=(root) NOPASSWD: /usr/bin/systemctl *
```text
```text:no-line-numbers
B3.  sudo visudo -f /etc/sudoers.d/deploy.conf      # файл создан, правило внутри верное
```text
<details><summary>Ответ</summary>

⚠️ Файлы с точкой в имени sudo игнорирует — правило не действует, и это тихо.
Имя `10-deploy`.

</details>

```text:no-line-numbers
B4.  sudo ufw default deny incoming
```text
<details><summary>Ответ</summary>

⚠️ После `enable` входящие закрыты, а SSH-правило добавляется только третьей
командой — текущая сессия может выжить за счёт conntrack, но новые подключения рвутся;
при ошибке в третьей команде доступ потерян. Сначала `allow`, потом `enable`.

</details>

```text:no-line-numbers
     sudo ufw enable
```text
```text:no-line-numbers
     sudo ufw allow from 192.168.56.0/24 to any port 22 proto tcp
```text
```text:no-line-numbers
B5.  # /etc/sysctl.d/60-hardening.conf на узле с Docker
```text
<details><summary>Ответ</summary>

⚠️ После `sysctl --system`/ребута контейнеры без сети. Для Docker/k8s-узлов
`ip_forward = 1` — исключение в роли.

</details>

```text:no-line-numbers
     net.ipv4.ip_forward = 0
```text
```text:no-line-numbers
B6.  # /etc/audit/rules.d/50-files.rules
```text
<details><summary>Ответ</summary>

⚠️ Аудит всех открытий файлов: шторм событий, нагрузка на CPU, `lost > 0`, диск
кончится. Точечные `-w` на критичные пути и syscall-правила с фильтрами.

</details>

```text:no-line-numbers
     -a always,exit -F arch=b64 -S open,openat -k files
```text
```text:no-line-numbers
B7.  # /etc/audit/rules.d/00-base.rules  (первый файл по алфавиту)
```text
<details><summary>Ответ</summary>

⚠️ `-e 2` загружается первым — всё, что после, уже не применится («правила
неизменяемы»). `-e 2` — в последнем файле (`99-finalize.rules`).

</details>

```text:no-line-numbers
     -e 2
```text
```text:no-line-numbers
     -w /etc/passwd -p wa -k identity
```text
```text:no-line-numbers
B8.  sudo setenforce 0
```text
<details><summary>Ответ</summary>

⚠️ SELinux выключен для всей системы ради одной метки; при `disabled` файлы перестают
маркироваться, и обратное включение потребует полного relabel. Нужен `audit2why` и точечное исправление.

</details>

```text:no-line-numbers
     sudo sed -i 's/^SELINUX=.*/SELINUX=disabled/' /etc/selinux/config   # «nginx заработал»
```text
```text:no-line-numbers
B9.  sudo chcon -R -t httpd_sys_content_t /srv/www     # через месяц после relabel снова 403
```text
<details><summary>Ответ</summary>

⚠️ `chcon` не пишет правило в политику: relabel вернул `var_t`/`default_t`. Правильно:
`semanage fcontext -a -t httpd_sys_content_t '/srv/www(/.*)?'` + `restorecon -Rv /srv/www`.

</details>

```text:no-line-numbers
B10.  # /etc/apt/apt.conf.d/52unattended-upgrades-local на primary PostgreSQL
```text
<details><summary>Ответ</summary>

⚠️ Автоперезагрузка primary без failover и согласования — простой базы в 03:30.
Для stateful — ребут вручную в окне, СУБД в `Package-Blacklist`.

</details>

```text:no-line-numbers
     Unattended-Upgrade::Automatic-Reboot "true";
```text
```text:no-line-numbers
B11.  - name: sshd config
```text
<details><summary>Ответ</summary>

⚠️ Нет `validate: /usr/sbin/sshd -t -f %s`: битый шаблон попадёт на сервер, а restart
положит sshd. Лучше drop-in в `sshd_config.d/`, `validate` и `reload` вместо `restart`.

</details>

```text:no-line-numbers
       ansible.builtin.template: { src: sshd_config.j2, dest: /etc/ssh/sshd_config }
```text
```text:no-line-numbers
       notify: restart ssh
```text
```text:no-line-numbers
B12.  «Lynis hardening index вырос с 61 до 84 — сервер защищён на 84%.»
```text
<details><summary>Ответ</summary>

⚠️ Индекс — относительная метрика проверок Lynis, а не процент безопасности. Важно,
закрыты ли warnings и реальные риски сервера.

</details>


---

### Блок C. Практика


### C1. 🔑 SSH: эффективный конфиг и группа доступа
На `sec01`: посмотри эффективные значения `permitrootlogin`, `passwordauthentication`,
`kbdinteractiveauthentication` через `sshd -T`; проверь, что лежит в `/etc/ssh/sshd_config.d/`.
Создай группу `ssh-users`, добавь `vagrant`, положи `00-hardening.conf` из конспекта, `sshd -t`,
reload, проверь вход новой сессией. Убедись, что пользователь вне группы не входит.

### C2. sudo по-взрослому
Создай пользователя `deploy`, дай ему право только на `systemctl restart app.service` (юнит
можно создать-заглушку). Добавь `00-defaults` с `use_pty` и `logfile`. Проверь `visudo -c`,
`sudo -l -U deploy`, попробуй от `deploy` выполнить что-то сверх разрешённого и найди попытку в логе.

### C3. 🔑 auditd: найти «кто это сделал»
Поставь auditd, положи `50-hardening.rules` **без** `-e 2`, загрузи `augenrules --load`.
От `vagrant` через sudo создай пользователя `eve`, поправь `/etc/ssh/sshd_config.d/00-hardening.conf`,
выполни `sudo id`. Найди все три события через `ausearch -k … -i` и определи для каждого
`auid`, `uid`, `exe`, команду. Сделай отчёт `aureport -au --summary -i` и `aureport -x --summary`.

### C4. sysctl-харденинг
Запиши текущие значения ключей из раздела 6, примени `60-hardening.conf`, проверь.
Покажи эффект двух параметров: `dmesg` от обычного пользователя после `dmesg_restrict=1`;
`cat /proc/kallsyms | head -3` от root после `kptr_restrict=2`.

### C5. Обновления без сюрпризов
Проверь `20auto-upgrades`, создай `52unattended-upgrades-local` (без авторебута, исключение
для `postgresql-`), запусти `unattended-upgrade --dry-run --debug`, найди таймеры `apt-daily*`,
проверь `reboot-required` и `needrestart -b`. На `rocky01` — то же через `dnf-automatic`.

### C6. SUID-baseline и детект нового SUID
Сними baseline SUID/SGID в `/root/suid-baseline.txt`. ⚠️ Только на `sec01`: сделай
`sudo cp /usr/bin/bash /usr/local/bin/rootsh && sudo chmod u+s /usr/local/bin/rootsh`. Найди
отличие от baseline одной командой, объясни, почему этот файл опасен, удали его.

### C7. AppArmor: профиль, отказ, complain, enforce
Повтори пример с `mycat` из конспекта: профиль разрешает только `/tmp/**`. Получи `DENIED`
в `journalctl -k`, переведи в complain и найди `ALLOWED`, верни enforce. Добавь в профиль право
читать `/etc/hostname` и перезагрузи его `apparmor_parser -r`.

### C8. 🔑 SELinux: починить, не выключая
На `rocky01`: nginx раздаёт `/srv/www/index.html` → получи 403, найди AVC через `ausearch`,
объясни через `audit2why`, исправь `semanage fcontext` + `restorecon`. Затем переведи nginx на
порт 8081 и почини запуск через `semanage port`. Проверь, что `getenforce` всё время `Enforcing`.

### C9. 🔑 Lynis до/после + роль
Прогони `lynis audit system --quick` на чистом `sec01`, сохрани hardening index и список
`warning[]`. Собери роль `hardening` по каркасу раздела 10, прогони дважды (второй раз
`changed=0`), снова Lynis. Сравни индекс и объясни 3 оставшихся suggestion: почему не сделал.
(Полная версия — лаба 1 в [08_practice_labs.md](/softskills/08-practice-labs).)

---

### Блок D. Инциденты


**D1.** После применения роли харденинга Ansible и ты сам получаете `Permission denied (publickey)`
на `sec01`. Консоль VM есть. Что проверяешь и в каком порядке?

<details><summary>Ответ</summary>

С консоли: `sshd -T | grep -Ei 'allowgroups|passwordauth|pubkey'` — не включил ли
`AllowGroups` без себя; `id vagrant` — состоит ли в `ssh-users`; `journalctl -u ssh -n 50`
(`not allowed because none of user's groups…`); права `~/.ssh` (700) и `authorized_keys` (600);
`ufw status` — есть ли правило для твоей сети. Исправить в роли (порядок: группа → участники
→ sshd; `ufw allow` до `enable`), откатить снапшот при необходимости.

</details>

**D2.** После ночного ребута Docker-хоста все контейнеры живы, но не ходят в сеть и не
принимают трафик. Неделю назад на сервер раскатили новую роль харденинга.

<details><summary>Ответ</summary>

Роль выставила `net.ipv4.ip_forward = 0` (например, из `devsec.hardening`/CIS-набора),
а применилось при ребуте. Проверка: `sysctl net.ipv4.ip_forward`. Исправление: исключение
для Docker/k8s-узлов в переменных роли (`sysctl_overwrite` или свой словарь), `sysctl --system`,
перезапуск Docker.

</details>

**D3.** В `auditctl -s` растёт `lost`, раздел `/var` заполняется `audit.log`.

<details><summary>Ответ</summary>

Слишком широкие правила (например, аудит `open` для всех) или маленький буфер.
`auditctl -l` — найти шумное правило, `aureport --key --summary` — топ ключей; сузить,
увеличить `-b`, настроить ротацию в `/etc/audit/auditd.conf` (`max_log_file`, `num_logs`,
`max_log_file_action = ROTATE`) и вывоз логов.

</details>

**D4.** На `rocky01` после переноса сайта в `/data/site` nginx отдаёт 403, а после добавления
`proxy_pass` на бэкенд — 502. Права на файлы `755/644`, бэкенд отвечает на `curl`.

<details><summary>Ответ</summary>

403 — метка `default_t` на `/data/site`: `semanage fcontext` + `restorecon`. 502 —
nginx не может подключаться к сети (`name_connect` в AVC): `setsebool -P httpd_can_network_connect on`.
Оба случая видны через `ausearch -m AVC -ts recent | audit2why`.

</details>

**D5.** Ежедневная проверка SUID показала новый файл `/usr/local/bin/.cache-helper` с битом SUID,
пакеты в этот день не обновлялись.

<details><summary>Ответ</summary>

Считать признаком компрометации: не удалять сразу. Сохранить `ls -l`, `stat`, хеш,
`dpkg -S` (скорее всего «не из пакета»), найти в auditd, кто создал (`ausearch -f /usr/local/bin/.cache-helper -i`),
проверить остальную персистентность и запускать реагирование по [07_security_incidents_compliance.md](/security/07-security-incidents-compliance).

</details>

**D6.** В 03:30 внезапно перезагрузился primary PostgreSQL; приложение 4 минуты отдавало 5xx.

<details><summary>Ответ</summary>

`Automatic-Reboot "true"` в unattended-upgrades после обновления ядра/libc.
Проверить `/var/log/unattended-upgrades/`, `last reboot`. Исправить: для stateful — без
авторебута, `needrestart`/`reboot-required` в мониторинге, ребут вручную в окне с failover.

</details>

**D7.** Утром вся команда из офиса не может зайти по SSH ни на один сервер, из дома — всё работает.

<details><summary>Ответ</summary>

fail2ban забанил NAT-адрес офиса после чьих-то неудачных попыток. Проверка:
`sudo fail2ban-client status sshd`, разбан `fail2ban-client set sshd unbanip &lt;IP&gt;`. Исправить:
`ignoreip` для админских сетей в `jail.local`, доступ через bastion/VPN.

</details>

**D8.** В `ausearch -k root_cmds` видишь `/usr/bin/curl … | sh` с `auid=unset` от процесса
веб-приложения. Ты хочешь добавить правило аудита, но `auditctl` отвечает, что правила
неизменяемы.

<details><summary>Ответ</summary>

Процесс веб-приложения (демон, `auid` не установлен) запускает `curl | sh` с euid 0 —
признак RCE и повышения прав. Правила неизменяемы из-за `-e 2` — так и задумано; менять их не
нужно сейчас. Действовать как при компрометации хоста: изолировать, сохранить улики, не
перезагружать (ребут нужен только для смены правил) — тема 07.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как бы ты захарденил новый Linux-сервер? Порядок действий.

<details><summary>Ответ</summary>

Страховка (snapshot, консоль, вторая сессия) → обновления → учётки и sudo → SSH (ключи, без
   root, AllowGroups, fail2ban) → firewall deny by default → минимум сервисов и пакетов, SUID →
   sysctl → auditd → AppArmor/SELinux в enforce → логи с хоста → проверка Lynis/CIS → всё в Ansible-роли.

</details>

**2.** Какие настройки sshd обязательны и как проверить, что они реально применились?

<details><summary>Ответ</summary>

`PermitRootLogin no`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
   `AllowGroups`, `MaxAuthTries`; проверка — `sshd -T` (действует первое значение, drop-in `00-…`),
   вход новой сессией, `ssh-audit` снаружи.

</details>

**3.** Как правильно выдавать sudo?

<details><summary>Ответ</summary>

Через `visudo` и `/etc/sudoers.d/` (без точек в имени), точечные команды с полными путями,
   без `NOPASSWD: ALL` и редакторов/пейджеров, `use_pty`, лог; права — группам.

</details>

**4.** Как организовать установку security-обновлений на парке серверов?

<details><summary>Ответ</summary>

unattended-upgrades/dnf-automatic для security-обновлений, ребуты по типу узла (stateless —
   авто/rolling, базы — в окне), мониторинг `reboot-required`/`needrestart`, отчёт по версиям
   пакетов, SLA по severity (тема 04).

</details>

**5.** Какие параметры sysctl ты бы включил для безопасности?

<details><summary>Ответ</summary>

`kptr_restrict`, `dmesg_restrict`, `unprivileged_bpf_disabled`, `yama.ptrace_scope`,
   `fs.protected_*`, `suid_dumpable=0`, запрет redirects/source route, `rp_filter`, `log_martians`,
   `tcp_syncookies`; с оговоркой про `ip_forward` на Docker/k8s.

</details>

**6.** Что такое auditd и как найти, кто изменил файл?

<details><summary>Ответ</summary>

Подсистема аудита ядра: правила на файлы и syscalls с ключами. Правило `-w /etc/x -p wa -k key`,
   поиск `ausearch -k key -i` — в записи SYSCALL видно `auid` (кто залогинился), `uid/euid`, `exe`,
   команду. Логи — сразу с хоста.

</details>

**7.** Что такое SELinux/AppArmor? Что делать, если SELinux блокирует сервис?

<details><summary>Ответ</summary>

Mandatory access control: ограничивает процесс даже под root. Если блокирует — читать AVC
   (`ausearch -m AVC`, `audit2why`), чинить метку (`semanage fcontext` + `restorecon`), порт
   (`semanage port`) или boolean (`setsebool -P`); не выключать.

</details>

**8.** Что такое CIS Benchmark?

<details><summary>Ответ</summary>

Набор рекомендаций по безопасной настройке ОС и софта от CIS, уровни 1 и 2, с проверками;
   используется как стандарт харденинга и для аудита (CIS-CAT, OpenSCAP, USG).

</details>

**9.** Пользовался ли ты Lynis/OpenSCAP? Что показывает отчёт?

<details><summary>Ответ</summary>

Lynis: `lynis audit system`, warnings/suggestions, hardening index в `lynis-report.dat`;
   использую для «до/после» и CI-проверки образов, индекс не считаю процентом безопасности.

</details>

**10.** Как применить харденинг на 100 серверах и не допустить дрейфа?

<details><summary>Ответ</summary>

Роль Ansible в git + golden image (Packer), прогон по расписанию/в CI с `--check --diff`
    для обнаружения дрейфа, повторный прогон `changed=0`, отчёт Lynis/OpenSCAP как артефакт,
    ручные правки запрещены.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Харденю сервер по порядку и не теряю доступ (snapshot, консоль, вторая сессия)
- [ ] ⭐ Проверяю sshd через `sshd -T`, понимаю правило первого значения и drop-in `00-…`
- [ ] Выдаю sudo точечно, знаю про GTFOBins и файлы с точкой в `sudoers.d`
- [ ] Настроил unattended-upgrades и знаю политику ребутов по типу узла
- [ ] Применил sysctl-набор и объясняю каждый параметр, помню про `ip_forward`
- [ ] ⭐ Пишу auditd-правила и нахожу «кто это сделал» по `auid` через `ausearch`
- [ ] Читаю отказы AppArmor и SELinux и чиню их точечно, не выключая защиту
- [ ] Прогнал Lynis до/после и объясняю, что значит hardening index
- [ ] Роль hardening идемпотентна: второй прогон даёт `changed=0`
