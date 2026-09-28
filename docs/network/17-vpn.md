---
title: "17. VPN"
description: "IPsec, WireGuard, mesh-сети: виды VPN, IKEv2/ESP, site-to-site на strongSwan и WireGuard, MTU/MSS, split DNS — конспект и задачи"
---

# 17. VPN: IPsec, WireGuard, mesh-сети

> Вне роадмапа 2.5 — но VPN встречается в каждой второй вакансии: «связать офис с облаком»,
> «доступ разработчиков в приватную сеть», «туннель между двумя ДЦ».
> **После темы ты умеешь:** объяснить виды VPN и устройство IPsec (IKEv2, SA, ESP, NAT-T),
> поднять site-to-site на strongSwan и WireGuard, настроить маршрутизацию и NAT через туннель,
> отличить split tunnel от full tunnel и за 5 минут найти, почему «туннель есть, а трафика нет».
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Схема: два главных вида VPN

```text:no-line-numbers
REMOTE ACCESS (человек → сеть)                 SITE-TO-SITE (сеть ↔ сеть)

 ноутбук 10.99.0.3                          офис A 10.10.0.0/24          офис B / VPC 10.20.0.0/16
 ┌──────────┐  UDP через интернет,          ┌──────────┐                        ┌──────────┐
 │ wg-клиент│═══ NAT, Wi-Fi ═════╗          │ шлюз A   │════ туннель ══════════ │ шлюз B   │
 └──────────┘              ┌─────╨────┐     │ (web)    │  (IPsec или WireGuard) │ (app)    │
                           │ VPN-шлюз │     └────┬─────┘                        └────┬─────┘
                           └────┬─────┘          ▼  хосты НЕ знают про VPN:          ▼
                         приватная сеть      10.10.0.x  шлюз для них — роутер    10.20.1.10
```

⭐ Remote access — клиент на каждом устройстве, у человека свой ключ и адрес.
Site-to-site — клиентов нет: шлюзы связывают сети, а хосты просто маршрутизируют через шлюз.

---

## 1. Что такое VPN и как их классифицируют

**VPN** — упаковка (инкапсуляция) исходных пакетов во внешние пакеты с шифрованием,
чтобы две сети или хост и сеть общались так, будто между ними приватный провод.

```text:no-line-numbers
Исходный пакет:          [ IP 10.10.0.5 → 10.20.1.10 | TCP | данные ]
После WireGuard:  [ IP 203.0.113.1 → 198.51.100.2 | UDP 51820 | WG | ▓▓▓ зашифровано ▓▓▓ | tag ]
После IPsec ESP:  [ IP 203.0.113.1 → 198.51.100.2 | (UDP 4500) | ESP SPI,seq | ▓▓▓ зашифровано ▓▓▓ | ICV ]
                    └──── внешний заголовок видит провайдер ────┘       └─ внутренний IP скрыт ─┘
```

| Ось | Варианты | Что выбирать |
|-----|----------|--------------|
| **Кто соединяется** | Remote access (устройство → сеть) · Site-to-site (сеть ↔ сеть) · Mesh (все со всеми) | Люди — remote access / mesh; ДЦ, офис, облако — site-to-site |
| **Уровень** | L3 (TUN, IP-пакеты) · L2 (TAP, Ethernet-кадры, broadcast, ARP) | ⭐ Почти всегда L3. L2 — только когда нужен общий broadcast-домен (legacy, VXLAN в ДЦ) |
| **Что идёт в туннель** | Full tunnel (весь трафик, `0.0.0.0/0`) · Split tunnel (только нужные сети) | Split — по умолчанию; full — когда нужен контроль всего трафика (публичный Wi-Fi, compliance) |

| Технология | Уровень / транспорт | Где работает | Сильная сторона | Слабая сторона |
|-----------|---------------------|--------------|-----------------|----------------|
| **IPsec (IKEv2)** | L3, ESP (IP proto 50) или UDP 4500 | Ядро (XFRM) + демон IKE | ⭐ Стандарт: любой роутер, облако, фаервол | Сложные конфиги и несовпадение предложений |
| **WireGuard** | L3, только UDP | Ядро Linux с 5.6 | Простота, скорость, ~4 тыс. строк кода | Нет встроенной раздачи адресов/SSO; UDP может быть закрыт |
| **OpenVPN** | L3 или L2, UDP/TCP, TLS | Userspace (+ DCO в ядре) | Проходит почти везде (TCP 443) | Медленнее, конфиг и PKI громоздкие |

---

## 2. IPsec: понятия, которые спрашивают

```text:no-line-numbers
     Шлюз A (инициатор)                                         Шлюз B (ответчик)
 ① IKE_SA_INIT   ─────── UDP 500: предложения шифров, DH, nonce ───────►
                 ◄────── выбранное предложение, DH, NAT_DETECTION (есть NAT → дальше UDP 4500)
 ② IKE_AUTH      ─────── UDP 4500: ID, PSK/сертификат, селекторы трафика ──►
                 ◄────── подтверждение + первая CHILD_SA ────────────────
                 ═══════ ESP (proto 50) или ESP-в-UDP 4500: данные ═════════
 ③ CREATE_CHILD_SA — rekey и новые SA;  INFORMATIONAL — DPD («ты жив?»), удаление SA
```

| Понятие | Что это |
|---------|---------|
| **IKE (IKEv2) / IKE SA** | Протокол управления: шифры, аутентификация, ключи; IKE SA — «управляющий канал» (rekey, DPD, удаления). ⭐ IKEv1 устарел — в strongSwan 6.1 выключен по умолчанию |
| **Child SA (IPsec SA)** | Пара **однонаправленных** ESP-SA для данных, каждая со своим **SPI**; привязана к селекторам трафика |
| **Traffic selectors** (`local_ts`/`remote_ts`) | Какие подсети с какими шифруются. Не совпали — `TS_UNACCEPTABLE` |
| **ESP** | Шифрование + целостность, IP-протокол **50** (не TCP/UDP — порта нет!). AH (proto 51) — только целостность и **несовместим с NAT**: не используют |
| **Tunnel mode** | Шифруется весь исходный IP-пакет, добавляется новый внешний IP — ⭐ site-to-site |
| **Transport mode** | Шифруется только полезная нагрузка, IP-заголовок исходный — host-to-host (часто вместе с GRE/L2TP) |
| **NAT-T** | ESP не имеет портов, и NAT не может его «разрулить». Если в IKE_SA_INIT обнаружен NAT — ESP заворачивается в **UDP 4500** (RFC 3948) |
| **DPD / PFS** | DPD — пустые INFORMATIONAL «ты жив?», нет ответа — SA сносится; PFS — новый DH при каждом rekey |

**Порты для файрвола:** UDP 500, UDP 4500 и протокол ESP (`-p esp`). ⚠️ «Открыли 500 и 4500, туннель
поднялся, а данные не идут» — классика: забыли ESP, а NAT на пути нет, поэтому NAT-T не включился.

**Policy-based vs route-based.** strongSwan по умолчанию ставит **XFRM-политики** (`ip xfrm policy`):
пакет шифруется, если попал под селектор, — в `ip route` туннеля не видно (маршруты — в таблице 220).
Route-based — XFRM-интерфейс (`if_id_in/out`) или VTI: в туннель ведёт маршрут, как у WireGuard;
облачные VPN с BGP (AWS) рассчитаны на него.

---

## 3. strongSwan: минимальный site-to-site на swanctl

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Последний релиз | **strongSwan 6.1.0** (07.09.2026): IKEv1 выключен по умолчанию, 11 исправленных уязвимостей |
| В LTS-репозиториях | Ubuntu 22.04 — 5.9.5, Ubuntu 24.04 — 5.9.13 (для наших лаб хватает) |
| Как конфигурировать | ⭐ `swanctl.conf` + команда `swanctl` (интерфейс vici). Старые `ipsec.conf`/`ipsec.secrets` + `ipsec` (stroke) — deprecated, в 6.x плагин stroke выключен по умолчанию |

Пример на стенде: «офис A» 10.10.0.0/24 за `web`, «офис B» 10.20.0.0/16 за `app` (dummy-интерфейсы
из мини-лабы). Пакеты: `sudo apt install -y charon-systemd strongswan-swanctl` (метапакет `strongswan`
тянет legacy `strongswan-starter` — не нужен); PSK — `openssl rand -base64 32`.

