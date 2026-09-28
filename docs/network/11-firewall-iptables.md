---
title: "11. Файрвол: iptables/nftables"
description: "iptables, nftables, ufw, conntrack, NAT, DOCKER-USER — конспект и задачи"
---

# 11. Файрвол — iptables, nftables, ufw, conntrack

> Роадмап → 2.5 Сети → **iptables** *(тут не столько траблшутинг, сколько настройка)*.
> **После темы ты умеешь:** прочитать чужие правила, написать свои, понять, почему
> `-j DROP` и `-j REJECT` дают разные симптомы, и не удивляться, что Docker «дырявит» файрвол.

---

## 🗺️ Схема: путь пакета через netfilter

```text:no-line-numbers
                    ┌──────────────── МОЙ ХОСТ ────────────────┐
  входящий пакет    │                                          │
        │           │                                          │
        ▼           │                                          │
   ┌─────────┐  ┌──────────┐   решение      ┌──────────┐       │
   │PREROUTING├─►│ routing  ├──── мне? ────►│  INPUT   ├──► локальный процесс
   │ (DNAT)  │  │ decision │                └──────────┘       │        │
   └─────────┘  └────┬─────┘                                   │        ▼
                     │ не мне (транзит)                        │   ┌────────┐
                     ▼                                         │   │ OUTPUT │
                ┌─────────┐                                    │   └───┬────┘
                │ FORWARD │  ⭐ Docker, NAT-шлюз, k8s            │       │
                └────┬────┘                                    │       │
                     ▼                                         │       ▼
                ┌──────────────┐                               │  ┌──────────────┐
                │ POSTROUTING  │ (SNAT/MASQUERADE)  ◄──────────┴──┤ POSTROUTING  │
                └──────┬───────┘                                  └──────┬───────┘
                       ▼                                                 ▼
                   наружу                                            наружу
```

| Таблица | Для чего | Основные цепочки |
|---------|----------|------------------|
| `filter` | ⭐ Разрешить/запретить (по умолчанию) | INPUT, FORWARD, OUTPUT |
| `nat` | Подмена адресов | PREROUTING (DNAT), POSTROUTING (SNAT/MASQUERADE) |
| `mangle` | Правка полей (TTL, TOS, MSS) | все |
| `raw` | Обход conntrack (`NOTRACK`) | PREROUTING, OUTPUT |

---

## 1. Чтение правил — первое, что делают на чужом сервере

```bash
sudo iptables -L -n -v --line-numbers        # ⭐ filter: что разрешено, счётчики пакетов
sudo iptables -t nat -L -n -v                # NAT-правила (Docker живёт тут)
sudo iptables -S                             # в виде команд — удобно копировать и диффать
sudo iptables-save > /tmp/rules.v4           # полный снимок
sudo nft list ruleset                        # ⭐ nftables (современная замена)
```

⭐ **Счётчики в `-v`** — главный инструмент отладки: если пакеты не попадают в правило,
его счётчик не растёт, и сразу видно, какое правило сработало раньше.

```text:no-line-numbers
Chain INPUT (policy DROP 12 packets, 720 bytes)
 num  pkts bytes target  prot opt in   out  source      destination
 1    1543  92K  ACCEPT  all  --  lo   *    0.0.0.0/0   0.0.0.0/0
 2   10231 1.2M  ACCEPT  all  --  *    *    0.0.0.0/0   0.0.0.0/0   ctstate RELATED,ESTABLISHED
 3      45 2700  ACCEPT  tcp  --  *    *    0.0.0.0/0   0.0.0.0/0   tcp dpt:22
```

---

## 2. Правила: синтаксис и порядок

```bash
# Добавить в конец / вставить в начало / удалить
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo iptables -D INPUT 3
sudo iptables -F INPUT                       # ⚠️ очистить цепочку
sudo iptables -P INPUT DROP                  # ⚠️ политика по умолчанию
```

| Ключ | Значение |
|------|----------|
| `-p tcp\|udp\|icmp` | Протокол |
| `--dport` / `--sport` | Порт назначения / источника |
| `-s` / `-d` | Источник / назначение (IP или сеть) |
| `-i` / `-o` | Входной / выходной интерфейс |
| `-m state --state` / `-m conntrack --ctstate` | ⭐ Состояние соединения |
| `-m multiport --dports 80,443` | Несколько портов |
| `-m limit --limit 5/min` | Ограничение частоты |
| `-j ACCEPT\|DROP\|REJECT\|LOG\|MASQUERADE\|DNAT\|SNAT` | Действие |

⭐ **Правила читаются сверху вниз, первое совпадение выигрывает.** Поэтому `-A` (в конец)
после `-j DROP` бессмысленно — до него не дойдёт.

### DROP vs REJECT — важная разница

| | DROP | REJECT |
|---|------|--------|
| Что делает | Молча выбрасывает | Отвечает ICMP/RST |
| Клиент видит | ⏳ Таймаут (секунды-минуты) | ⚡ Connection refused сразу |
| Где применять | Внешний периметр (не отвечать сканерам) | Внутри сети (быстрый отказ, понятные ошибки) |