```text:no-line-numbers
# web: /etc/swanctl/conf.d/s2s.conf          (на app — зеркально: адреса, id и ts местами)
connections {
  s2s {
    local_addrs  = 192.168.56.10
    remote_addrs = 192.168.56.11
    proposals    = aes256gcm16-prfsha384-ecp384      # IKE SA: шифр-PRF-группа DH
    dpd_delay    = 30s
    local {
      auth = psk
      id   = web.lab                   # одна пара «ключ = значение» на строку
    }
    remote {
      auth = psk
      id   = app.lab
    }
    children {
      lan {
        local_ts      = 10.10.0.0/24
        remote_ts     = 10.20.0.0/16
        esp_proposals = aes256gcm16-ecp384           # Child SA; группа DH = PFS при rekey
        start_action  = trap          # поднять туннель при первом пакете под селектор
        dpd_action    = restart
      }
    }
  }
}
secrets {
  ike-s2s {
    id-web = web.lab
    id-app = app.lab
    secret = 0sВАШ_BASE64_PSK
  }
}
```

```bash
sudo systemctl restart strongswan              # сервис из charon-systemd, сам делает swanctl --load-all
sudo swanctl --load-all                        # перечитать конфиг после правок
sudo swanctl --list-conns                      # что загружено
ping -c3 -I 10.10.0.1 10.20.0.1                # первый пакет «ловит» trap → IKE → туннель
sudo swanctl --list-sas                        # ⭐ IKE SA ESTABLISHED + Child SA INSTALLED, байты
sudo ip xfrm state; sudo ip xfrm policy        # SA и политики глазами ядра
sudo tcpdump -ni eth1 'udp port 500 or udp port 4500 or esp'
journalctl -u strongswan -f                    # причины отказа — ниже
```

Ошибки в логе: `NO_PROPOSAL_CHOSEN` — не совпали шифры/DH; `AUTHENTICATION_FAILED` — не тот PSK
или `id`; `TS_UNACCEPTABLE` — селекторы; только ретрансмиты IKE_SA_INIT — UDP 500 не доходит.

⚠️ Не запускай этот пример одновременно с WireGuard-лабой на тех же подсетях:
XFRM-политика перехватит 10.20.0.0/16 раньше, чем маршрут в `wg0`.

---

## 4. WireGuard глубже

### 4.1 Модель: интерфейс, ключи, пиры

- `wg0` — обычный сетевой интерфейс L3. Всё, что маршрутизировано в него, шифруется.
- У каждой стороны пара ключей Curve25519. Пир = **публичный ключ** + `AllowedIPs`
  (+ необязательный `Endpoint`). Нет пользователей, паролей, сертификатов.
- Handshake (Noise IK) — 1-RTT, повторяется каждые ~2 минуты **только при наличии трафика**.
  Нет трафика — WireGuard молчит: «туннель поднят» не означает «туннель работает».
- `PresharedKey` (`wg genpsk`) — доп. симметричный слой (защита от будущих квантовых атак).
- Только UDP: где UDP закрыт (гостевой Wi-Fi, прокси), WireGuard не пройдёт — mesh обходит это relay по HTTPS (§7).

### 4.2 ⭐ AllowedIPs = маршрутизация + ACL (cryptokey routing)

```text:no-line-numbers
ИСХОДЯЩИЙ пакет dst=10.20.1.10                ВХОДЯЩИЙ пакет от пира app
  │ 1. ядро: маршрут 10.20.0.0/16 dev wg0        │ 1. расшифровали ключом пира app
  │ 2. wg: у какого пира dst ∈ AllowedIPs?       │ 2. src внутреннего пакета ∈ AllowedIPs(app)?
  │    → app (10.99.0.2/32, 10.20.0.0/16)        │    да  → пакет отдаём в стек
  │ 3. шифруем, шлём на Endpoint app             │    нет → DROP («unallowed src IP»)
  ▼                                              ▼
```

| `AllowedIPs` у пира | Смысл |
|---------------------|-------|
| `10.99.0.2/32` | Только сам пир (host-to-host, remote-access клиент на сервере) |
| `10.99.0.2/32, 10.20.0.0/16` | Пир + сеть **за** ним (site-to-site) |
| `10.99.0.0/24` | Весь VPN-диапазон через этого пира (клиент в hub-and-spoke) |
| `0.0.0.0/0, ::/0` | Всё через пира — full tunnel |

- Префиксы у пиров одного интерфейса **не должны пересекаться**: побеждает самый
  специфичный; одинаковый префикс «переезжает» к последнему пиру, которому его назначили.
- `wg` сам маршрутов не создаёт — это делает `wg-quick` (для каждого AllowedIPs).
  `Table = off` в `[Interface]` — не трогать маршруты (когда их раздаёт BGP/Ansible).

### 4.3 Endpoint, роуминг и PersistentKeepalive

- `Endpoint` нужен хотя бы одной стороне; сервер узнаёт адрес клиента из последнего **аутентифицированного** пакета (роуминг Wi-Fi → LTE без переподключения).
- Клиент за NAT: запись в таблице NAT живёт 30-120 с без трафика. После этого сервер
  не сможет достучаться до клиента первым. `PersistentKeepalive = 25` — пустой пакет раз в
  25 с держит запись живой. Ставят **на стороне за NAT**; серверу в публичной сети — не нужно.

### 4.4 MTU 1420 — откуда число

```text:no-line-numbers
Overhead WireGuard:  внешний IPv4 20 + UDP 8 + WG 32 (тип 4 + индекс 4 + счётчик 8 + tag 16) = 60 байт
                     внешний IPv6 40 + UDP 8 + WG 32                                        = 80 байт
wg-quick ставит MTU = MTU интерфейса к Endpoint − 80  →  1500 − 80 = 1420  (запас на IPv6-underlay)
```

Underlay меньше 1500 (PPPoE 1492, облако 1450/1460, туннель в туннеле) — уменьши MTU `wg0`, иначе внешние
пакеты фрагментируются или теряются. PMTUD и blackhole — §5 и [03. IP/ICMP](/network/03-l3-ip-icmp) §5.

### 4.5 Site-to-site: форвардинг, маршруты, NAT

Шлюз пересылает пакеты между `wg0` и LAN — значит:

1. `net.ipv4.ip_forward=1` на **обоих** шлюзах (иначе пакет умирает на шлюзе).
2. `AllowedIPs` пира включает **сеть за ним**, а не только его /32.
3. **Обратный маршрут**: хосты LAN должны слать ответы для `10.99.0.0/24` и удалённой сети на шлюз.
   Шлюз — их default gateway? Ничего не надо. Нет — маршрут на роутере LAN (правильно)
   или `MASQUERADE` на шлюзе (быстро, но хосты видят адрес шлюза, а не клиента).
4. Файрвол `FORWARD` пропускает трафик `wg0 ↔ LAN` (⚠️ Docker ставит политику `FORWARD DROP` —
   [11. Файрвол/iptables](/network/11-firewall-iptables) §7).

```ini
PostUp   = sysctl -w net.ipv4.ip_forward=1        # [Interface] шлюза: включается вместе с туннелем
PostUp   = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT
# PostUp = iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o eth1 -j MASQUERADE   ← если нет обратного маршрута
```

### 4.6 Что делает wg-quick (и почему full tunnel не ломает сам себя)

`wg-quick up wg0` печатает каждую команду — читай вывод: создать интерфейс, `wg setconf`,
назначить адрес, MTU, маршруты для AllowedIPs, `DNS=` через `resolvconf`, `PostUp`.

Для `AllowedIPs = 0.0.0.0/0` нельзя просто заменить default route: пакеты к самому `Endpoint`
тоже ушли бы в туннель (петля). Поэтому wg-quick использует policy routing:

```text:no-line-numbers
wg set wg0 fwmark 51820                        # пакеты самого WireGuard помечены
ip route add 0.0.0.0/0 dev wg0 table 51820     # отдельная таблица с default через туннель
ip rule add not fwmark 51820 table 51820       # всё НЕпомеченное → в туннель
ip rule add table main suppress_prefixlength 0 # но конкретные маршруты main (LAN, mgmt) важнее default
```

Горячие изменения: `wg set wg0 peer <pub> allowed-ips …` (только в памяти) или применить файл
без разрыва — `sudo bash -c 'wg syncconf wg0 <(wg-quick strip wg0)'` (конфиг читается от root).

### 4.7 Отладка WireGuard

```bash
sudo wg show                        # ⭐ latest handshake, transfer, endpoint у каждого пира
sudo wg show wg0 latest-handshakes  # unix-время; 0 = handshake не было ни разу
sudo wg show wg0 dump               # машиночитаемо — для мониторинга
sudo wg showconf wg0                # текущий конфиг из ядра (после wg set)
# сообщения модуля в dmesg: Invalid handshake initiation, Packet has unallowed src IP…
echo 'module wireguard +p' | sudo tee /sys/kernel/debug/dynamic_debug/control
```

| Что видно в `wg show` | Диагноз |
|-----------------------|---------|
| Нет строки `latest handshake`, `transfer: 0 B received` | Ключи перепутаны, Endpoint неверный, UDP-порт закрыт |
| Handshake свежий, `received` растёт, но ping не ходит | Маршруты/AllowedIPs другой стороны, форвардинг, файрвол |
| Handshake старше 3 минут при активном трафике | Сломался путь (NAT-запись истекла — нужен keepalive, сменился IP) |

---

## 5. MTU и MSS в туннелях

**Симптом:** SSH через VPN работает, `ping` ходит, мелкие HTTP-запросы проходят,
а `scp`, `git clone`, большие страницы и TLS с длинной цепочкой — зависают.

**Почему:** хост в LAN шлёт 1500-байтные пакеты с DF, а в `wg0` лезет 1420. Шлюз отвечает ICMP «Fragmentation
Needed», но ICMP где-то режется — PMTUD blackhole ([03 §5](/network/03-l3-ip-icmp)). Хосты, которые сами в VPN, не страдают:
они видят MTU `wg0` и сразу режут сегменты. Страдают те, **чей трафик форвардится** через шлюз.

```bash
ping -M do -s 1392 -c1 10.20.1.10       # 1392 + 28 (IP+ICMP) = 1420 → проходит
ping -M do -s 1393 -c1 10.20.1.10       # «message too long, mtu=1420» или тишина
tracepath -n 10.20.1.10                 # покажет pmtu на пути

# ⭐ Лечение для TCP: MSS clamping на шлюзе — переписать MSS в SYN под MTU маршрута
sudo iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

MSS clamping лечит только TCP; для UDP (большие DNS-ответы, QUIC) — правильный MTU и не блокировать
ICMP type 3 code 4. AWS в конфиге для CGW сам советует MSS 1379.

---

## 6. DNS через VPN: split DNS

Имена `*.corp.lab` резолвит DNS **внутри** VPN, остальное — обычный резолвер. Весь DNS в туннель при split
tunnel — лишняя задержка и утечка «чужих» запросов в корпоративный DNS.

```bash
# systemd-resolved (Ubuntu): DNS и домены — на интерфейс, а не глобально
sudo resolvectl dns wg0 10.20.0.53
sudo resolvectl domain wg0 '~corp.lab'      # ⭐ «~» — только маршрутизация запросов, не search
sudo resolvectl default-route wg0 false     # остальные имена — не через wg0
resolvectl status wg0
resolvectl query app.corp.lab               # покажет, через какой link ушёл запрос
```

В `wg0.conf` те же команды кладут в `PostUp` (`resolvectl dns %i …; resolvectl domain %i ~corp.lab`).
⚠️ Директива `DNS =` вызывает `resolvconf`, которого на Ubuntu нет (`resolvconf: command not found`;
костыль — `ln -s /usr/bin/resolvectl /usr/local/bin/resolvconf`), и без домена шлёт в туннель
**все** запросы — это уже не split DNS.

---

## 7. Mesh VPN: Tailscale, Headscale, NetBird

Классический VPN — звезда через шлюз. Mesh — узлы напрямую друг с другом, а координатор только
раздаёт ключи, адреса и ACL (control plane). Data plane — всё тот же WireGuard.

```text:no-line-numbers
        координатор (control plane): ключи, ACL, SSO, DNS
            ▲          ▲           ▲
   ноутбук ◄╪═════════►╪ сервер-1 ◄╪═════════► сервер-2      ═══ прямой WireGuard (пробитый NAT)
            └─── если напрямую нельзя: ретранслятор (DERP / TURN / relay) ───┘
```

| | Tailscale | Headscale | NetBird |
|---|-----------|-----------|---------|
| Что это | SaaS-координатор + клиенты | Open-source замена **координатора** Tailscale | Полностью open-source платформа (management, signal, relay) |
| Версия (проверь, сентябрь 2026) | клиент 1.102.x | 0.29.x | 0.79.x |
| Self-hosted | Только клиенты (координатор — их) | ✅ сервер свой, клиенты официальные Tailscale | ✅ весь стек, или их облако |
| Обход NAT | STUN + DERP-ретрансляторы по HTTPS | Свой или публичные DERP | STUN + TURN/relay |
| Фишки | MagicDNS, ACL, subnet router, exit node, SSH | Совместимость с клиентами, один tailnet | SSO/IdP, группы, posture checks, веб-UI |

- **Subnet router** — узел mesh, который анонсирует сеть за собой (тот же site-to-site),
  **exit node** — full tunnel через выбранный узел.
- Когда брать: команда распределённая, NAT везде, нужен SSO и ACL «человек → сервис».
  Когда нет: канал «облако ↔ ДЦ» с BGP — это IPsec/облачный VPN.

---

## 8. OpenVPN — кратко

- TLS-канал управления + свой протокол данных, userspace, TUN (L3) или TAP (L2); PKI на `easy-rsa`, клиентам — `.ovpn`.
- ⭐ Умеет **TCP 443** — проходит через самые строгие сети (ценой TCP-over-TCP и задержек).
- DCO (Data Channel Offload) — модуль ядра `ovpn`: шифрование данных в ядре, скорость ближе к WireGuard.
- Версии (проверь, сентябрь 2026): **2.7.x** — стабильная (2.7.0 — февраль 2026: multi-socket, ovpn-DCO);
  2.6 — «old stable» (2.6.23 от 23.09.2026); в Ubuntu 24.04 — 2.6.x.
- Где встретишь: legacy, pfSense/OPNsense, AWS Client VPN (OpenVPN-совместимый). Новое строят на WireGuard.

---

## 9. Облачный VPN: AWS, Yandex, облака РК

```text:no-line-numbers
 Свой ДЦ: Customer Gateway ══ туннель 1 (IPsec + BGP, inside 169.254.x.x/30) ══► AWS: Virtual Private Gateway (1 VPC)
 (strongSwan, роутер, FW)  ══ туннель 2 (IPsec + BGP, другой адрес AWS)    ══►      или Transit Gateway (хаб VPC)
```

- **AWS Site-to-Site VPN**: объект `Customer Gateway` (твой внешний IP и ASN) +
  `Virtual Private Gateway` (одна VPC) или `Transit Gateway` (много VPC и площадок).
  ⭐ Каждое подключение = **два туннеля** на разные адреса AWS; в каждом — IKE SA, IPsec SA и
  (при динамической маршрутизации) BGP. Inside-адреса — /30 из 169.254.0.0/16, рекомендован IKEv2.
- **Yandex Cloud**: типовой путь — ВМ-шлюз: «IPSec-инстанс» из Marketplace (готовая ВМ
  со strongSwan) или своя ВМ, плюс статический маршрут в таблице маршрутизации VPC на эту ВМ
  (появился ли управляемый VPN-шлюз — проверь, сентябрь 2026). Выделенный канал — Cloud Interconnect.
- **Облака РК**: как правило, VPN на ВМ (strongSwan/WireGuard) или по договору с провайдером.
- ⭐ Главное правило всех облаков: **CIDR площадок не должны пересекаться** — иначе
  маршрутизация невозможна.
- У ВМ-шлюза в облаке выключают проверку source/destination (AWS: `SourceDestCheck=false`),
  иначе облако дропнет «чужие» пакеты.

---

## 10. Чек-лист «туннель есть, а трафика нет»

```text:no-line-numbers
 1. Туннель установлен?   wg show / swanctl --list-sas     нет handshake → ключи, Endpoint, UDP 51820/500/4500, ESP
 2. Пакет идёт в туннель? ip route get <dst>; tcpdump -ni wg0     нет → AllowedIPs, Table, селекторы трафика
 3. Другая сторона видит? tcpdump -ni wg0 там; dmesg       нет → её AllowedIPs (unallowed src IP)
 4. Шлюз форвардит?       sysctl net.ipv4.ip_forward       0 → пакет умирает на шлюзе
 5. Файрвол пропускает?   iptables -S FORWARD; nft list ruleset   Docker, ufw, security group, SourceDestCheck
 6. Обратный путь есть?   ip route get 10.99.0.x на хосте LAN     нет → маршрут на роутере или MASQUERADE
 7. MTU?                  ping -M do -s 1392                мелкое ходит, крупное висит → MTU/MSS clamping
 8. DNS?                  resolvectl status; dig @10.20.0.53     ходит по IP, не ходит по имени → split DNS