---

## 3. Stateful-фильтрация — почему достаточно одного правила

```bash
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

Это правило разрешает **ответы** на исходящие соединения. Без него пришлось бы вручную
описывать обратный трафик для каждого сервиса. Состояния:

| Состояние | Значение |
|-----------|----------|
| `NEW` | Первый пакет нового соединения |
| `ESTABLISHED` | Пакет существующего соединения |
| `RELATED` | Связанное соединение (ICMP-ошибка, FTP-data) |
| `INVALID` | Не соответствует ни одному соединению — обычно дропают |

```bash
sudo conntrack -L | head                      # текущие соединения
sudo conntrack -S                             # статистика (в т.ч. drops)
sysctl net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_count
```

---

## 4. Типовой набор для веб-сервера

```bash
# 1. Разрешаем то, что нужно
sudo iptables -A INPUT -i lo -j ACCEPT
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
sudo iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/s -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 22 -s 192.168.56.0/24 -j ACCEPT   # ⭐ SSH только из своей сети
sudo iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT

# 2. Логируем остальное (с ограничением, чтобы не забить диск)
sudo iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "iptables-drop: "

# 3. И только потом закрываем
sudo iptables -P INPUT DROP
sudo iptables -P FORWARD DROP
sudo iptables -P OUTPUT ACCEPT
```

⚠️ **Порядок критичен.** Сначала `-P INPUT DROP`, потом правила для SSH — и ты отрезал себя
от сервера. Приёмы безопасности:

```bash
# Страховка: откат через 5 минут, если что-то пойдёт не так
echo 'iptables-restore < /tmp/rules.backup.v4' | sudo at now + 5 minutes
sudo iptables-save > /tmp/rules.backup.v4      # СНАЧАЛА бэкап!
```

**Сохранение правил** (иначе они исчезнут после перезагрузки):

```bash
sudo apt install -y iptables-persistent
sudo netfilter-persistent save                 # → /etc/iptables/rules.v4
sudo iptables-restore < /etc/iptables/rules.v4
```

---

## 5. NAT: проброс портов и выход в интернет

```bash
# DNAT: внешний 8080 → внутренний сервис 80 (то же делает docker -p)
sudo iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 10.0.0.5:80
sudo iptables -A FORWARD -p tcp -d 10.0.0.5 --dport 80 -j ACCEPT

# SNAT/MASQUERADE: приватная сеть выходит наружу через нас
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -s 192.168.56.0/24 -o eth0 -j MASQUERADE

# Локальный редирект порта (80 → 8080 без root у приложения)
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
```

`MASQUERADE` — это SNAT с автоматическим определением исходящего адреса (для динамических IP);
`SNAT --to-source` быстрее, когда адрес статический.

---

## 6. ufw и firewalld — обёртки

```bash
# ufw (Ubuntu) — простой фронтенд к iptables
sudo ufw status verbose
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow from 192.168.56.0/24 to any port 5432 proto tcp
sudo ufw limit 22/tcp                   # ⭐ защита от перебора
sudo ufw enable
sudo ufw status numbered && sudo ufw delete 3

# firewalld (RHEL/CentOS) — зоны
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload
```

⚠️ Смешивать ufw/firewalld и ручные `iptables`-правила — верный способ получить
непредсказуемый результат: обёртка перезапишет цепочки при следующей перезагрузке.

---

## 7. ⭐ Docker и iptables — источник сюрпризов

```bash
sudo iptables -t nat -L DOCKER -n
sudo iptables -L DOCKER-USER -n -v
```

Ключевые факты:

1. Docker сам добавляет правила в `nat` (DNAT для `-p`) и в `FORWARD` (цепочка `DOCKER`).
2. ⭐ Публикация порта (`-p 8080:80`) **обходит** твои правила в `INPUT`: трафик к контейнеру
   идёт через `PREROUTING`/`FORWARD`, а не через `INPUT`. Классическая ошибка:
   «я закрыл всё в INPUT, но контейнер доступен из интернета».
3. Правильное место для своих ограничений — цепочка **`DOCKER-USER`**, она обрабатывается
   до правил Docker и не перезаписывается при рестарте демона.

```bash
# Разрешить доступ к опубликованным портам только из своей сети
sudo iptables -I DOCKER-USER -i eth0 ! -s 192.168.56.0/24 -j DROP