```

⭐ Снизу вверх и **tcpdump на обоих концах** — сразу видно, где теряется пакет ([10. tcpdump/Wireshark](/network/10-tcpdump-wireshark)).

---

## 11. Грабли

| Грабля | Симптом | Лечение |
|--------|---------|---------|
| AllowedIPs без сети за пиром | Трафик в сеть не маршрутизируется или дропается на входе | Добавить подсеть в `AllowedIPs` у пира **на обеих** сторонах |
| Docker на VPN-шлюзе | После установки Docker site-to-site перестал форвардить | `FORWARD DROP` от Docker — правила в `DOCKER-USER`/`FORWARD` |
| Пересекающиеся CIDR | Часть адресов недоступна, маршруты «перетягивают» | Планировать адресацию на все площадки заранее |
| Нет `PersistentKeepalive` за NAT | Сервер не может достучаться до клиента после паузы | `PersistentKeepalive = 25` на стороне за NAT |
| Приватный ключ в git/Ansible без vault | Компрометация всего туннеля | Ключи генерировать на узле, в репо — только публичные |
| IPsec: открыли 500/4500, забыли ESP | IKE ESTABLISHED, данные не идут | `-p esp -j ACCEPT` или форсировать `encap = yes` |

---

## 💼 Как это в DevOps

- Site-to-site «ДЦ ↔ облако» — почти всегда IPsec (облачный VPN, железный фаервол, strongSwan):
  от DevOps ждут умения сверить с другой стороной proposals, селекторы и маршруты.
- WireGuard — стандарт для своих туннелей; конфиги раскладывает Ansible-роль, ключи — из Vault.
- Mesh (Tailscale/NetBird) заменяет «VPN-сервер + bastion»: SSO и ACL «человек → сервис»
  ближе к zero trust.
- Мониторинг туннеля — **возраст последнего handshake**, а не «интерфейс UP»: `wg show dump` → экспортер → алерт.
- Kubernetes использует те же идеи: Calico/Cilium умеют шифровать трафик между нодами
  WireGuard'ом, а overlay-сети (VXLAN) — та же инкапсуляция со своим MTU.

---

## 🧪 Мини-лаба

Стенд `~/Projects/devops/stands/net-lab`: `web` = шлюз «офиса A» (10.10.0.0/24), `app` = шлюз «офиса B»
(10.20.0.0/16) с «сервером» 10.20.1.10 в netns. Туннель — 10.99.0.0/24, приватная сеть ВМ — `eth1`.

```bash
cd ~/Projects/devops/stands/net-lab && vagrant snapshot save before_vpn
vagrant ssh web          # и во втором терминале: vagrant ssh app

# 1. Пакеты (обе ВМ). Модуль уже в ядре 5.15 — ставим только утилиты
sudo apt update && sudo apt install -y wireguard-tools tcpdump && sudo modprobe wireguard

# 2. «Офисные» сети
# web:
sudo ip link add dummy0 type dummy && sudo ip addr add 10.10.0.1/24 dev dummy0 && sudo ip link set dummy0 up
# app: dummy + «сервер» 10.20.1.10 за шлюзом (netns + veth)
sudo ip link add dummy0 type dummy && sudo ip addr add 10.20.0.1/24 dev dummy0 && sudo ip link set dummy0 up
sudo ip netns add srv
sudo ip link add veth-app type veth peer name veth-srv && sudo ip link set veth-srv netns srv
sudo ip addr add 10.20.1.1/24 dev veth-app && sudo ip link set veth-app up
sudo ip -n srv addr add 10.20.1.10/24 dev veth-srv && sudo ip -n srv link set veth-srv up
sudo ip -n srv route add default via 10.20.1.1

# 3. Ключи (на каждой ВМ свои) — приватный не покидает машину
sudo sh -c 'umask 077; wg genkey > /etc/wireguard/wg0.key; wg pubkey < /etc/wireguard/wg0.key > /etc/wireguard/wg0.pub'
sudo cat /etc/wireguard/wg0.pub          # скопируй на другую сторону

# 4. Конфиги. web (подставь pub app):
sudo tee /etc/wireguard/wg0.conf >/dev/null <<EOF
[Interface]
Address    = 10.99.0.1/24
ListenPort = 51820
PrivateKey = $(sudo cat /etc/wireguard/wg0.key)

[Peer]
# app — шлюз офиса B
PublicKey  = <PUB_APP>
Endpoint   = 192.168.56.11:51820
AllowedIPs = 10.99.0.2/32, 10.20.0.0/16
EOF
# app — тот же heredoc, зеркально: Address = 10.99.0.2/24, PublicKey = <PUB_WEB>,
#       Endpoint = 192.168.56.10:51820, AllowedIPs = 10.99.0.1/32, 10.10.0.0/24

# 5. Поднимаем (обе ВМ) и читаем, что сделал wg-quick
sudo wg-quick up wg0                     # ip link add, wg setconf, ip -4 route add 10.20.0.0/16 dev wg0 …
sudo wg show                             # до первого пакета handshake нет — это нормально
ping -c2 10.99.0.2 && sudo wg show wg0 latest-handshakes     # с web

# 6. Маршрутизируемая «удалённая сеть» (с web)
ip route get 10.20.1.10                  # dev wg0 src 10.99.0.1
ping -c2 10.20.0.1                       # ✅ адрес на dummy0 — ЛОКАЛЬНЫЙ для app, форвардинг не нужен
ping -c2 -W1 10.20.1.10                  # ❌ хост ЗА шлюзом: на app ip_forward=0
sudo sysctl -w net.ipv4.ip_forward=1     # ← на app (и на web — для обратного направления)
ping -c2 10.20.1.10                      # ✅
ping -c2 -I 10.10.0.1 10.20.1.10         # ✅ LAN-to-LAN: источник из «офиса A»

# 7. Нет обратного маршрута → MASQUERADE (app)
sudo ip -n srv route del default                      # «сервер» не знает, куда слать ответы
sudo ip netns exec srv tcpdump -ni veth-srv -c2 icmp  # + с web: ping -c2 -W1 10.20.1.10 → запросы есть, ответов нет
sudo iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o veth-app -j MASQUERADE
sudo ip netns exec srv tcpdump -ni veth-srv -c2 icmp  # теперь источник 10.20.1.1, ping с web ✅
sudo iptables -t nat -D POSTROUTING -s 10.99.0.0/24 -o veth-app -j MASQUERADE
sudo ip -n srv route add default via 10.20.1.1        # правильное решение — маршрут, а не NAT

# 8. Split tunnel remote access: твой хост (ноутбук с Vagrant) — клиент к app
sudo apt install -y wireguard-tools        # хост; ключи — как в шаге 3, файл wg-lab.key
sudo wg set wg0 peer <PUB_HOST> allowed-ips 10.99.0.3/32     # app: пир «на горячую» (только в памяти!)
# хост: /etc/wireguard/wg-lab.conf
#   [Interface]  Address = 10.99.0.3/32   PrivateKey = <ключ хоста>
#   [Peer]       PublicKey = <PUB_APP>    Endpoint = 192.168.56.11:51820
#                AllowedIPs = 10.99.0.0/24, 10.20.0.0/16      ← split: только сети офиса B
#                PersistentKeepalive = 25
sudo wg-quick up wg-lab
ip route get 10.20.1.10                  # dev wg-lab
ip route get 1.1.1.1                     # через твой обычный шлюз — интернет мимо VPN
ping -c2 10.20.1.10                      # ✅
ping -c2 -W1 10.99.0.1                   # ❌ web дропает: у него в AllowedIPs(app) нет 10.99.0.3
#   фикс на web: AllowedIPs для app → 10.99.0.0/24, 10.20.0.0/16 (hub-and-spoke) + syncconf — ✅
#   full tunnel (0.0.0.0/0) и policy routing wg-quick — задача C4 в задачах темы

# 9. MTU глазами (web)
ip link show wg0 | grep -o 'mtu [0-9]*'          # 1420 = 1500 − 80
ping -M do -s 1392 -c1 10.99.0.2                 # ✅ 1392 + 28 = 1420
ping -M do -s 1393 -c1 10.99.0.2                 # ❌ message too long, mtu=1420
sudo tcpdump -ni eth1 -v -c1 udp port 51820 & sleep 1; ping -M do -s 1392 -c1 10.99.0.2
#   внешний пакет: length 1480 = 1420 + 60 (IPv4-underlay; 80 — с запасом на IPv6)
sudo ip link set wg0 mtu 1500                    # «забыли» про overhead
sudo tcpdump -ni eth1 -c2 'udp port 51820 or ip[6:2] & 0x1fff != 0' & sleep 1; ping -s 1472 -c1 10.99.0.2
#   внешний 1560 > 1500 → два фрагмента (flags [+]): здесь работает, но там, где фрагменты режут, — blackhole
sudo ip link set wg0 mtu 1420

# 10. Уборка: хост — sudo wg-quick down wg-lab; ВМ — откат снапшота
vagrant snapshot restore before_vpn
```

---

## 📌 Шпаргалка

| Команда / понятие | Смысл |
|-------------------|-------|
| `wg genkey \| wg pubkey` | Пара ключей (приватный — только на узле) |
| `wg-quick up/down wg0`, `wg-quick@wg0` | Поднять/опустить (+ маршруты), автозапуск через systemd |
| `wg show` / `wg show wg0 dump` | ⭐ Handshake, трафик, endpoint |
| `wg set wg0 peer … allowed-ips …` | Изменить пира на лету (только в памяти) |
| `bash -c 'wg syncconf wg0 <(wg-quick strip wg0)'` | Применить файл без разрыва (от root) |
| `AllowedIPs` | ⭐ Маршрут в пира + фильтр источника от пира |
| `PersistentKeepalive = 25` | Держать NAT-запись (сторона за NAT) |
| `sysctl net.ipv4.ip_forward=1` | Шлюз site-to-site |
| `TCPMSS --clamp-mss-to-pmtu` | ⭐ Лечение MTU для форвардимого TCP |
| `resolvectl domain wg0 '~corp.lab'` | Split DNS |
| `swanctl --load-all` / `--list-sas` | strongSwan: загрузить конфиг / посмотреть SA |
| UDP 500, UDP 4500, ESP (50) | Что открыть для IPsec |

---

## 🧠 Что запомнить

1. Remote access — устройство в сеть, site-to-site — сеть с сетью, mesh — все со всеми через координатор.
   Почти все VPN — L3. Split tunnel — только нужные сети; full tunnel — всё, и нужен NAT на выходе.
2. IPsec = IKE (UDP 500 → 4500) для ключей + ESP (протокол 50) для данных; Child SA —
   пара однонаправленных SA со своими SPI.
3. Tunnel mode (новый IP-заголовок) — site-to-site, transport — host-to-host; NAT-T заворачивает
   ESP в UDP 4500, потому что у ESP нет портов.
4. strongSwan сегодня — `swanctl.conf` и `swanctl`; `ipsec.conf` — legacy, IKEv1 — выключен.
5. ⭐ `AllowedIPs` в WireGuard — одновременно таблица маршрутизации к пиру и ACL на вход.
6. WireGuard молчит без трафика: отсутствие handshake до первого пакета — норма;
   мониторят возраст последнего handshake.
7. MTU 1420 = 1500 − 80; поверх облака или PPPoE — ещё меньше; форвардимый TCP лечат MSS clamping.
8. Site-to-site требует форвардинга, сети за пиром в AllowedIPs и обратного маршрута в LAN.
9. Облачный VPN: два туннеля, BGP или статика, CIDR площадок не пересекаются.
10. Отладка — снизу вверх: handshake → маршрут → tcpdump на обоих концах → форвардинг →
    файрвол → обратный путь → MTU → DNS.

---

## Задачи

> Стенд: `net-lab` (`web` 192.168.56.10, `app` 192.168.56.11) + твой хост как «ноутбук».
> Перед практикой: `vagrant snapshot save before_vpn_tasks`.

---

### Блок A. Теория

**A1.** Чем remote access VPN отличается от site-to-site и от mesh? По одному примеру, где что уместно.

<details><summary>Ответ</summary>

Remote access — устройство подключается к сети (ноутбук админа к приватной сети
через WireGuard). Site-to-site — шлюзы соединяют сети, хостам клиент не нужен (офис ↔ AWS VPC
по IPsec). Mesh — узлы соединяются напрямую друг с другом, координатор раздаёт ключи и ACL
(распределённая команда + серверы в разных облаках через Tailscale/NetBird).

</details>

**A2.** Чем L3 VPN (TUN) отличается от L2 VPN (TAP)? Когда нужен L2 и почему его избегают?

<details><summary>Ответ</summary>

L3 передаёт IP-пакеты, между сторонами маршрутизация. L2 передаёт Ethernet-кадры,
стороны в одном broadcast-домене (ARP, DHCP, broadcast ходят через туннель). L2 нужен
редко: legacy-приложения на broadcast, «растянуть» VLAN между ДЦ. Избегают из-за broadcast-шторма,
большего overhead и сложной отладки.

</details>

**A3.** Что такое full tunnel и split tunnel? Плюсы и минусы каждого, что происходит с DNS.

<details><summary>Ответ</summary>

Full tunnel — весь трафик через VPN: контроль и защита на чужом Wi-Fi, но нагрузка на
шлюз и задержки для всего интернета; DNS обычно тоже через VPN. Split tunnel — только нужные
сети: быстро и дёшево, но трафик в интернет идёт мимо корпоративного контроля; нужен split DNS,
чтобы внутренние имена резолвились внутренним DNS, а остальные — локальным.

</details>

**A4.** ⭐ Опиши обмены IKEv2: что происходит в `IKE_SA_INIT` и `IKE_AUTH`. Чем IKE SA
отличается от Child SA? Что такое SPI?

<details><summary>Ответ</summary>

`IKE_SA_INIT` (UDP 500): стороны обмениваются предложениями шифров, DH-значениями и nonce,
вырабатывают общий ключ; по NAT_DETECTION выясняют, есть ли NAT. `IKE_AUTH` (уже шифрован,
при NAT — UDP 4500): идентификаторы, аутентификация (PSK/сертификат/EAP), селекторы трафика и
создание первой Child SA. IKE SA — управляющий канал (rekey, DPD, удаление), Child SA — пара
однонаправленных ESP-SA для данных. SPI — 32-битный идентификатор SA в каждом ESP-пакете,
по нему приёмник выбирает ключ.

</details>

**A5.** Чем ESP отличается от AH? Почему AH не работает через NAT?

<details><summary>Ответ</summary>

ESP шифрует и проверяет целостность полезной нагрузки (протокол 50). AH только проверяет
целостность (протокол 51), но включает в подпись неизменяемые поля IP-заголовка, в том числе
адреса. NAT меняет адрес → проверка AH ломается.

</details>

**A6.** Tunnel mode и transport mode: что шифруется в каждом и где применяется?

<details><summary>Ответ</summary>

Tunnel mode шифрует весь исходный IP-пакет и добавляет новый внешний заголовок
(адреса шлюзов) — для site-to-site. Transport mode шифрует только полезную нагрузку, исходный
IP-заголовок остаётся — для host-to-host, часто в связке с GRE/L2TP.

</details>

**A7.** Что такое NAT-T? Какой порт, когда включается и что он делает с ESP?

<details><summary>Ответ</summary>

NAT Traversal: у ESP нет портов, и NAT (особенно PAT) не может различить потоки.
Если в `IKE_SA_INIT` обнаружен NAT, IKE переезжает на UDP 4500, а ESP заворачивается в тот же
UDP 4500 (RFC 3948). Можно форсировать (`encap = yes`), когда ESP режется файрволом.

</details>

**A8.** Policy-based и route-based VPN: как это выглядит в Linux и почему облака с BGP
требуют route-based?

<details><summary>Ответ</summary>

Policy-based: ядро шифрует пакет, если он попал под XFRM-политику (`ip xfrm policy`),
в `ip route` ничего не видно. Route-based: есть интерфейс (XFRM-интерфейс, VTI, `wg0`),
и в туннель ведёт маршрут. BGP анонсирует маршруты, а маршрутам нужен next-hop-интерфейс —
поэтому облачные VPN с динамической маршрутизацией предполагают route-based.

</details>

**A9.** ⭐ Какие две роли у `AllowedIPs` в WireGuard? Что будет, если у двух пиров одного
интерфейса одинаковые префиксы?

<details><summary>Ответ</summary>

(1) Маршрутизация: для исходящего пакета WireGuard выбирает пира, чей `AllowedIPs`
содержит адрес назначения. (2) ACL: входящий пакет от пира принимается, только если его
адрес источника входит в `AllowedIPs` этого пира. Одинаковый префикс у двух пиров не
дублируется: он «переезжает» к пиру, которому назначен последним, у первого пропадает.

</details>

**A10.** Почему `wg show` сразу после `wg-quick up` может не показывать handshake? Как тогда
мониторить состояние туннеля?

<details><summary>Ответ</summary>

WireGuard устанавливает handshake только когда есть что отправить; без трафика он
молчит. Мониторят возраст `latest handshake` (`wg show wg0 latest-handshakes` / `dump`) при
наличии трафика или с keepalive, плюс счётчики transfer и пробы до адреса за туннелем.

</details>

**A11.** Зачем нужен `PersistentKeepalive` и на какой стороне его ставить?

<details><summary>Ответ</summary>

Запись NAT живёт десятки секунд без трафика; после её истечения сторона снаружи
не может инициировать связь. Keepalive (обычно 25 с) держит запись. Ставят на стороне **за NAT**
(клиент), серверу с публичным адресом не нужно.

</details>

**A12.** Посчитай overhead WireGuard для IPv4 и IPv6 underlay. Почему wg-quick ставит 1420?
Когда MTU нужно уменьшить ещё?

<details><summary>Ответ</summary>

IPv4: 20 (IP) + 8 (UDP) + 32 (WG: 4 тип + 4 индекс + 8 счётчик + 16 tag) = 60.
IPv6: 40 + 8 + 32 = 80. wg-quick берёт MTU интерфейса к Endpoint и вычитает 80 с запасом
на IPv6: 1500 − 80 = 1420. Уменьшать, если underlay меньше 1500: PPPoE (1492 → 1412),
облака с 1450/1460, туннель внутри другого туннеля (VXLAN, IPsec).

</details>

**A13.** Перечисли четыре условия, без которых не заработает site-to-site через WireGuard.

<details><summary>Ответ</summary>

(1) `ip_forward=1` на шлюзах; (2) сеть за пиром в его `AllowedIPs` на обеих сторонах;
(3) обратный маршрут у хостов LAN (или MASQUERADE); (4) файрвол `FORWARD` пропускает трафик
между `wg0` и LAN (плюс в облаке — отключённая source/dest-проверка и маршрут в VPC).

</details>

**A14.** Как wg-quick реализует full tunnel (`0.0.0.0/0`) и почему пакеты к самому Endpoint
не уходят в петлю?

<details><summary>Ответ</summary>

`wg set wg0 fwmark 51820` помечает пакеты самого WireGuard; default через `wg0` кладётся
в таблицу 51820; правило `not fwmark 51820 table 51820` отправляет туда всё непомеченное, а
помеченные UDP-пакеты к Endpoint идут по main. Правило `table main suppress_prefixlength 0`
позволяет конкретным маршрутам main (LAN, mgmt) выиграть у default из таблицы 51820.

</details>

**A15.** Чем Tailscale, Headscale и NetBird отличаются друг от друга? Что такое subnet router
и exit node?

<details><summary>Ответ</summary>

Tailscale — коммерческий координатор (SaaS) + open-source клиенты, NAT traversal через
STUN и DERP. Headscale — open-source self-hosted замена координатора Tailscale, клиенты те же.
NetBird — полностью open-source стек (management, signal, relay) с SSO и веб-UI, можно своё или
их облако. Subnet router — узел, анонсирующий сеть за собой в mesh; exit node — узел,
через который идёт весь интернет-трафик клиента (full tunnel).

</details>

**A16.** Из чего состоит AWS Site-to-Site VPN и зачем в каждом подключении два туннеля?

<details><summary>Ответ</summary>

Customer Gateway (описание твоего устройства: внешний IP, ASN), Virtual Private Gateway
(одна VPC) или Transit Gateway (хаб), VPN Connection с двумя туннелями. Два туннеля заканчиваются
на разных endpoint'ах AWS: при обслуживании одного трафик уходит во второй — если настроены оба
и маршрутизация (BGP или статика с приоритетами).

</details>

---

### Блок B. «Что делает конфиг / что покажет вывод»

```ini
B1.  AllowedIPs = 10.99.0.2/32
B2.  AllowedIPs = 10.99.0.2/32, 10.20.0.0/16
B3.  AllowedIPs = 0.0.0.0/0, ::/0
B4.  PersistentKeepalive = 25
B5.  Table = off
B6.  MTU = 1380
B7.  PostUp = iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o eth0 -j MASQUERADE
B8.  start_action = trap                             # strongSwan, children
B9.  local_ts = 10.10.0.0/24  +  remote_ts = 10.20.0.0/16
B10. esp_proposals = aes256gcm16-ecp384
B11. iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
B12. resolvectl domain wg0 '~corp.lab'
```

- **B1.** В пира идёт только трафик к 10.99.0.2 и только с этого адреса пакеты принимаются.
- **B2.** Плюс сеть 10.20.0.0/16 за пиром: site-to-site, wg-quick добавит маршрут.
- **B3.** Full tunnel: весь трафик в пира, wg-quick включит policy routing с fwmark.
- **B4.** Keepalive-пакет каждые 25 с — держит NAT-запись.
- **B5.** wg-quick не добавляет маршруты для AllowedIPs (их раздаёт BGP/скрипт).
- **B6.** MTU интерфейса 1380 — под underlay меньше 1500 (например, облако 1460 или туннель в туннеле).
- **B7.** Трафик VPN-клиентов в интернет подменяет источник на адрес `eth0` шлюза — нужно для full tunnel.
- **B8.** Ставит trap-политику: туннель поднимается при первом пакете под селектор.
- **B9.** Шифруется трафик между 10.10.0.0/24 (у себя) и 10.20.0.0/16 (у другой стороны);
  на другой стороне селекторы должны быть зеркальными.
- **B10.** Child SA: AES-256-GCM, при rekey — новый DH на ECP-384 (PFS).
- **B11.** В форвардимых SYN через `wg0` MSS переписывается под MTU маршрута — лечит висящие крупные TCP-передачи.
- **B12.** Запросы к `*.corp.lab` уходят на DNS интерфейса `wg0`; «~» — только маршрутизация, не search-домен.

**B13.** Прочитай вывод и поставь диагноз:

```text:no-line-numbers
peer: Xk3…=
  endpoint: 203.0.113.7:43122
  allowed ips: 10.99.0.5/32
  latest handshake: 7 minutes, 12 seconds ago
  transfer: 1.20 MiB received, 45.31 MiB sent