# Или не публиковать порт наружу вовсе:
docker run -p 127.0.0.1:8080:80 nginx      # ⭐ слушает только на localhost
```

В Kubernetes ситуация аналогичная: kube-proxy в режиме iptables/IPVS создаёт сотни правил;
ручные правила стоит писать только там, где они не конфликтуют, а фильтрацию делать
через NetworkPolicy.

---

## 8. nftables — то, во что всё переехало

Современные дистрибутивы используют `nftables`, а `iptables` — это обёртка (`iptables-nft`).

```bash
sudo nft list ruleset
sudo nft add table inet myfilter
sudo nft add chain inet myfilter input '{ type filter hook input priority 0; policy drop; }'
sudo nft add rule inet myfilter input ct state established,related accept
sudo nft add rule inet myfilter input iif lo accept
sudo nft add rule inet myfilter input tcp dport { 22, 80, 443 } accept
sudo nft list ruleset > /etc/nftables.conf
```

Преимущества: один синтаксис для IPv4/IPv6, наборы (`{ }`), словари, атомарная загрузка
правил. Знать нужно оба: `iptables` — потому что он везде в документации и скриптах,
`nftables` — потому что он под капотом.

---

## 💼 Как это в DevOps

- Первое, что проверяют при «порт не отвечает снаружи»: `ss -tlnp` (слушает ли)
  и `iptables -L -n -v` (не дропается ли).
- Счётчики правил отвечают на вопрос «а срабатывает ли вообще это правило».
- Забытый `iptables-persistent` — классика: после перезагрузки все правила исчезли.
- В облаках поверх хостового файрвола есть security groups — проверять надо оба слоя.
- Docker/k8s меняют правила динамически: свои ограничения — только в `DOCKER-USER`
  или через NetworkPolicy.

---

## 🧪 Мини-лаба

```bash
vagrant ssh app        # ⚠️ работаем на app, чтобы в случае чего зайти с web
sudo iptables-save > /tmp/rules.backup.v4      # ⭐ СНАЧАЛА бэкап

# 1. Что есть сейчас
sudo iptables -L -n -v --line-numbers
sudo iptables -t nat -L -n | head

# 2. DROP vs REJECT — прочувствовать разницу
python3 -m http.server 8080 >/dev/null 2>&1 &
# с web:  time nc -zv -w5 192.168.56.11 8080   → succeeded
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP
# с web:  time nc -zv -w5 192.168.56.11 8080   → таймаут ~5 секунд
sudo iptables -D INPUT -p tcp --dport 8080 -j DROP
sudo iptables -A INPUT -p tcp --dport 8080 -j REJECT
# с web:  time nc -zv -w5 192.168.56.11 8080   → Connection refused мгновенно
sudo iptables -D INPUT -p tcp --dport 8080 -j REJECT

# 3. Счётчики как инструмент отладки
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP
# с web: nc -z -w1 192.168.56.11 8080
sudo iptables -L INPUT -n -v --line-numbers | grep 8080     # pkts вырос
sudo iptables -D INPUT -p tcp --dport 8080 -j DROP

# 4. Ограничение по источнику
sudo iptables -A INPUT -p tcp --dport 8080 -s 192.168.56.10 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP
# с web (192.168.56.10) — работает; с любого другого адреса — таймаут
sudo iptables -D INPUT -p tcp --dport 8080 -s 192.168.56.10 -j ACCEPT
sudo iptables -D INPUT -p tcp --dport 8080 -j DROP

# 5. Логирование дропов
sudo iptables -A INPUT -p tcp --dport 8080 -m limit --limit 5/min -j LOG --log-prefix "FW-DROP: "
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP
# с web: nc -z -w1 192.168.56.11 8080
sudo dmesg | grep -m3 "FW-DROP"
sudo iptables -D INPUT -p tcp --dport 8080 -m limit --limit 5/min -j LOG --log-prefix "FW-DROP: "
sudo iptables -D INPUT -p tcp --dport 8080 -j DROP

# 6. Stateful: почему нужен ESTABLISHED
sudo iptables -A OUTPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --sport 80 -j DROP      # запрещаем ОТВЕТЫ
curl -s -m5 -o /dev/null -w 'без ESTABLISHED: %{http_code}\n' http://example.com || echo "ответ не пришёл"
sudo iptables -I INPUT 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
curl -s -m5 -o /dev/null -w 'с ESTABLISHED: %{http_code}\n' http://example.com
sudo iptables -D INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -D INPUT -p tcp --sport 80 -j DROP
sudo iptables -D OUTPUT -p tcp --dport 80 -j ACCEPT

# 7. conntrack
sudo apt install -y conntrack
sudo conntrack -L 2>/dev/null | head -5
sudo conntrack -S | head -3
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# 8. Полный набор для веб-сервера (аккуратно, с откатом)
echo 'sudo iptables-restore < /tmp/rules.backup.v4' | sudo at now + 5 minutes 2>/dev/null || \
  echo "поставь at, либо просто не закрывай эту сессию"
sudo iptables -A INPUT -i lo -j ACCEPT
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
sudo iptables -A INPUT -p icmp --icmp-type echo-request -j ACCEPT
sudo iptables -P INPUT DROP
sudo iptables -L -n -v
# проверь НОВОЙ сессией с web: ssh, ping, curl
sudo iptables-restore < /tmp/rules.backup.v4     # откат

# 9. ufw
sudo ufw status verbose
# (не включай ufw одновременно с ручными правилами — смотри, как он их перепишет)

# 10. nftables
sudo nft list ruleset | head -30