```
(пользователь говорит, что «VPN подключен, но ничего не открывается»)

<details><summary>Ответ</summary>

Мы отправили 45 МБ, получили 1.2 МБ, последний handshake 7 минут назад при активном
трафике — ответы не приходят. У клиента сменился адрес/NAT-запись истекла, а сервер держит
старый endpoint, или путь к серверу закрыт. Проверить: `tcpdump udp port 51820` на сервере
(доходят ли пакеты), keepalive у клиента, не заблокирован ли UDP в сети клиента.

</details>

**B14.** Новому сотруднику по ошибке выдали `AllowedIPs = 10.99.0.7/32`, который уже есть
у другого пира. Что произойдёт с обоими?

<details><summary>Ответ</summary>

Префикс переезжает к последнему пиру: трафик к 10.99.0.7 пойдёт новому сотруднику,
а пакеты старого с этого адреса будут отброшены как «unallowed src IP». У старого VPN сломан.

</details>

---

### Блок C. Практика

**C1. 🔑 Site-to-site с нуля.** Без подглядывания в конспект собери туннель `web ↔ app`
с сетями 10.10.0.0/24 и 10.20.0.0/16 (dummy + netns-«сервер»), включи автозапуск
(`wg-quick@wg0`, `ip_forward` в `/etc/sysctl.d/`), перезагрузи обе ВМ и докажи, что
LAN-to-LAN пинг работает после ребута.

<details><summary>Ответ</summary>

Конфиги — из мини-лабы. Для ребута: `sudo systemctl enable wg-quick@wg0`,
`echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-wg.conf`, а dummy и netns — через
`PostUp` в `wg0.conf` или systemd-networkd (иначе после ребута их нет). Проверка:
`ping -I 10.10.0.1 10.20.1.10` после `vagrant reload`.

</details>

**C2. Маршрут или NAT.** Убери у netns-«сервера» маршрут обратно. Сними tcpdump на `veth-srv`
и `wg0` на `app`, объясни, где теряется ответ. Почини двумя способами (маршрут и MASQUERADE)
и покажи, какой адрес источника видит «сервер» в каждом случае.

<details><summary>Ответ</summary>

Без маршрута запрос от 10.99.0.1 доходит до `veth-srv` (tcpdump видит echo request),
ответ ядро «сервера» отправить не может (`Network is unreachable`, в tcpdump ответа нет).
Маршрут `ip -n srv route add default via 10.20.1.1` — «сервер» видит настоящий 10.99.0.1;
MASQUERADE `-o veth-app` — видит 10.20.1.1 (адрес шлюза), реальный источник теряется.

</details>

**C3. Split tunnel и hub-and-spoke.** Подключи хост к `app` как remote-access клиента
(split tunnel: только 10.99.0.0/24 и 10.20.0.0/16). Добейся, чтобы с хоста пинговался
и `web` (10.99.0.1) через `app`. Какие AllowedIPs и где пришлось поменять?

<details><summary>Ответ</summary>

На хосте `AllowedIPs = 10.99.0.0/24, 10.20.0.0/16`, на `app` пир хоста `10.99.0.3/32`.
Чтобы хост ↔ `web` работал через `app`: на `web` у пира `app` расширить AllowedIPs до
`10.99.0.0/24` (иначе `web` отбросит пакет от 10.99.0.3), на `app` — `ip_forward=1`
(пакет входит и выходит через `wg0`). Это и есть hub-and-spoke.

</details>

**C4. Full tunnel.** Переведи `web` в режим full tunnel через `app` (`AllowedIPs = 0.0.0.0/0`).
Покажи `ip rule`, таблицу 51820, первый хоп `traceroute` до 1.1.1.1 и объясни, почему
`vagrant ssh` не отвалился. Что нужно сделать на `app`, чтобы у `web` работал интернет?

<details><summary>Ответ</summary>

```bash
sudo iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o eth0 -j MASQUERADE   # app: выход в интернет
sudo wg-quick down wg0                                                      # web
sudo sed -i 's|^AllowedIPs = .*|AllowedIPs = 0.0.0.0/0|' /etc/wireguard/wg0.conf
sudo wg-quick up wg0
ip rule                          # … not from all fwmark 0xca6c lookup 51820; from all lookup main suppress_prefixlength 0
ip route show table 51820        # default dev wg0 scope link
traceroute -n -m 3 1.1.1.1       # 1  10.99.0.2 …
```
`vagrant ssh` идёт через `eth0` (сеть 192.168.121.0/24): это конкретный маршрут в main,
и правило `suppress_prefixlength 0` отдаёт ему приоритет перед default из 51820. Без MASQUERADE
на `app` пакеты web уйдут в интернет с источником 10.99.0.1 и ответы не вернутся.
Откат — вернуть прежние AllowedIPs и `wg-quick down/up`.

</details>

**C5. AllowedIPs как ACL.** Включи dynamic debug модуля wireguard на `app` и пошли с `web`
пакет с адреса, которого нет в `AllowedIPs`. Найди сообщение в `dmesg`.

<details><summary>Ответ</summary>

```bash
echo 'module wireguard +p' | sudo tee /sys/kernel/debug/dynamic_debug/control   # app
sudo dmesg -w | grep -i wireguard                                               # app
sudo ip addr add 10.10.5.1/32 dev dummy0 && ping -c1 -W1 -I 10.10.5.1 10.20.0.1  # web
# app: wg0: Packet has unallowed src IP (10.10.5.1) from peer N (192.168.56.10:51820)
```

</details>

**C6. Три поломки handshake.** По очереди: (1) неверный публичный ключ пира; (2) DROP на
UDP 51820 на `app`; (3) неверный порт в `Endpoint`. Для каждого зафиксируй вывод `wg show`,
`tcpdump -ni eth1 udp` на обеих сторонах и `dmesg` (с debug). Чем случаи различаются снаружи?

<details><summary>Ответ</summary>

(1) Неверный ключ: инициатор шлёт handshake initiation, ответа нет; на приёмнике
в debug — `Invalid handshake initiation`; `wg show` — без handshake. (2) DROP на 51820: на `app`
tcpdump **видит** входящие пакеты (tcpdump работает до netfilter), ответов нет, в dmesg `app` тихо.
(3) Неверный порт: на `app` в tcpdump на 51820 пусто, ядро отвечает ICMP port unreachable
(если не режется). Снаружи все три выглядят одинаково — «нет handshake»; различает только
наблюдение на обеих сторонах.

</details>

**C7. PMTUD blackhole и MSS clamping.** Добавь netns-«клиента» 10.10.1.10 за `web`
(расширь AllowedIPs до 10.10.0.0/16). Запрети на обоих шлюзах исходящий ICMP
`fragmentation-needed` и передай 5 МБ по TCP от «клиента» к «серверу» (`nc`). Покажи зависание,
затем почини MSS clamping и объясни, почему пинг маленькими пакетами всё время работал.

<details><summary>Ответ</summary>

```bash
# web: «клиент» за шлюзом (на app: AllowedIPs для web → 10.10.0.0/16)
sudo ip netns add cli && sudo ip link add veth-web type veth peer name veth-cli
sudo ip link set veth-cli netns cli && sudo ip addr add 10.10.1.1/24 dev veth-web && sudo ip link set veth-web up
sudo ip -n cli addr add 10.10.1.10/24 dev veth-cli && sudo ip -n cli link set veth-cli up
sudo ip -n cli route add default via 10.10.1.1
# обе ВМ: «кто-то режет ICMP»
sudo iptables -A OUTPUT -p icmp --icmp-type fragmentation-needed -j DROP
# app: sudo ip netns exec srv nc -l 9000 > /dev/null
head -c 5M /dev/urandom | sudo ip netns exec cli nc -q1 -w10 10.20.1.10 9000   # висит
# лечение на обоих шлюзах:
sudo iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```
Оба конца — хосты с MTU 1500, договорились о MSS 1460; сегменты 1500 не лезут в `wg0` (1420),
шлюз шлёт ICMP «frag needed», но он режется → blackhole. Пинг маленький (84 байта) — ничего не
превышает. MSS clamping переписывает MSS в SYN на 1380, и сегменты помещаются.

</details>

**C8. Split DNS.** Подними `dnsmasq` на `app` на адресе 10.20.0.1 с зоной `corp.lab`
(`db.corp.lab → 10.20.1.10`). Настрой на `web` split DNS через `resolvectl` и докажи:
`db.corp.lab` резолвится через `wg0`, `example.com` — через обычный резолвер.

<details><summary>Ответ</summary>

`app`: `sudo apt install -y dnsmasq-base` (без сервиса, который подерётся с systemd-resolved
за порт 53), затем `sudo dnsmasq --listen-address=10.20.0.1 --bind-interfaces --no-resolv
--address=/db.corp.lab/10.20.1.10`. `web`:
`resolvectl dns wg0 10.20.0.1; resolvectl domain wg0 '~corp.lab'; resolvectl default-route wg0 false`.
`resolvectl query db.corp.lab` покажет `-- link: wg0`, `resolvectl query example.com` — `eth0`.
Проверка трафиком: `sudo tcpdump -ni wg0 udp port 53` видит только запросы к `corp.lab`.

</details>

**C9. strongSwan.** Подними site-to-site из §3 конспекта (WireGuard перед этим опусти).
Затем по очереди сломай: proposals, PSK, `remote_ts`. Для каждого — строка из
`journalctl -u strongswan`. Включи `encap = yes` и покажи в tcpdump разницу ESP vs UDP 4500.

<details><summary>Ответ</summary>

Ошибки: proposals → `NO_PROPOSAL_CHOSEN`; PSK → `AUTHENTICATION_FAILED`
(на ответчике — `tried 1 shared key … MAC mismatched`); `remote_ts` → `TS_UNACCEPTABLE`.
Без NAT на стенде tcpdump покажет `ESP(spi=0x…)`; с `encap = yes` — `UDP 4500` с `UDP-encap`.

</details>

**C10. Мониторинг туннеля.** Напиши `wg-check.sh`: для каждого пира из `wg show wg0 dump`
выводит возраст handshake и возвращает код 1, если хоть один старше N секунд (параметр).
Бонус: выводи метрики в формате textfile collector node_exporter.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
# wg-check.sh [интерфейс] [макс_возраст_с]
IF=${1:-wg0}; MAX=${2:-300}; now=$(date +%s); rc=0
while IFS=$'\t' read -r pub _psk _ep _ips hs _rx _tx _ka; do
  age=$(( hs == 0 ? -1 : now - hs ))
  echo "wg_handshake_age_seconds{interface=\"$IF\",peer=\"${pub:0:8}\"} $age"
  (( hs == 0 || age > MAX )) && { echo "ALERT ${pub:0:8} age=$age" >&2; rc=1; }
done < <(sudo wg show "$IF" dump | tail -n +2)
exit $rc
```
Первая строка `dump` — сам интерфейс (4 поля), у пиров — 8, поэтому `tail -n +2`.
Цикл без пайпа (`< <(…)`), чтобы `rc` не потерялся в подоболочке. Для node_exporter пиши stdout в
`/var/lib/node_exporter/textfile/wg.prom` по cron.