# 11. Docker обходит INPUT (если есть docker)
docker run -d --name web8081 -p 8081:80 nginx:alpine >/dev/null 2>&1
sudo iptables -A INPUT -p tcp --dport 8081 -j DROP
# с web: curl -s -m3 -o /dev/null -w '%{http_code}\n' http://192.168.56.11:8081/  → 200 (!)
sudo iptables -I DOCKER-USER -p tcp --dport 80 -j DROP
# теперь недоступен
sudo iptables -D DOCKER-USER -p tcp --dport 80 -j DROP
sudo iptables -D INPUT -p tcp --dport 8081 -j DROP
docker rm -f web8081 >/dev/null 2>&1

# 12. Уборка
sudo iptables-restore < /tmp/rules.backup.v4
pkill -f http.server
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `iptables -L -n -v --line-numbers` | ⭐ Показать правила со счётчиками |
| `iptables -t nat -L -n -v` | NAT-правила |
| `iptables -S` | Правила как команды |
| `iptables -A ЦЕПЬ ... -j ДЕЙСТВИЕ` | Добавить в конец |
| `iptables -I ЦЕПЬ 1 ...` | Вставить первым |
| `iptables -D ЦЕПЬ номер` | Удалить |
| `iptables -P INPUT DROP` | ⚠️ Политика по умолчанию |
| `-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT` | ⭐ Разрешить ответы |
| `-j DROP` / `-j REJECT` | Таймаут / мгновенный отказ |
| `-m limit --limit 5/min -j LOG --log-prefix "X: "` | Логирование с ограничением |
| `-t nat -A PREROUTING ... -j DNAT --to-destination` | Проброс порта |
| `-t nat -A POSTROUTING -s NET -o eth0 -j MASQUERADE` | Выход в интернет |
| `iptables-save` / `iptables-restore` | Бэкап / восстановление |
| `netfilter-persistent save` | Сохранить навсегда |
| `iptables -I DOCKER-USER ...` | ⭐ Ограничения для контейнеров |
| `nft list ruleset` | Правила nftables |
| `conntrack -L` / `-S` | Соединения / статистика |

---

## 🧠 Что запомнить

1. Таблицы: `filter` (разрешить/запретить), `nat` (подмена адресов), `mangle`, `raw`.
2. Цепочки: INPUT (мне), OUTPUT (от меня), FORWARD (транзит — Docker, NAT-шлюз).
3. Правила читаются сверху вниз, первое совпадение выигрывает.
4. `DROP` — таймаут у клиента, `REJECT` — мгновенный refused. Симптомы разные, диагностика тоже.
5. Одно правило `ctstate ESTABLISHED,RELATED -j ACCEPT` заменяет десятки «обратных» правил.
6. Сначала разрешающие правила (особенно SSH!), только потом `-P INPUT DROP`.
7. Счётчики `-v` показывают, какое правило реально срабатывает.
8. Без `iptables-persistent`/`netfilter-persistent save` правила исчезнут после перезагрузки.
9. ⭐ Docker обходит INPUT: ограничивай через `DOCKER-USER` или публикуй порт на `127.0.0.1`.
10. В облаке есть второй слой — security groups; проверяй оба.
11. Под капотом уже nftables; `iptables` — совместимая обёртка.

---

## Задачи

> ⚠️ Перед практикой: `vagrant snapshot save before_net11` и `sudo iptables-save > /tmp/rules.backup.v4`.
> Работай на `app`, чтобы в случае блокировки зайти с `web` через vagrant-консоль.

---

### Блок A. Теория

**A1.** Назови таблицы netfilter и для чего каждая.

<details><summary>Ответ</summary>

`filter` — фильтрация (ACCEPT/DROP/REJECT); `nat` — подмена адресов (DNAT/SNAT);
`mangle` — изменение полей пакета (TTL, TOS, MSS); `raw` — работа до conntrack (NOTRACK).

</details>

**A2.** Назови цепочки таблицы filter и какой трафик через какую проходит.

<details><summary>Ответ</summary>

INPUT — пакеты, адресованные самому хосту; OUTPUT — исходящие от локальных процессов;
FORWARD — транзитные (маршрутизация между интерфейсами: NAT-шлюз, Docker, k8s).

</details>

**A3.** Нарисуй путь входящего пакета: когда он попадает в INPUT, а когда в FORWARD?

<details><summary>Ответ</summary>

PREROUTING (nat, DNAT) → решение маршрутизации: если адрес назначения локальный —
INPUT → процесс; если нет — FORWARD → POSTROUTING → наружу.

</details>

**A4.** В каком порядке применяются правила? Что будет, если добавить ACCEPT после DROP?

<details><summary>Ответ</summary>

Сверху вниз, первое совпадение определяет судьбу пакета. ACCEPT после DROP
для того же трафика недостижим — пакет уже отброшен.

</details>

**A5.** ⭐ Разница `-j DROP` и `-j REJECT`: что видит клиент, где что применять?

<details><summary>Ответ</summary>

DROP молча отбрасывает: клиент ждёт таймаут и повторяет SYN. REJECT отвечает
ICMP unreachable или TCP RST: клиент мгновенно получает `Connection refused`.
DROP — на внешнем периметре (не подсказывать сканерам), REJECT — внутри сети,
чтобы приложения быстро получали внятную ошибку.

</details>

**A6.** Что делает `-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT` и почему без него
не работает исходящий трафик при `-P INPUT DROP`?

<details><summary>Ответ</summary>

Разрешает пакеты, принадлежащие уже установленным соединениям и связанным с ними.
Без него при `-P INPUT DROP` исходящий запрос уйдёт, а ответ будет отброшен на входе —
«интернета нет», хотя OUTPUT разрешён.

</details>

**A7.** Что означают состояния NEW, ESTABLISHED, RELATED, INVALID?

<details><summary>Ответ</summary>

NEW — первый пакет соединения; ESTABLISHED — пакет существующего соединения;
RELATED — связанное соединение (ICMP-ошибка к существующему потоку, FTP-data);
INVALID — не соотносится ни с одним соединением (мусор, пакеты после таймаута) — обычно дропают.

</details>

**A8.** Чем `MASQUERADE` отличается от `SNAT`?

<details><summary>Ответ</summary>

`SNAT --to-source IP` подменяет источник фиксированным адресом (быстрее, для статики);
`MASQUERADE` определяет адрес исходящего интерфейса на лету (для динамических адресов,
чуть дороже, сбрасывает соединения при смене адреса).

</details>

**A9.** Что делает DNAT и какой командой Docker его использует?

<details><summary>Ответ</summary>

DNAT меняет адрес назначения — так реализуется проброс порта. Docker при
`-p 8080:80` создаёт правила DNAT в `nat/PREROUTING` (цепочка DOCKER) и разрешающие
правила в FORWARD.

</details>

**A10.** Как сохранить правила между перезагрузками в Debian/Ubuntu?

<details><summary>Ответ</summary>

`apt install iptables-persistent`, затем `netfilter-persistent save`
(правила в `/etc/iptables/rules.v4`), либо вручную `iptables-save > файл` +
`iptables-restore < файл` в systemd-юните. Для nftables — `/etc/nftables.conf` и
`systemctl enable nftables`.

</details>

**A11.** ⭐ Почему `-P INPUT DROP` не закрывает порты, опубликованные Docker'ом?
Где правильное место для таких ограничений?

<details><summary>Ответ</summary>

Трафик к опубликованному порту контейнера проходит PREROUTING (DNAT) и FORWARD,
а не INPUT — INPUT для него просто не применяется. Ограничения нужно добавлять в цепочку
`DOCKER-USER` (она вызывается раньше правил Docker и не перезаписывается) или публиковать
порт только на `127.0.0.1`.

</details>

**A12.** Чем ufw отличается от прямой работы с iptables? Почему их опасно смешивать?

<details><summary>Ответ</summary>

ufw — высокоуровневая обёртка, генерирующая свои цепочки. При смешивании ручные
правила попадают в другие цепочки и/или перезаписываются при `ufw reload`/перезагрузке,
поведение становится непредсказуемым. Нужно выбрать один инструмент.

</details>

**A13.** Что такое conntrack и чем грозит переполнение его таблицы?

<details><summary>Ответ</summary>

Таблица отслеживания соединений в ядре, необходимая для stateful-фильтрации и NAT.
При переполнении новые пакеты отбрасываются: массовые обрывы, «сеть тупит»,
в `dmesg` — `table full`.

</details>

**A14.** Чем nftables лучше iptables?

<details><summary>Ответ</summary>

Единый синтаксис для IPv4/IPv6/ARP/bridge, наборы и словари (быстрый поиск вместо
линейного перебора), атомарная замена правил, лучшая производительность при большом числе
правил, более читаемый синтаксис.

</details>

**A15.** Как ограничить частоту логирования и зачем это нужно?

<details><summary>Ответ</summary>

`-m limit --limit 5/min` ограничивает частоту срабатывания правила. Без него
LOG при сканировании или атаке заполнит `/var/log` и dmesg за минуты — и это отдельная авария.

</details>

---

### Блок B. «Что делает правило»

```bash
B1.  iptables -A INPUT -i lo -j ACCEPT
B2.  iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
B3.  iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT
B4.  iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
B5.  iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
B6.  iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 1/s -j ACCEPT
B7.  iptables -P INPUT DROP
B8.  iptables -t nat -A POSTROUTING -s 192.168.56.0/24 -o eth0 -j MASQUERADE
B9.  iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 10.0.0.5:80
B10. iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
B11. iptables -I DOCKER-USER -i eth0 ! -s 10.0.0.0/8 -j DROP
B12. iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
```

<details><summary>Ответ</summary>

- **B1.** Разрешает весь трафик на loopback (обязательное правило).
- **B2.** Разрешает ответы на исходящие соединения.
- **B3.** Разрешает SSH только из сети 10.0.0.0/8.
- **B4.** Вставляет разрешение 443 первым правилом.
- **B5.** Разрешает 80 и 443 одним правилом.
- **B6.** Разрешает ping не чаще одного в секунду.
- **B7.** Политика по умолчанию — отбрасывать всё, что не разрешено явно.
- **B8.** Маскарадинг для выхода приватной сети в интернет.
- **B9.** Проброс внешнего порта 8080 на 10.0.0.5:80.
- **B10.** Локальное перенаправление 80 → 8080.
- **B11.** Запрещает доступ к контейнерам с eth0 всем, кроме сети 10.0.0.0/8.
- **B12.** Отбрасывает пакеты, не принадлежащие ни одному соединению.