</details>

**C11. Docker ломает шлюз.** Установи Docker на `app`, проверь site-to-site, найди причину
в `iptables -S FORWARD` и почини правилом в `DOCKER-USER` (связь с [11. Файрвол/iptables](/network/11-firewall-iptables) §7).

<details><summary>Ответ</summary>

Docker ставит `-P FORWARD DROP` и свои цепочки; трафик `wg0 ↔ veth-app` под них
не подпадает и дропается. Решение: `sudo iptables -I DOCKER-USER -i wg0 -j ACCEPT` и
`-o wg0 -j ACCEPT` (Docker не трогает `DOCKER-USER`), а лучше — не ставить Docker на шлюз.

</details>

**C12 (по желанию). Headscale.** Подними Headscale в Docker на `web`, подключи `app` и хост
официальным клиентом Tailscale, объяви с `app` subnet route 10.20.0.0/16. Сравни объём
настройки с C1 и C3.

<details><summary>Ответ</summary>

Headscale: контейнер `headscale/headscale` с `config.yaml` (`server_url`, префиксы
адресов), `headscale users create lab`, `headscale preauthkeys create --user <ID из users list>`,
на узлах `tailscale up --login-server http://192.168.56.10:8080 --authkey …`;
на `app` — `--advertise-routes=10.20.0.0/16` и одобрение маршрута в Headscale
(синтаксис команд менялся между версиями — сверяйся с `headscale --help`).
Ключи, адреса и маршруты раздаёт координатор — руками их не пишешь.

</details>

---

### Блок D. Инциденты

**D1.** Site-to-site настроен: шлюзы пингуют друг друга по туннельным адресам, но хост
офиса A не видит хост офиса B. Что проверить по порядку?

<details><summary>Ответ</summary>

(1) `ip route get <хост B>` на шлюзе A — маршрут в `wg0`; (2) `AllowedIPs` на обеих
сторонах содержит сети LAN, а не только /32 шлюзов; (3) `ip_forward` на обоих шлюзах;
(4) `FORWARD` в файрволах; (5) у хостов LAN есть маршрут к удалённой сети через шлюз
(шлюз — не их default gateway?); (6) tcpdump на `wg0` и LAN-интерфейсе обеих сторон.

</details>

**D2.** Туннель до AWS: в консоли один туннель UP, второй DOWN «с самого начала».
Раз в несколько недель связь пропадает на 5-10 минут. Причина и решение.

<details><summary>Ответ</summary>

Настроен только один туннель. AWS периодически обслуживает endpoint'ы, и в это время
активный туннель переподнимается. Решение: поднять оба туннеля и маршрутизацию через оба
(BGP с отказоустойчивостью или статика с приоритетами), мониторить состояние каждого.

</details>

**D3.** Разработчики через VPN: SSH работает, `git clone` большого репозитория висит,
веб-консоль мониторинга открывается наполовину.

<details><summary>Ответ</summary>

MTU/PMTUD blackhole: мелкие пакеты проходят, крупные сегменты не лезут в туннель,
а ICMP «frag needed» режется. Проверка `ping -M do -s 1392/1472`, `tracepath`. Лечение:
MSS clamping на шлюзе, корректный MTU туннеля, не резать ICMP type 3 code 4.

</details>

**D4.** Удалённые сотрудники: из офиса нельзя зайти на ноутбук сотрудника по VPN-адресу,
если тот пару минут ничего не делал. Когда сотрудник сам что-то открывает — снова можно.

<details><summary>Ответ</summary>

NAT-запись у сотрудника истекает, и сервер не может инициировать связь первым;
когда клиент шлёт трафик, запись создаётся заново. Решение — `PersistentKeepalive = 25` у клиента.

</details>

**D5.** На VPN-шлюз поставили Docker для «маленького экспортера». Утром site-to-site перестал
пропускать трафик, хотя handshake свежий.

<details><summary>Ответ</summary>

Docker поставил политику `FORWARD DROP`, трафик через шлюз режется (handshake —
это INPUT/OUTPUT, он не пострадал). Разрешить `wg0` в `DOCKER-USER` или убрать Docker со шлюза.

</details>

**D6.** Выдали доступ новому сотруднику — и у одного из старых перестал работать VPN.

<details><summary>Ответ</summary>

Новому выдали `AllowedIPs`, пересекающийся со старым пиром (тот же /32 или
перекрывающую подсеть). Префикс переехал к новому. Нужен учёт адресов (IPAM, файл в git,
генерация конфигов Ansible) и проверка уникальности.

</details>

**D7.** IPsec: `swanctl --list-sas` — IKE SA ESTABLISHED, Child SA INSTALLED, счётчик
исходящих байтов растёт, входящих — 0.

<details><summary>Ответ</summary>

Туннель установлен, наши пакеты уходят, ответы не приходят: другая сторона не маршрутизирует
ответ в туннель (нет маршрута/`ip_forward`), её файрвол режет ESP или ответный трафик,
селекторы у неё уже, чем у нас. Смотреть tcpdump `esp` на обеих сторонах и `--list-sas` там.

</details>

**D8.** После включения VPN у сотрудников весь интернет «тормозит», а в логах корпоративного
DNS — запросы к YouTube и маркетплейсам.

<details><summary>Ответ</summary>

Full tunnel DNS (или `DNS =` без домена): все запросы идут в корпоративный DNS через
VPN. Перейти на split DNS: DNS-сервер и `~corp.lab` на интерфейсе VPN, `default-route false`.

</details>

**D9.** После перезагрузки шлюза туннель поднялся, handshake свежий, но сеть офиса B недоступна.

<details><summary>Ответ</summary>

`ip_forward` включали `sysctl -w` (не сохранилось) или правила `FORWARD`/NAT не
персистентны. Прописать в `/etc/sysctl.d/` и `PostUp` в конфиге туннеля.

</details>

**D10.** В облаке ВМ-шлюз со strongSwan: с самой ВМ офис пингуется, с остальных ВМ VPC — нет.

<details><summary>Ответ</summary>

В таблице маршрутизации VPC нет маршрута «сеть офиса → ВМ-шлюз», у ВМ не выключена
проверка source/destination (AWS `SourceDestCheck`), security group не пускает трафик
из подсетей VPC к шлюзу, или на шлюзе нет `ip_forward`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое VPN и какие виды бывают?

<details><summary>Ответ</summary>

Туннель с инкапсуляцией и шифрованием поверх чужой сети. Виды: remote access,
site-to-site, mesh; L3/L2; full/split tunnel.

</details>

**2.** Как работает IPsec: IKE, ESP, SA?

<details><summary>Ответ</summary>

IKEv2 (UDP 500/4500) аутентифицирует стороны и вырабатывает ключи — IKE SA; данные идут
в ESP (протокол 50) по Child SA — паре однонаправленных SA с SPI; селекторы задают, что шифровать.

</details>

**3.** Что такое NAT-T и зачем нужен UDP 4500?

<details><summary>Ответ</summary>

ESP без портов не проходит через NAT; при обнаружении NAT ESP заворачивается в UDP 4500.

</details>

**4.** Tunnel mode vs transport mode?

<details><summary>Ответ</summary>

Tunnel — шифруется весь пакет с новым заголовком (site-to-site); transport — только
полезная нагрузка (host-to-host).

</details>

**5.** Чем WireGuard отличается от IPsec и OpenVPN?

<details><summary>Ответ</summary>

WireGuard — минимальный L3 в ядре, только UDP, ключи вместо PKI, роуминг; IPsec — стандарт
для железа и облаков, сложнее; OpenVPN — userspace, TLS, умеет TCP 443, медленнее.

</details>

**6.** Что такое `AllowedIPs` в WireGuard?

<details><summary>Ответ</summary>

Список префиксов пира: маршрутизация исходящих пакетов к пиру и фильтр источника входящих.

</details>

**7.** Split tunnel vs full tunnel — что и когда?

<details><summary>Ответ</summary>

Full — весь трафик через VPN (контроль, нужна NAT на выходе); split — только нужные сети
(быстро, нужен split DNS).

</details>

**8.** Почему через VPN ping работает, а большие файлы не передаются?

<details><summary>Ответ</summary>

MTU: туннель съедает 60-80 байт, крупные пакеты с DF не проходят, ICMP «frag needed»
режется → blackhole. MSS clamping и правильный MTU.

</details>

**9.** Как связать офис (или свой ДЦ) с облаком?

<details><summary>Ответ</summary>

Site-to-site IPsec к облачному VPN-шлюзу (два туннеля, BGP), без пересечения CIDR;
для высоких требований — выделенный канал (Direct Connect/Interconnect).

</details>

**10.** Туннель поднят, а трафика нет — как будешь искать причину?

<details><summary>Ответ</summary>

Снизу вверх: handshake/SA → маршрут → tcpdump на обоих концах → forwarding → файрвол →
обратный маршрут → MTU → DNS.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю IKE SA, Child SA, ESP, NAT-T и tunnel/transport mode без шпаргалки
- [ ] Поднял site-to-site на WireGuard с сетями за шлюзами и пережил перезагрузку
- [ ] Понимаю `AllowedIPs` как маршрут и ACL, видел `unallowed src IP`
- [ ] Настроил split tunnel и full tunnel, прочитал `ip rule` от wg-quick
- [ ] Воспроизвёл PMTUD blackhole и починил MSS clamping
- [ ] Настроил split DNS через `resolvectl`
- [ ] Поднял strongSwan на `swanctl.conf` и знаю три главные ошибки в логе
- [ ] Иду по чек-листу «туннель есть, трафика нет» и смотрю tcpdump на обоих концах