</details>

**B13.** Найди ошибку:
```bash
iptables -P INPUT DROP
iptables -A INPUT -p tcp --dport 22 -j ACCEPT
```

<details><summary>Ответ</summary>

Политика применена **до** разрешающего правила: в момент выполнения первой строки
текущая SSH-сессия обрывается (если нет правила ESTABLISHED), и вторая строка уже не выполнится.
Правильно: сначала все ACCEPT (включая `ESTABLISHED,RELATED` и SSH), затем `-P INPUT DROP`.

</details>

**B14.** А здесь?
```bash
iptables -A INPUT -j DROP
iptables -A INPUT -p tcp --dport 443 -j ACCEPT
```

<details><summary>Ответ</summary>

Первое правило отбрасывает вообще всё, второе недостижимо. Нужно либо `-I` для
вставки в начало, либо разместить DROP последним.

</details>

---

### Блок C. Практика

**C1. Разница DROP/REJECT.** Подними сервис на 8080, закрой его сначала `DROP`, потом `REJECT`.
Замерь `time nc -zv -w5` с соседней ВМ в обоих случаях, сними tcpdump и опиши разницу
на уровне пакетов.

<details><summary>Ответ</summary>

DROP: `nc` висит до таймаута, в tcpdump — только исходящие SYN с повторами.
REJECT: мгновенный `Connection refused`, в tcpdump — SYN и ответный RST (или ICMP
`administratively prohibited` при `--reject-with icmp-admin-prohibited`).

</details>

**C2. Отладка по счётчикам.** Создай три правила для одного порта (ACCEPT по источнику,
LOG, DROP). Сгенерируй трафик с разных адресов и по счётчикам `-v` покажи,
какое правило сработало для какого источника.

<details><summary>Ответ</summary>

После генерации трафика `iptables -L INPUT -n -v --line-numbers` покажет ненулевые
`pkts` у сработавших правил: у ACCEPT — для разрешённого источника, у LOG и DROP —
для остальных.

</details>

**C3. 🔑 Базовый набор для веб-сервера.** Настрой полный набор: lo, ESTABLISHED, SSH только
из локальной сети, 80/443 отовсюду, ICMP с лимитом, логирование остального, `-P INPUT DROP`.
Проверь **новой сессией** каждый пункт. Сохрани через `netfilter-persistent`, перезагрузи ВМ
и убедись, что правила остались.

<details><summary>Ответ</summary>

Набор — из конспекта (раздел 4). Проверка: `ssh` из локальной сети работает,
`curl http://app/` работает, `ping` работает, доступ на любой другой порт — таймаут.
Сохранение: `sudo netfilter-persistent save`, затем `sudo reboot` и повторная проверка
`iptables -L -n -v`.

</details>

**C4. Защита от себя.** Настрой автоматический откат (`at` или `sleep && iptables-restore`
в фоне), затем намеренно примени правило, которое отрезает SSH, и покажи, что через
5 минут доступ вернулся.

<details><summary>Ответ</summary>

```bash
sudo iptables-save > /tmp/rules.backup.v4
echo "iptables-restore < /tmp/rules.backup.v4" | sudo at now + 5 minutes
# или: sudo bash -c 'sleep 300 && iptables-restore < /tmp/rules.backup.v4' &
sudo iptables -I INPUT 1 -p tcp --dport 22 -j DROP    # отрезали себя
# через 5 минут доступ восстановится автоматически
```

</details>

**C5. Stateful.** Покажи на практике, что без правила ESTABLISHED исходящие запросы
не получают ответов. Затем добавь его и покажи, что всё заработало.

<details><summary>Ответ</summary>

См. шаг 6 мини-лабы: без ESTABLISHED `curl` не получает ответ (таймаут),
с ним — код 200. Это наглядно показывает, что фильтрация двунаправленная.

</details>

**C6. NAT-шлюз.** Сделай из `web` шлюз: `app` ходит в интернет через него (MASQUERADE).
Проверь `curl ifconfig.me` с `app`, найди соединение в `conntrack -L` на `web`,
покажи счётчики правила POSTROUTING.

<details><summary>Ответ</summary>

```bash
# на web
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -s 192.168.56.0/24 -o eth0 -j MASQUERADE
sudo iptables -A FORWARD -s 192.168.56.0/24 -j ACCEPT
sudo iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# на app
sudo ip route replace default via 192.168.56.10 dev eth1
curl -s ifconfig.me
# на web
sudo iptables -t nat -L POSTROUTING -n -v      # счётчик растёт
sudo conntrack -L | grep 192.168.56.11 | head -3
```

</details>

**C7. Проброс порта.** Через DNAT пробрось порт 8080 на `web` в порт 80 на `app`.
Проверь снаружи. Объясни, какие ещё правила (FORWARD, ip_forward) нужны, чтобы это работало.

<details><summary>Ответ</summary>

```bash
# на web
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 192.168.56.11:80
sudo iptables -t nat -A POSTROUTING -d 192.168.56.11 -p tcp --dport 80 -j MASQUERADE
sudo iptables -A FORWARD -p tcp -d 192.168.56.11 --dport 80 -j ACCEPT
```
Нужны: включённый `ip_forward`, правило FORWARD (иначе транзит запрещён политикой)
и обратный путь — либо MASQUERADE, либо маршрут на `app` обратно через `web`.

</details>

**C8. Docker и файрвол.** Подними контейнер с `-p 8081:80`, закрой 8081 в INPUT
и покажи, что он всё равно доступен. Затем закрой через `DOCKER-USER`. В конце покажи
альтернативу — публикацию на `127.0.0.1`.

<details><summary>Ответ</summary>

Порт 8081 останется доступен при `-A INPUT ... -j DROP`, потому что трафик идёт
через FORWARD. `sudo iptables -I DOCKER-USER -p tcp --dport 80 -j DROP` закроет его.
Альтернатива — `docker run -p 127.0.0.1:8081:80`, тогда порт вообще не публикуется наружу.

</details>

**C9. Ограничение частоты.** Настрой защиту от перебора SSH через `-m recent` или `ufw limit`.
Проверь, что после N попыток соединения начинают отбрасываться.

<details><summary>Ответ</summary>

```bash
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -m recent --set --name SSH
sudo iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -m recent \
     --update --seconds 60 --hitcount 4 --name SSH -j DROP
# или просто: sudo ufw limit 22/tcp
```

</details>

**C10. nftables.** Собери эквивалент набора из C3 на nftables: таблица, цепочка с политикой
drop, правила для lo, ct state, портов. Сохрани в `/etc/nftables.conf`.

<details><summary>Ответ</summary>

```bash
sudo nft add table inet fw
sudo nft add chain inet fw input '{ type filter hook input priority 0; policy drop; }'
sudo nft add rule inet fw input iif lo accept
sudo nft add rule inet fw input ct state established,related accept
sudo nft add rule inet fw input ct state invalid drop
sudo nft add rule inet fw input tcp dport { 22, 80, 443 } accept
sudo nft add rule inet fw input icmp type echo-request limit rate 5/second accept
sudo nft list ruleset | sudo tee /etc/nftables.conf >/dev/null
```

</details>

**C11. Инвентаризация.** Напиши скрипт, который выводит: политики цепочек, число правил,
открытые порты (из `ss -tlnp`), и сопоставляет их — «порт слушается, но закрыт файрволом»
и «порт открыт в файрволе, но никто не слушает».

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail
echo "=== политики ==="; sudo iptables -L -n | grep policy
echo "=== число правил ==="; sudo iptables -S | grep -c '^-A'
echo "=== слушающие порты vs файрвол ==="
while read -r port; do
  if sudo iptables -S INPUT | grep -q -- "--dport $port .*ACCEPT"; then
    printf 'порт %-6s слушается и разрешён\n' "$port"
  else
    printf 'порт %-6s слушается, но НЕ разрешён явно\n' "$port"
  fi
done < <(ss -tlnH | awk '{print $4}' | sed 's/.*://' | sort -un)
```

</details>

---

### Блок D. Инциденты

**D1.** После перезагрузки сервера все правила файрвола исчезли. Причина и решение.

<details><summary>Ответ</summary>

Правила `iptables` живут только в памяти. Решение: `iptables-persistent` +
`netfilter-persistent save`, либо `/etc/nftables.conf` с включённым сервисом,
либо управление файрволом через Ansible/ufw с сохранением конфигурации.

</details>

**D2.** Ты применил `-P INPUT DROP` и потерял SSH-сессию. Что делать сейчас и как было правильно?

<details><summary>Ответ</summary>

Сейчас: зайти через консоль гипервизора/облака (vagrant ssh, VNC, serial) и
восстановить `iptables-restore < бэкап` или `iptables -P INPUT ACCEPT`.
Правильно было: бэкап, отложенный откат через `at`, сначала ACCEPT-правила
(включая ESTABLISHED и SSH), потом политика, проверка новой сессией.

</details>

**D3.** Сервис в контейнере доступен из интернета, хотя в INPUT всё закрыто. Объясни механизм
и предложи два решения.

<details><summary>Ответ</summary>

Трафик к опубликованному порту обрабатывается в PREROUTING/FORWARD, минуя INPUT.
Решения: правило в `DOCKER-USER` или публикация на `127.0.0.1` (и внешний доступ —
только через reverse proxy).

</details>

**D4.** Клиенты жалуются на долгие таймауты при подключении к закрытому сервису вместо
быстрой ошибки. Что поменять и какие есть аргументы против?

<details><summary>Ответ</summary>

Заменить `DROP` на `REJECT` для внутренних сетей: клиент получит быструю ошибку.
Аргумент против для внешнего периметра: REJECT подтверждает существование хоста
и упрощает сканирование, а также создаёт исходящий трафик (усиление при спуфинге).

</details>

**D5.** На NAT-шлюзе в `dmesg` — `nf_conntrack: table full, dropping packet`,
пользователи теряют соединения. Что делать сейчас и что — потом?

<details><summary>Ответ</summary>

Сейчас: увеличить `nf_conntrack_max` и `hashsize`, уменьшить таймауты
(`nf_conntrack_tcp_timeout_established`). Потом: убрать лишний трафик из conntrack
(`raw` + `NOTRACK` для заведомо stateless-потоков), разгрузить шлюз, перейти на прямую
маршрутизацию без NAT, добавить мониторинг `nf_conntrack_count/max`.

</details>

**D6.** Правило `-A INPUT -p tcp --dport 443 -j ACCEPT` добавлено, но порт снаружи закрыт.
Счётчик правила — 0. Что это означает и куда смотреть?

<details><summary>Ответ</summary>

Счётчик 0 означает, что пакеты до правила не доходят: раньше сработало другое правило
(DROP выше по списку), либо трафик идёт по другой цепочке (FORWARD вместо INPUT), либо
не доходит до хоста вовсе (внешний файрвол/security group). Проверять порядок правил
и `tcpdump` на входе.

</details>

**D7.** В облаке порт открыт в iptables, но снаружи недоступен. Что забыли?

<details><summary>Ответ</summary>

Security group / network ACL облака — второй, внешний слой фильтрации.
Его нужно открыть отдельно; хостовой файрвол про него ничего не знает.

</details>

**D8.** После включения `ufw` перестал работать Docker-контейнер с публикацией порта.
Что произошло?

<details><summary>Ответ</summary>

ufw по умолчанию задаёт `DEFAULT_FORWARD_POLICY="DROP"` и переписывает цепочки,
из-за чего ломается маршрутизация трафика к контейнерам. Решения: разрешить forward в ufw
(`/etc/default/ufw`), настраивать ограничения через `DOCKER-USER`, либо не использовать
ufw на docker-хостах.

</details>

**D9.** Разработчики просят «отключить файрвол, чтобы проверить». Что предложить вместо этого?

<details><summary>Ответ</summary>

Предложить точечную проверку: временно разрешить конкретный порт для конкретного
источника с ограничением по времени, снять `tcpdump` для доказательства, использовать
`iptables -I` с последующим удалением и отложенный откат. Отключение файрвола целиком
на сервере с публичным адресом — неприемлемо.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как устроен iptables: таблицы, цепочки, правила?

<details><summary>Ответ</summary>

Таблицы (filter/nat/mangle/raw) содержат цепочки (INPUT/OUTPUT/FORWARD/PRE-/POSTROUTING),
цепочки — правила, применяемые сверху вниз до первого совпадения.

</details>

**2.** В чём разница между DROP и REJECT?

<details><summary>Ответ</summary>

DROP молчит (клиент ждёт таймаут), REJECT отвечает RST/ICMP (мгновенный refused).

</details>

**3.** Что делает правило с ESTABLISHED,RELATED и зачем оно?

<details><summary>Ответ</summary>

Разрешает пакеты уже установленных и связанных соединений — без него не работают ответы
на исходящие запросы при закрытой политике.

</details>

**4.** Как пробросить порт средствами iptables?

<details><summary>Ответ</summary>

`iptables -t nat -A PREROUTING -p tcp --dport X -j DNAT --to-destination IP:PORT`
плюс разрешение в FORWARD и включённый `ip_forward`.

</details>

**5.** Что такое MASQUERADE?

<details><summary>Ответ</summary>

SNAT с автоматическим выбором адреса исходящего интерфейса — «выход в интернет»
для приватной сети.

</details>

**6.** Как сохранить правила после перезагрузки?

<details><summary>Ответ</summary>

`iptables-persistent` / `netfilter-persistent save` (или `/etc/nftables.conf`).

</details>

**7.** Почему Docker обходит правила INPUT?

<details><summary>Ответ</summary>

Потому что его трафик проходит PREROUTING и FORWARD, а не INPUT; ограничивать нужно
в `DOCKER-USER`.

</details>

**8.** Чем nftables отличается от iptables?

<details><summary>Ответ</summary>

Единый синтаксис, наборы, атомарные обновления, лучшая производительность;
iptables сейчас — обёртка над nftables.

</details>

**9.** Как проверить, какое правило срабатывает?

<details><summary>Ответ</summary>

По счётчикам пакетов в `iptables -L -n -v --line-numbers`.

</details>

---

### 🎯 Чек-лист

- [ ] Читаю чужие правила и понимаю порядок их применения
- [ ] Знаю разницу DROP/REJECT и её симптомы
- [ ] Пишу базовый набор для веб-сервера, не отрезая себе SSH
- [ ] Всегда делаю бэкап и отложенный откат перед изменением политики
- [ ] Понимаю stateful-фильтрацию и ESTABLISHED,RELATED
- [ ] Настроил NAT-шлюз и проброс порта
- [ ] Знаю про DOCKER-USER и почему INPUT не работает для контейнеров
- [ ] Сохранил правила так, что они переживают перезагрузку
- [ ] Собрал эквивалентный набор на nftables
