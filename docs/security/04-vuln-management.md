---
title: "04. Управление уязвимостями"
description: "Блок → Безопасность → тема 04. Опирается на"
---

# 04. Управление уязвимостями

> Блок → Безопасность → тема 04. Опирается на
> [../Docker/10_security_best_practices.md](/docker/10-security-best-practices) (сканеры, SBOM, cosign) ·
> [../CICD/13_quality_security.md](/cicd/13-quality-security) (виды сканов, gate, supply chain) ·
> [01_security_mindset.md](/security/01-security-mindset) (риск и поверхность атаки).
> Там — **как запустить сканер**. Здесь — **что делать с его отчётом**: как отличить
> срочное от шума, как оформить исключение, в какие сроки патчить и как не дать самому
> сканеру стать точкой взлома.
>
> **После темы ты умеешь:** читать вектор CVSS v3.1/v4.0, проверять CVE по EPSS и CISA KEV,
> разбирать JSON-отчёт Trivy через `jq`, принимать решение «чинить сейчас / в SLA / принять
> риск / не затронуты», вести `.trivyignore.yaml` со сроком и обоснованием, делать SBOM
> и пересканировать его, настраивать Renovate и процесс обновления базового образа.

---

## 🗺️ Карта темы

```text
 ИСТОЧНИКИ ЗНАНИЙ           СКАНЕР                 ТРИАЖ                        РЕШЕНИЕ
 ────────────────           ──────                 ─────                        ───────
 CVE / NVD, GHSA, OSV  ─┐                          KEV? ─► да ─────────────────► P0: чинить сейчас
 трекеры Debian/Ubuntu/ ├─► Trivy / Grype  ─► отчёт  │ нет                        (или митигировать)
 Red Hat (vendor sev.)  │   (образ, fs, SBOM)  JSON  ▼
 EPSS (вероятность)  ───┤                          эксплойт / EPSS высокий?
 CISA KEV (факт)     ───┘                            ▼
                                                   достижимо? (в runtime, из сети,   ──► нет ► VEX not_affected
                                                   функция вызывается?)                    или ignore со сроком
                                                     ▼ да
                                                   есть fixed version? ── нет ► компенсирующие меры
                                                     ▼ да                         + пересмотр
                                                   патч в срок SLA по приоритету ► метрики: MTTR, SLA %
```text
---

## 1. Словарь: CVE, CWE и откуда берутся данные

| Термин | Что это | Пример |
|--------|---------|--------|
| **CVE** | Идентификатор конкретной уязвимости в конкретном продукте | `CVE-2021-44228` (Log4Shell) |
| **CNA** | Организация, которая выдаёт CVE ID (вендоры, дистрибутивы, GitHub, MITRE) | Red Hat, GitHub, Debian |
| **NVD** | База NIST: к CVE добавляет CVSS, CPE, ссылки | nvd.nist.gov |
| **CWE** | Класс слабости — «тип ошибки», а не конкретный баг | CWE-787 out-of-bounds write, CWE-89 SQL injection |
| **GHSA** | GitHub Security Advisory — для пакетов npm/PyPI/Go/Maven… | `GHSA-xxxx-xxxx-xxxx` |
| **OSV** | Открытая база уязвимостей open source (osv.dev), агрегирует GHSA, PyPI, Go… | — |
| **Vendor advisory** | Бюллетень дистрибутива: какие версии затронуты и где фикс | DSA/DLA (Debian), USN (Ubuntu), RHSA |

> ⭐ Для пакетов ОС правда — у **дистрибутива**, а не в NVD. Debian может пометить CVE как
> «не затрагивает нашу сборку», а NVD этого не знает. Поэтому Trivy берёт severity
> в первую очередь у вендора и только потом у NVD — это видно в поле `SeveritySource`.

---

## 2. CVSS: читай вектор, а не число

**CVSS v3.1** — то, что до сих пор чаще всего в отчётах:

```text
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H   = 9.8 CRITICAL
         │    │    │    │    │   └──┴───┴── последствия: конфиденциальность, целостность, доступность
         │    │    │    │    └── Scope: U — остаёмся в том же компоненте, C — выходим за него
         │    │    │    └── User Interaction: N — жертве ничего не надо делать
         │    │    └── Privileges Required: N — без логина
         │    └── Attack Complexity: L — без особых условий
         └── Attack Vector: N сеть · A соседняя сеть · L локально · P физически
```text
**CVSS v4.0** (FIRST, ноябрь 2023) — что поменялось:

| | v3.1 | v4.0 |
|---|------|------|
| Группы метрик | Base, Temporal, Environmental | **Base, Threat, Environmental, Supplemental** |
| Новые базовые | — | **AT** (Attack Requirements: N/P), **UI** стало N/P/A (passive/active) |
| Последствия | C/I/A + Scope | **VC/VI/VA** — уязвимая система, **SC/SI/SA** — последующие системы (Scope убрали) |
| Эксплуатация | Temporal E | **Threat: E** = X / A (attacked) / P (PoC) / U (unreported) |
| Подпись оценки | просто «9.8» | **CVSS-B, CVSS-BT, CVSS-BE, CVSS-BTE** — видно, какие группы учтены |

```text
CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N
```text
Шкала одинакова для обеих версий: None 0.0 · Low 0.1–3.9 · Medium 4.0–6.9 · High 7.0–8.9 ·
Critical 9.0–10.0.

**Почему base score ≠ твой риск:**
- Base — свойства уязвимости «в вакууме». Он не знает, что библиотека лежит в образе, но
  не загружается, что сервис не торчит в интернет, что эксплойта нет.
- **Threat** (v4) / Temporal (v3.1) снижает оценку, если эксплуатации не видно.
- **Environmental** — твой контекст: требования к C/I/A (CR/IR/AR) и modified-метрики
  (например, MAV:L, если компонент доступен только локально).
- Итог: почти всегда реальный приоритет ниже base score, но иногда выше — HIGH, который
  уже в KEV, срочнее CRITICAL без эксплойта (раздел 3).

---

## 3. EPSS и KEV: вероятность и факт

| | EPSS | CISA KEV |
|---|------|----------|
| Кто ведёт | FIRST | CISA (агентство кибербезопасности США) |
| Отвечает на вопрос | «Какова вероятность эксплуатации в ближайшие 30 дней?» | «Эксплуатируется ли это уже?» |
| Формат | Число 0–1 + перцентиль, пересчёт ежедневно | Каталог CVE с датой добавления и дедлайном |
| Версия | EPSS v4 (с 17 марта 2025) | На 25.09.2026: 1726 записей |
| Где взять | `api.first.org/data/v1/epss` | JSON-фид CISA |

```bash
# EPSS по списку CVE (до ~50 штук за запрос — длинные URL лучше бить на пачки)
curl -s "https://api.first.org/data/v1/epss?cve=CVE-2021-44228,CVE-2023-45853" \
  | jq -r '.data[] | [.cve, .epss, .percentile] | @tsv'

# KEV: скачать каталог и проверить свои CVE
curl -s -o kev.json https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
jq -r '.catalogVersion, .count' kev.json
jq -r --arg c CVE-2021-44228 '.vulnerabilities[] | select(.cveID==$c)
  | [.cveID, .dateAdded, .dueDate, .knownRansomwareCampaignUse] | @tsv' kev.json
```text
Живые данные для калибровки (EPSS на 26.09.2026, CVSS — NVD v3.1):

| CVE | Что | CVSS | EPSS | KEV | Вывод |
|-----|-----|------|------|-----|-------|
| CVE-2021-44228 | Log4Shell | 10.0 | 0.99999 | ✅ добавлена 10.12.2021, срок 24.12.2021 | P0 без обсуждений |
| CVE-2023-44487 | HTTP/2 Rapid Reset (DDoS) | **7.5 HIGH** | 0.99999 | ✅ | HIGH, но срочнее многих CRITICAL |
| CVE-2023-4863 | libwebp | 8.8 | 0.99979 | ✅ | P0 для всего, что парсит картинки |
| CVE-2024-6387 | regreSSHion (OpenSSH) | 8.1 | 0.99506 | ❌ | KEV — не полный список: высокая EPSS = срочно |
| CVE-2024-3094 | бэкдор xz | 10.0 | 0.85974 | ❌ | срочно, если версия 5.6.0/5.6.1 реально стоит |
| CVE-2022-37434 | zlib `inflateGetHeader` | 9.8 | 0.17852 | ❌ | важно, если код зовёт эту функцию |
| CVE-2023-45853 | zlib MiniZip | **9.8 CRITICAL** | 0.03179 | ❌ | в Debian 12 код даже не собирается (раздел 6) |

> ⚠️ EPSS и KEV — сигналы, а не вердикт. KEV неполный (regreSSHion нет), EPSS
> не знает твою архитектуру. Решение принимает триаж: достижимо ли это у тебя.

---

## 4. Триаж: алгоритм «что с этим делать»

```text
 1. В KEV или есть публичный рабочий эксплойт / EPSS высокий (≳ 0.1)?
      └─ да → кандидат в P0/P1, дальше проверяем только достижимость
 2. Достижимо у нас?
      • пакет есть в RUNTIME-образе (а не только в build-стадии)?
      • процесс его загружает (библиотека слинкована / модуль импортируется)?
      • компонент обрабатывает недоверенный ввод или слушает сеть?
      • уязвимая функция/фича используется (inflateGetHeader, HTTP/2, awk в busybox…)?
      • AV:L — есть ли у атакующего shell? (distroless, read-only, non-root снижают)
      └─ нет → not_affected (VEX) или исключение со сроком и обоснованием
 3. Есть fixed version?
      ├─ да → патч в срок по SLA (раздел 8)
      └─ нет → компенсирующие меры: убрать пакет, выключить фичу, WAF-правило,
               NetworkPolicy, другой базовый образ; пересмотр каждые 30 дней
 4. Записать решение там, где его увидят: MR с фиксом, .trivyignore.yaml, VEX, тикет
```text
| Решение | Когда | Где фиксируется |
|---------|-------|-----------------|
| **Fix now** | KEV/эксплойт + достижимо | Emergency change, инцидент при необходимости |
| **Fix in SLA** | Достижимо, фикс есть, эксплуатации не видно | Тикет с дедлайном, Renovate MR |
| **Mitigate** | Фикса нет, риск реален | Тикет + компенсирующая мера, пересмотр |
| **Accept (risk)** | Недостижимо или риск мал, фикс дорог | `.trivyignore.yaml`: срок, причина, владелец |
| **Not affected** | Доказано, что уязвимого кода нет/он не вызывается | VEX-документ (раздел 7) |

---

## 5. Читаем отчёт Trivy

```bash
IMG=python:3.12-slim
TRIVY='docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache
       -v "$PWD":/work -w /work aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969'
eval $TRIVY image --quiet --scanners vuln --format json -o report.json $IMG
```text
Реальный прогон 27.09.2026 (у тебя цифры будут другими — базы обновляются каждый день):

```text
python:3.12-slim (Debian 13.7):  162 находки, но уникальных CVE — 74
  по severity:  CRITICAL 0 · HIGH 44 · MEDIUM 58 · LOW 58 · UNKNOWN 2
  уникальных HIGH CVE — всего 8: одна CVE util-linux «размножается» на bsdutils, libblkid1,
  libmount1, libuuid1, login, mount… — один исходный пакет, десяток бинарных
  по статусу:   affected 154 · fix_deferred 2 · fixed 6
  все 6 fixed — pip 25.0.1 (lang-pkgs), MEDIUM/LOW
Вывод: в слое ОС чинить нечего (фиксов нет), единственное действие — pip:
  обновить или вообще убрать из runtime-образа (multi-stage)
```text
Поля, которые нужны для триажа:

| Поле JSON | Смысл |
|-----------|-------|
| `Results[].Class` | `os-pkgs` — пакеты ОС (лечится базовым образом), `lang-pkgs` — зависимости приложения |
| `Results[].Target` | Что сканировали: образ с ОС или конкретный lock-файл/site-packages |
| `VulnerabilityID`, `PkgName`, `InstalledVersion` | Всегда заполнены |
| `FixedVersion` | Пусто — фикса нет |
| `Status` | `fixed` · `affected` (фикса пока нет) · `will_not_fix` · `fix_deferred` · `end_of_life` |
| `Severity`, `SeveritySource` | Итоговая оценка и чья она (`debian`, `nvd`, `ghsa`…) |
| `CVSS`, `VendorSeverity` | Оценки всех источников — видно расхождение NVD и дистрибутива |
| `PkgPath` | Для lang-pkgs: где лежит пакет в образе |

Рецепты `jq`:

```bash
# сколько находок по severity
jq -r '[.Results[].Vulnerabilities[]?] | group_by(.Severity) | map("\(.[0].Severity)\t\(length)")[]' report.json
# уникальные CVE (а не находки)
jq -r '[.Results[].Vulnerabilities[]?.VulnerabilityID] | unique | length' report.json
# только то, что можно починить прямо сейчас
jq -r '.Results[].Vulnerabilities[]? | select(.Status=="fixed")
  | [.VulnerabilityID,.PkgName,.InstalledVersion,.FixedVersion,.Severity] | @tsv' report.json
# ОС против зависимостей приложения
jq -r '.Results[] | "\(.Class)\t\(.Target)\t\((.Vulnerabilities // []) | length)"' report.json
# топ пакетов по числу находок
jq -r '[.Results[].Vulnerabilities[]?] | group_by(.PkgName)
  | map({p: .[0].PkgName, n: length}) | sort_by(-.n)[:10][] | "\(.n)\t\(.p)"' report.json
# CRITICAL/HIGH с источником оценки
jq -r '.Results[].Vulnerabilities[]? | select(.Severity|test("CRITICAL|HIGH"))
  | [.VulnerabilityID,.PkgName,.Status,.Severity,(.SeveritySource//"-")] | @tsv' report.json
```text
**Base image vs зависимости приложения:**

| Находка | Кто чинит | Как |
|---------|-----------|-----|
| `os-pkgs` с фиксом | Тот, кто владеет Dockerfile | Пересобрать с `--pull` / обновить digest базового образа |
| `os-pkgs` без фикса | Никто быстро | Меньший образ (slim → distroless), убрать лишние пакеты, ждать дистрибутив |
| `lang-pkgs` | Команда сервиса | Обновить зависимость в lock-файле (Renovate), убрать dev-зависимости из runtime |

`--ignore-unfixed` — сокращение для `--ignore-status affected,will_not_fix,fix_deferred,end_of_life`:
показывает только то, что можно починить. Для **gate** это разумно (нельзя требовать
невозможного), но в **отчёт/дашборд** отправляй всё: иначе не увидишь опасную
неисправленную уязвимость, для которой нужна компенсирующая мера.

---

## 6. «Не всё CRITICAL срочно»: разбор CVE-2023-45853

```text
debian:12-slim (Debian 12.15), Trivy 0.74.0, 27.09.2026:
  zlib1g 1:1.2.13.dfsg-1   CVE-2023-45853   CRITICAL   will_not_fix   SeveritySource=nvd (9.8)
```text
| Вопрос триажа | Ответ |
|---------------|-------|
| KEV? | Нет |
| EPSS? | 0.03179 на 26.09.2026 — низкая |
| Что уязвимо? | MiniZip — отдельный contrib-код в исходниках zlib, «not a supported part of zlib» |
| Достижимо? | Debian: `[bookworm] - zlib &lt;ignored&gt; (contrib/minizip not built…)` — **уязвимого кода нет в бинарном пакете** |
| Фикс? | В Debian 13 (trixie) исправлено; в bookworm чинить нечего |
| Решение | Not affected (`vulnerable_code_not_present`) через VEX или исключение со сроком до переезда на Debian 13 |

Контрпример — **CVE-2023-44487**: всего HIGH (7.5), но в KEV и EPSS ≈ 1. Если твой nginx/Ingress
терминирует HTTP/2 снаружи — это P0: обновить или ограничить HTTP/2 на краю
([03_web_edge_security.md](/security/03-web-edge-security)).

> ⭐ Приоритет = эксплуатируемость × достижимость × ценность актива. Severity из отчёта —
> только стартовая точка.

---

## 7. Исключения: `.trivyignore.yaml` со сроком и обоснованием

```yaml
# .trivyignore.yaml — формат помечен в Trivy как experimental; проверь доку своей версии
vulnerabilities:
  - id: CVE-2023-45853
    purls:
      - "pkg:deb/debian/zlib1g"          # сужаем: только этот пакет
    expired_at: 2027-03-31               # после даты правило перестаёт действовать
    statement: "MiniZip не собирается в bookworm (Debian &lt;ignored&gt;). Уйдём на trixie. SEC-142, владелец @nurik"
  - id: CVE-2026-9538
    paths:
      - "usr/lib/x86_64-linux-gnu/perl-base"   # или сузь через purls
    expired_at: 2026-10-31
    statement: "Фикса нет (fix_deferred). perl в runtime не вызывается. Пересмотр 31.10. SEC-150"
misconfigurations:
  - id: AVD-DS-0002
    paths: ["docker/debug.Dockerfile"]
    statement: "Отладочный образ, в прод не катится"
```text
```bash
eval $TRIVY image --scanners vuln --severity CRITICAL --exit-code 1 \
  --ignorefile .trivyignore.yaml --show-suppressed debian:12-slim
# ... в конце: «Suppressed Vulnerabilities» — ID, Statement и файл-источник
```text
Проверено: запись с `expired_at` в прошлом **не применяется** — находка возвращается в отчёт,
и gate снова краснеет. Это и есть механизм «исключение само напомнит о себе».

Старый текстовый формат тоже умеет срок: строка `CVE-2019-14697 exp:2023-01-01`.
YAML лучше: есть `statement`, `purls`, `paths`.

**Правила процесса:**
1. Каждое исключение — через MR, с ревью security-владельца (`CODEOWNERS` на файл).
2. `statement` = почему безопасно + тикет + владелец. «Accept the risk» без причины — отказ.
3. `expired_at` обязателен и не дальше 90 дней (или до конкретного события).
4. `--show-suppressed` в логе CI: исключения видны, а не спрятаны.
5. Раз в месяц — обзор: что истекает, что уже можно убрать.

**VEX** — машиночитаемое «мы не затронуты, потому что…», его можно публиковать вместе
с образом. Статусы OpenVEX: `not_affected`, `affected`, `fixed`, `under_investigation`;
для `not_affected` нужна `justification`: `component_not_present`,
`vulnerable_code_not_present`, `vulnerable_code_not_in_execute_path`,
`vulnerable_code_cannot_be_controlled_by_adversary`, `inline_mitigations_already_exist`.

```json
{
  "@context": "https://openvex.dev/ns/v0.2.0",
  "@id": "https://example.kz/vex/app-2026-001",
  "author": "platform-team",
  "timestamp": "2026-09-27T10:00:00Z",
  "version": 1,
  "statements": [{
    "vulnerability": {"name": "CVE-2023-45853"},
    "products": [{
      "@id": "pkg:oci/app?repository_url=registry.example.kz/team/app",
      "subcomponents": [{"@id": "pkg:deb/debian/zlib1g"}]
    }],
    "status": "not_affected",
    "justification": "vulnerable_code_not_present",
    "impact_statement": "contrib/minizip не собирается в Debian 12"
  }]
}
```text
```bash
eval $TRIVY image --vex vex.openvex.json registry.example.kz/team/app:1.4.2
```text
| | `.trivyignore.yaml` | VEX |
|---|---------------------|-----|
| Смысл | «Принимаем риск до даты» | «Уязвимость к продукту неприменима» — факт |
| Срок | `expired_at` | Нет (пересматривается при изменении продукта) |
| Кто читает | Только Trivy в твоём CI | Любой VEX-совместимый сканер, клиенты, аудиторы |

---

## 8. SLA на устранение

Пример политики (⚠️ **это пример** — сроки согласуют с бизнесом и регулятором):

| Приоритет | Условие | Срок | Как |
|-----------|---------|------|-----|
| **P0** | В KEV / активная эксплуатация, компонент достижим (особенно извне) | 24–72 часа | Emergency change; нет фикса — митигировать сразу |
| **P1** | CRITICAL + (эксплойт или EPSS высокий) + достижимо | 7 дней | Отдельный MR, внеплановый релиз |
| **P2** | CRITICAL/HIGH с фиксом, достижимо | 30 дней | Обычный релизный цикл |
| **P3** | Остальное с фиксом | 90 дней | Плановые обновления, Renovate |
| **—** | Фикса нет | Компенсирующие меры | Пересмотр каждые 30 дней |

- Часы идут с момента, когда **фикс доступен** и находка **обнаружена** — это прописывают.
- Просрочка SLA = исключение с подписью владельца риска, а не тишина.
- Регуляторы задают минимум: PCI DSS 4.0.1, требование 6.3.3 — патчи для критичных
  уязвимостей ставятся в течение месяца после выхода (проверь актуальную редакцию;
  подробнее о compliance — [07_security_incidents_compliance.md](/security/07-security-incidents-compliance)).

---

## 9. SBOM: знать, из чего состоит артефакт

Зачем: в день новой громкой CVE (xz в 2024, Log4Shell в 2021) вопрос «где у нас эта
библиотека?» решается запросом к SBOM за минуты, а не пересборкой всего за день.
Плюс лицензии и требования заказчиков/регуляторов.

| | CycloneDX | SPDX |
|---|-----------|------|
| Кто | OWASP | Linux Foundation, стандарт ISO/IEC 5962:2021 (SPDX 2.2.1) |
| Фокус | Безопасность, зависимости, VEX | Лицензии и происхождение |
| Когда брать | Сканеры, VEX, DevSecOps | Юристы, open source compliance |

```bash
# syft: сразу два формата
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD":/out anchore/syft:v1.52.0 \
  python:3.12-slim -o cyclonedx-json=/out/sbom.cdx.json -o spdx-json=/out/sbom.spdx.json
# trivy тоже умеет
eval $TRIVY image --format cyclonedx -o sbom-trivy.cdx.json python:3.12-slim

# через месяц: пересканировать SBOM новыми базами — образ скачивать не нужно
eval $TRIVY sbom sbom.cdx.json
grype sbom:./sbom.cdx.json            # grype покажет ещё и EPSS/KEV

# «есть ли у нас xz-utils и какой версии?»
jq -r '.components[] | select(.name|test("^xz|liblzma")) | "\(.name) \(.version)"' sbom.cdx.json

# привязать SBOM к образу подписанной аттестацией (cosign v3)
cosign attest --key cosign.key --type cyclonedx --predicate sbom.cdx.json registry.example.kz/team/app@sha256:…
cosign verify-attestation --key cosign.pub --type cyclonedx registry.example.kz/team/app@sha256:…
```text
Практика: SBOM — артефакт CI на **каждый digest** образа; хранится столько же, сколько
образ живёт в проде; `cosign attach sbom` устарел — используй аттестации.

---

## 10. Renovate/Dependabot и обновление базового образа

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:best-practices"],
  "timezone": "Asia/Almaty",
  "schedule": ["before 9am on monday"],
  "minimumReleaseAge": "3 days",
  "osvVulnerabilityAlerts": true,
  "packageRules": [
    { "matchUpdateTypes": ["patch", "digest", "pinDigest"], "automerge": true },
    { "matchDatasources": ["docker"], "matchPackageNames": ["python"], "groupName": "python base image" },
    { "matchUpdateTypes": ["major"], "dependencyDashboardApproval": true }
  ]
}
```text
- `config:best-practices` = `config:recommended` + `docker:pinDigests` +
  `helpers:pinGitHubActionDigests` + ещё несколько пресетов: Renovate сам пропишет digest
  к `FROM python:3.12-slim` и будет его обновлять.
- `minimumReleaseAge` — не брать версию моложе N дней: защита от «вредоносный релиз
  отозвали через сутки» (см. раздел 11).
- Automerge — только patch/digest и только при зелёном пайплайне со сканом.
- На GitLab Renovate запускают scheduled-пайплайном: проект-шаблон `renovate-bot/renovate-runner`,
  переменная `RENOVATE_TOKEN` (скоупы `read_user`, `api`, `write_repository`; protected + masked).
- Dependabot — встроенный аналог на GitHub (`.github/dependabot.yml`, `package-ecosystem: docker/pip/…`).

Процесс обновления базового образа:

```text
 FROM python:3.12-slim@sha256:&lt;digest&gt;     ← пин: сборка воспроизводима
        │  Renovate: MR «update python digest» (раз в неделю / при security-фиксе)
        ▼
 CI: build --pull → trivy (gate) → SBOM → push → deploy stage
        │
 cron раз в неделю: пересборка main без изменений кода (новые пакеты ОС)
 cron каждую ночь:  пересканировать образы, которые СЕЙЧАС в проде:
        kubectl get pods -A -o jsonpath='{..image}' | tr ' ' '\n' | sort -u
 метрика: «возраст базового образа» — дней с даты сборки базы (docker inspect .Created)
```text
---

## 11. Урок марта 2026: сканер как точка атаки

19–23 марта 2026 злоумышленники (TeamPCP) скомпрометировали экосистему Trivy
(advisory GHSA-69fq-xp46-6x23): вредоносные бинарники v0.69.4, образы Docker Hub **v0.69.5 и
v0.69.6**, перебиты 76 из 77 тегов `aquasecurity/trivy-action` и все 7 тегов `setup-trivy`.
Код читал память раннера через `/proc/&lt;pid&gt;/mem`, собирал SSH-ключи, облачные креды и
токены Kubernetes; запасной канал вывоза — публичный репозиторий `tpcp-docs`.

Кто в эти дни тянул `aquasec/trivy:latest` (как в примере из
[../CICD/13_quality_security.md](/cicd/13-quality-security) — там `latest` ради простоты),
мог получить заражённый образ, **ничего не меняя в своём пайплайне**.

| Мера | Как |
|------|-----|
| ⭐ Пин по digest даже для инструментов безопасности | `aquasec/trivy:0.74.0@sha256:…`, actions — по полному SHA коммита |
| Зеркало в свой registry | CI тянет только из своего registry, обновление — осознанным MR |
| Задержка новых версий | `minimumReleaseAge` в Renovate |
| Минимум секретов у scan-джоб | Скан — в отдельной стадии без protected-переменных и deploy-токенов |
| Готовность к ротации | Инвентарь секретов, доступных пайплайну ([../Project/08_secrets_security.md](/project/08-secrets-security)) |
| Если затронут | Обновиться на безопасную версию, **ротировать всё**, что видел раннер, искать `tpcp-docs` в своей организации |

---

## 12. Метрики программы

| Метрика | Зачем |
|---------|-------|
| MTTR по приоритетам (P0…P3) | Укладываемся ли в SLA |
| % находок, закрытых в SLA | Главный KPI для руководства и аудита |
| Открытые P0/P1 прямо сейчас | Сигнал на дежурство, не на квартальный отчёт |
| Активные исключения и истекшие | Растёт — процесс превращается в «игнорируем всё» |
| % прод-образов с базой старше 30 дней | Работает ли автоматическое обновление |
| Покрытие: % прод-образов со SBOM и сканом за 24 ч | Не слепые ли мы |

> Считать «число CVE» бессмысленно: 162 находки в `python:3.12-slim` — это 74 CVE, из которых
> действие требуется для одной зависимости.

---

## 13. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Gate на все HIGH, включая без фикса | Пайплайн красный всегда, команда перестаёт смотреть | Gate: CRITICAL с фиксом (+ KEV), остальное — в отчёт |
| Исключение без срока и причины | Через год никто не помнит, почему | `expired_at` + `statement` с тикетом и владельцем |
| `aquasec/trivy:latest`, actions по тегу | Март 2026: заражённый сканер крадёт секреты | Digest / SHA, своё зеркало |
| Скан только при сборке | Новые CVE появляются в уже выкаченных образах | Ночной рескан прод-образов или SBOM |
| Считать находки вместо CVE и риска | Паника из-за «162 уязвимостей» | Уникальные CVE, статус, достижимость |
| Верить NVD больше дистрибутива | Лишние CRITICAL в пакетах ОС | Смотреть `SeveritySource` и трекер дистрибутива |
| `--ignore-unfixed` везде | Не видно опасных неисправленных | В gate — да, в отчёте — нет |
| pip/компиляторы в runtime-образе | Лишние находки и поверхность атаки | Multi-stage, slim/distroless |
| Automerge мажорных версий | Сломанный прод по расписанию | Automerge только patch/digest при зелёных тестах |
| SLA без точки отсчёта | Споры «когда пошли часы» | От момента обнаружения при доступном фиксе |

---

## 💼 Как это в DevOps

- Девопс строит конвейер: скан в CI, ночной рескан, SBOM, Renovate, дашборд; решение
  по конкретной CVE принимают вместе с владельцем сервиса.
- Типичная неделя: Renovate-MR с новым digest базы → зелёный скан → automerge; две
  находки в зависимостях — тикеты командам с датой по SLA.
- На вопрос аудитора «как вы управляете уязвимостями?» отвечают политикой (SLA по
  приоритетам), доказательствами (отчёты, MTTR) и процессом исключений.
- В день громкой CVE девопс за 15 минут отвечает «где у нас это есть» — по SBOM и
  списку образов из кластера, а не по памяти.
- Инструменты безопасности — такой же supply chain: их тоже пинят, зеркалируют и
  ограничивают в правах.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Скан образа в JSON | `trivy image --scanners vuln --format json -o r.json IMG` |
| Только починяемое | `--ignore-unfixed` (= `--ignore-status affected,will_not_fix,fix_deferred,end_of_life`) |
| Gate | `--severity CRITICAL --exit-code 1` |
| Исключения со сроком | `.trivyignore.yaml`: `id`, `purls`/`paths`, `expired_at`, `statement` + `--ignorefile` |
| Показать подавленное | `--show-suppressed` |
| Учесть VEX | `trivy image --vex vex.json IMG` |
| Уникальные CVE | `jq '[.Results[].Vulnerabilities[]?.VulnerabilityID] \| unique \| length'` |
| EPSS | `curl -s "https://api.first.org/data/v1/epss?cve=CVE-…"` |
| KEV | JSON-фид CISA + `jq 'select(.cveID==…)'` |
| SBOM | `syft IMG -o cyclonedx-json=sbom.cdx.json` / `trivy image --format cyclonedx` |
| Рескан SBOM | `trivy sbom sbom.cdx.json` / `grype sbom:./sbom.cdx.json` |
| Аттестация SBOM | `cosign attest --key k --type cyclonedx --predicate sbom.cdx.json IMG@sha256:…` |
| Пин образа | `FROM image:tag@sha256:…` + Renovate `config:best-practices` |
| Образы в проде | `kubectl get pods -A -o jsonpath='{..image}'` |

---

## 🧠 Что запомнить

1. CVSS base — свойство уязвимости, а не твой риск; читай вектор (AV, PR, UI) и контекст.
2. EPSS — вероятность эксплуатации за 30 дней, KEV — факт эксплуатации; оба — сигналы для приоритета.
3. HIGH из KEV срочнее CRITICAL без эксплойта; CRITICAL без достижимости может быть not_affected.
4. Триаж: KEV/эксплойт → достижимость → наличие фикса → решение, и решение записано.
5. Для пакетов ОС правда у дистрибутива: смотри `Status` и `SeveritySource`, а не только severity.
6. Находки ≠ CVE ≠ риск: одна CVE util-linux дала десять строк в отчёте.
7. Исключение без `expired_at` и `statement` — это не исключение, а забытая дыра.
8. SLA по приоритетам с точкой отсчёта; PCI DSS 4.0.1 требует критичные патчи за месяц.
9. SBOM на каждый digest — ответ на «где у нас X» за минуты; рескан SBOM без пересборки.
10. Сканер — тоже supply chain: пин по digest/SHA, зеркало, минимум секретов (урок марта 2026).

➡️ Дальше: [05_iam_access.md](/security/05-iam-access) · задачи: 04_vuln_management_tasks.md


---

### Блок A. Теория


**A1.** Чем CVE отличается от CWE и GHSA? Кто выдаёт CVE ID?

<details><summary>Ответ</summary>

CVE — идентификатор конкретной уязвимости в конкретном продукте; CWE — класс слабости
(тип ошибки: SQLi, out-of-bounds write); GHSA — advisory GitHub для пакетов экосистем
(npm, PyPI, Go…), часто со ссылкой на CVE. CVE выдают CNA — вендоры, дистрибутивы, GitHub, MITRE.

</details>

**A2.** ⭐ Почему для пакетов ОС severity лучше брать у дистрибутива, а не в NVD? Что показывает
поле `SeveritySource` в отчёте Trivy?

<details><summary>Ответ</summary>

Дистрибутив знает свою сборку: патчи-бэкпорты, отключённые при сборке модули (как MiniZip
в Debian 12). NVD оценивает «в вакууме». `SeveritySource` показывает, чья оценка стала итоговой
(`debian`, `ubuntu`, `nvd`, `ghsa`).

</details>

**A3.** Расшифруй вектор `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`.

<details><summary>Ответ</summary>

Эксплуатируется по сети (AV:N), без особых условий (AC:L), без привилегий (PR:N), без
действий жертвы (UI:N), не выходит за компонент (S:U), полное влияние на конфиденциальность,
целостность и доступность (C/I/A:H) — 9.8 CRITICAL.

</details>

**A4.** Что изменилось в CVSS v4.0 по сравнению с v3.1? Что значит пометка `CVSS-BT`?

<details><summary>Ответ</summary>

Группы Base, Threat, Environmental, Supplemental; новая метрика AT (Attack Requirements);
UI стало N/P/A; вместо Scope — отдельные последствия для уязвимой (VC/VI/VA) и последующих
(SC/SI/SA) систем; Threat-метрика E (X/A/P/U). `CVSS-BT` — оценка учитывает Base и Threat.

</details>

**A5.** ⭐ Почему base score — не твой риск? Какие группы метрик приближают оценку к реальности?

<details><summary>Ответ</summary>

Base описывает уязвимость без контекста: не знает, загружается ли пакет, торчит ли сервис
наружу, есть ли эксплойт. Ближе к реальности — Threat (v4)/Temporal (v3.1: зрелость эксплойта)
и Environmental (требования к C/I/A и modified-метрики твоего окружения).

</details>

**A6.** Чем EPSS отличается от CISA KEV? Почему ни один из них не вердикт?

<details><summary>Ответ</summary>

EPSS — вероятность эксплуатации в ближайшие 30 дней (модель FIRST, ежедневно); KEV —
каталог CISA уже эксплуатируемых уязвимостей (факт). KEV неполный (regreSSHion там нет при EPSS ≈ 1),
EPSS не знает твою архитектуру — нужен триаж достижимости.

</details>

**A7.** ⭐ Опиши алгоритм триажа находки по шагам.

<details><summary>Ответ</summary>

1) KEV / публичный эксплойт / высокий EPSS? 2) Достижимо у нас? 3) Есть fixed version?

</details>

**A8.** Какие вопросы задают, чтобы понять, достижима ли уязвимость?

<details><summary>Ответ</summary>

Есть ли пакет в runtime-образе, а не только в build-стадии; загружает ли его процесс;
обрабатывает ли компонент недоверенный ввод или слушает сеть; используется ли уязвимая функция;
для AV:L — есть ли у атакующего shell (distroless, read-only, non-root снижают).

</details>

**A9.** Какие пять решений по находке бывают и где каждое фиксируется?

<details><summary>Ответ</summary>

Fix now — emergency change; fix in SLA — тикет с дедлайном/Renovate MR; mitigate — тикет
с компенсирующей мерой и пересмотром; accept — `.trivyignore.yaml` со сроком, причиной и владельцем;
not affected — VEX-документ.

</details>

**A10.** Чем находки класса `os-pkgs` отличаются от `lang-pkgs`? Кто и как их чинит?

<details><summary>Ответ</summary>

`os-pkgs` — пакеты дистрибутива в образе, лечатся обновлением базового образа
(пересборка с `--pull`, новый digest) или его сменой; чинит владелец Dockerfile/платформа.
`lang-pkgs` — зависимости приложения, лечатся обновлением lock-файла; чинит команда сервиса.

</details>

**A11.** Что делает `--ignore-unfixed`? Где его стоит включать, а где нет?

<details><summary>Ответ</summary>

Скрывает находки без фикса (статусы affected, will_not_fix, fix_deferred, end_of_life).
В gate — да: нельзя требовать невозможного. В отчётах и дашбордах — нет: иначе не увидишь опасную
неисправленную уязвимость, которой нужна компенсирующая мера.

</details>

**A12.** ⭐ Какие поля есть у записи в `.trivyignore.yaml`? Что происходит после даты `expired_at`?

<details><summary>Ответ</summary>

`id` (обязательно), `paths`, `purls` (только для уязвимостей), `expired_at` (дата),
`statement` (причина, не участвует в фильтрации). После `expired_at` правило не применяется:
находка возвращается в отчёт, и gate снова падает.

</details>

**A13.** Чем VEX отличается от `.trivyignore.yaml`? Назови статусы OpenVEX.

<details><summary>Ответ</summary>

`.trivyignore.yaml` — локальное «принимаем риск до даты» для твоего CI. VEX —
машиночитаемое утверждение «продукт не затронут, потому что…», которое читают любые совместимые
сканеры, клиенты и аудиторы. Статусы: `not_affected`, `affected`, `fixed`, `under_investigation`.

</details>

**A14.** Как устроен пример SLA по приоритетам? С какого момента идут часы? Что требует
PCI DSS 4.0.1 в 6.3.3?

<details><summary>Ответ</summary>

P0 (KEV/эксплуатация + достижимо) — 24–72 часа; P1 (CRITICAL + эксплойт/EPSS + достижимо) —

</details>

**A15.** Зачем SBOM, если есть сканер? Чем CycloneDX отличается от SPDX?

<details><summary>Ответ</summary>

Сканер отвечает «что уязвимо сейчас»; SBOM — «из чего состоит артефакт», и на него можно
пересканировать уже выпущенные образы и за минуты ответить «где у нас X» в день громкой CVE;
плюс лицензии и требования заказчиков. CycloneDX (OWASP) — фокус на безопасности и VEX;
SPDX (Linux Foundation, ISO/IEC 5962) — на лицензиях и происхождении.

</details>

**A16.** ⭐ Чему научила компрометация Trivy в марте 2026? Какие меры защищают конвейер от
заражённого инструмента?

<details><summary>Ответ</summary>

Инструмент безопасности — тоже часть supply chain: в марте 2026 заражённые образы
Trivy и перебитые теги trivy-action крали секреты раннеров у тех, кто тянул `latest`/теги. Меры:
пин по digest и по SHA коммита, своё зеркало, `minimumReleaseAge`, scan-джоба без
protected-переменных и deploy-токенов, инвентарь секретов для быстрой ротации.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # .trivyignore.yaml
```text
<details><summary>Ответ</summary>

⚠️ Нет срока, нет причины, нет сужения по пакету — и это regreSSHion с EPSS ≈ 0,995.
Исключение без `expired_at` и нормального `statement` — забытая дыра. Здесь — обновить OpenSSH
или убрать sshd из образа.

</details>

```text:no-line-numbers
     vulnerabilities:
```text
```text:no-line-numbers
       - id: CVE-2024-6387
```text
```text:no-line-numbers
         statement: Accept the risk
```text
```text:no-line-numbers
B2.  # gate в CI
```text
<details><summary>Ответ</summary>

⚠️ Gate по HIGH без `--ignore-unfixed` требует невозможного: у пакетов ОС фиксов нет,
команда перестаёт смотреть на красный. Gate: CRITICAL с фиксом (+ KEV), остальное — в отчёт.

</details>

```text:no-line-numbers
     trivy image --severity HIGH,CRITICAL --exit-code 1 app:$CI_COMMIT_SHORT_SHA
```text
```text:no-line-numbers
     # базовый образ python:3.12-slim, пайплайн красный третью неделю
```text
```text:no-line-numbers
B3.  scan:image:
```text
<details><summary>Ответ</summary>

⚠️ Образ сканера `latest` без digest (март 2026) и прод-kubeconfig в той же джобе:
заражённый сканер унесёт доступ к проду. Пин по digest, скан — отдельная стадия без deploy-секретов.

</details>

```text:no-line-numbers
       image: {name: aquasec/trivy:latest, entrypoint: [""]}
```text
```text:no-line-numbers
       variables:
```text
```text:no-line-numbers
         KUBECONFIG_PROD: $KUBECONFIG_PROD      # «чтобы потом сразу задеплоить»
```text
```text:no-line-numbers
       script: [trivy image --exit-code 1 --severity CRITICAL $IMAGE]
```text
```text:no-line-numbers
B4.  # решение на планёрке
```text
<details><summary>Ответ</summary>

⚠️ Не проведён триаж: KEV нет, EPSS ≈ 0,03, а в Debian 12 MiniZip даже не собирается
(`&lt;ignored&gt;`). Решение — not affected через VEX или исключение со сроком до переезда на Debian 13.

</details>

```text:no-line-numbers
     «CVE-2023-45853 в zlib1g, CRITICAL 9.8 — стоп всех релизов до фикса.»
```text
```text:no-line-numbers
     # образы на debian:12-slim
```text
```text:no-line-numbers
B5.  # отчёт по образу публичного nginx-ingress
```text
<details><summary>Ответ</summary>

⚠️ HIGH, но в KEV и EPSS ≈ 1, компонент торчит в интернет — это P0. Обновить
ingress/nginx немедленно или ограничить HTTP/2 на краю.

</details>

```text:no-line-numbers
     CVE-2023-44487  HIGH 7.5  → «не CRITICAL, берём в плановые 90 дней»
```text
```text:no-line-numbers
B6.  # письмо руководству
```text
<details><summary>Ответ</summary>

⚠️ Находки ≠ CVE ≠ риск: 162 строки — это 74 уникальных CVE, одна CVE util-linux даёт
десяток строк, почти все без фикса. Сообщать уникальные CVE, статусы и что требует действий.

</details>

```text:no-line-numbers
     «В образе python:3.12-slim найдено 162 уязвимости!»
```text
```text:no-line-numbers
B7.  // renovate.json
```text
<details><summary>Ответ</summary>

⚠️ Automerge мажорных и минорных версий по расписанию — сломанный прод без человека.
Automerge только patch/digest при зелёном пайплайне, мажорные — через одобрение.

</details>

```text:no-line-numbers
     { "extends": ["config:recommended"],
```text
```text:no-line-numbers
       "packageRules": [{ "matchUpdateTypes": ["major","minor","patch"], "automerge": true }] }
```text
```text:no-line-numbers
B8.  # образ собран и просканирован 8 месяцев назад, с тех пор крутится в проде без изменений
```text
<details><summary>Ответ</summary>

⚠️ Новые CVE появились за 8 месяцев, а образ никто не сканирует. Ночной рескан образов
из кластера или SBOM, регулярная пересборка.

</details>

```text:no-line-numbers
B9.  # Dockerfile
```text
<details><summary>Ответ</summary>

⚠️ Тег `3.12-slim` плавающий: сегодня и через месяц это разные образы. Воспроизводимость —
`FROM python:3.12-slim@sha256:…` + Renovate для обновления digest.

</details>

```text:no-line-numbers
     FROM python:3.12-slim
```text
```text:no-line-numbers
     # «сборка воспроизводима, у нас же тег версии»
```text
```text:no-line-numbers
B10.  # дашборд уязвимостей для security-команды
```text
<details><summary>Ответ</summary>

⚠️ В дашборде не видно находок без фикса — именно тех, где нужны компенсирующие меры.
Для отчётов — полный скан.

</details>

```text:no-line-numbers
     trivy image --ignore-unfixed --format json …
```text
```text:no-line-numbers
B11.  - id: CVE-2026-9538
```text
<details><summary>Ответ</summary>

⚠️ Срок на 3+ года — фактически бессрочно; нет владельца, тикета и объяснения, почему
безопасно. Срок ≤ 90 дней или до события, `statement` = почему безопасно + тикет + владелец.

</details>

```text:no-line-numbers
       expired_at: 2030-01-01
```text
```text:no-line-numbers
       statement: "фикса нет"
```text
```text:no-line-numbers
B12.  # политика: «Critical — 7 дней». Команда: «Фикс вышел месяц назад, но мы узнали вчера —
```text
<details><summary>Ответ</summary>

⚠️ Точка отсчёта не определена. Политика должна прямо сказать: «от момента обнаружения
при доступном фиксе» (и какой автоматикой обнаружение фиксируется — например, ночной скан).

</details>

```text:no-line-numbers
     # у нас ещё 6 дней». Безопасность: «Просрочено на 3 недели».
```text
---

### Блок C. Практика


### C1. 🔑 Разобрать настоящий отчёт
Просканируй `python:3.12-slim` в JSON. Ответь через `jq`: сколько находок по severity;
сколько **уникальных** CVE; что можно починить прямо сейчас (`Status=="fixed"`); как делятся
находки между `os-pkgs` и `lang-pkgs`; топ-5 пакетов по числу находок. Сформулируй одной фразой:
«что реально нужно сделать с этим образом».

### C2. 🔑 Обогатить отчёт EPSS и KEV
Напиши скрипт `enrich.sh report.json`: берёт уникальные CVE, запрашивает EPSS пачками
(до ~50 CVE на запрос), скачивает KEV и печатает таблицу `CVE · пакет · severity · status ·
EPSS · в KEV?`, отсортированную по EPSS.

### C3. 🔑 Триаж пяти находок
Возьми из отчёта C1 (и из скана `debian:12-slim`) пять находок, включая CVE-2023-45853. Для каждой
пройди алгоритм раздела 4: KEV/EPSS → достижимость → фикс → решение, и запиши, где решение
будет зафиксировано.

### C4. 🔑 Исключение со сроком
Создай `.trivyignore.yaml` для CVE-2023-45853 (с `purls`, `expired_at`, `statement` с тикетом
и владельцем). Запусти gate на `debian:12-slim` с `--ignorefile` и `--show-suppressed`.
Затем поставь `expired_at` в прошлое и докажи, что находка вернулась и gate упал.

### C5. SBOM и рескан
Сделай SBOM образа из `ci/` в CycloneDX и SPDX через syft и CycloneDX через Trivy. Найди в SBOM
версии `openssl` и `pip` через `jq`. Пересканируй SBOM (`trivy sbom`) и сравни с прямым сканом образа.

### C6. VEX вместо исключения
Напиши OpenVEX-документ `not_affected` / `vulnerable_code_not_present` для CVE-2023-45853 и
проверь `trivy image --vex vex.openvex.json debian:12-slim`. Когда VEX лучше `.trivyignore.yaml`?

### C7. Renovate для демо-репо
Положи `renovate.json` из раздела 10 в `ci/`. Объясни каждую строку. Какой вид примет строка
`FROM` после первого MR от Renovate и почему automerge разрешён только для patch/digest?

### C8. SLA-политика на одну страницу
Напиши `docs/vuln-sla.md` для своего проекта: приоритеты P0–P3 с условиями, сроки, точка отсчёта,
что делать без фикса, как оформляется просрочка, кто владелец риска, какие метрики считаем.

### C9. Пин сканера по digest
Узнай digest `aquasec/trivy:0.74.0` (`docker buildx imagetools inspect` или
`docker inspect --format '&#123;&#123;index .RepoDigests 0&#125;&#125;'` после pull) и перепиши job `scan:image`
из [../CICD/13_quality_security.md](/cicd/13-quality-security) с пином, отдельной стадией без
deploy-переменных и `--show-suppressed`.

---

### Блок D. Инциденты


**D1.** Понедельник: в базовом образе появилась CRITICAL без фикса, gate блокирует все релизы,
включая срочный багфикс.

<details><summary>Ответ</summary>

Триаж находки (KEV/EPSS/достижимость). Если не P0 — исключение со сроком и тикетом
через MR с ревью security-владельца, релиз идёт; если P0 без фикса — компенсирующие меры
(убрать пакет, сменить базу, WAF/NetworkPolicy) и решение о релизе с владельцем риска.
Урок: gate блокирует только то, что можно починить.

</details>

**D2.** Утром в новостях — новая CVE в OpenSSH, уже в KEV. Руководитель спрашивает «где у нас это
и когда закроем?».

<details><summary>Ответ</summary>

За минуты: список образов в проде (`kubectl get pods -A -o jsonpath='{..image}'`) и
запрос по SBOM (`jq` по `openssh`), плюс инвентарь ВМ (Ansible `package_facts`). Приоритет P0
(KEV) для всего, где sshd достижим; обновить пакеты/образы, ограничить доступ к 22 до патча;
сообщить план и ETA.

</details>

**D3.** В CI-логах scan-джобы появились странные исходящие соединения и чтение `/proc/*/mem`;
вы используете `aquasec/trivy:latest`.

<details><summary>Ответ</summary>

Считать компрометацией: остановить джобы, зафиксировать версию/digest образа, ротировать
все секреты, доступные раннеру (CI-переменные, токены registry/облака/k8s), проверить
организацию на `tpcp-docs`-подобные репозитории и аудит-логи на использование ключей,
перейти на пин по digest и своё зеркало (см. тему 07).

</details>

**D4.** В пятницу вечером истекли 12 исключений в `.trivyignore.yaml` — все пайплайны красные,
горит релиз.

<details><summary>Ответ</summary>

Не удалять исключения пачкой «чтобы позеленело». Для каждой — быстрый триаж: можно ли
уже починить (часто да — фикс вышел), иначе продлить через MR с ревью и новым сроком. Урок:
ежемесячный обзор исключений и алерт за 2 недели до `expired_at`.

</details>

**D5.** Аудитор: «Покажите, как вы управляете уязвимостями, и докажите, что критичные
закрываются вовремя».

<details><summary>Ответ</summary>

Политика SLA, отчёты сканов за период, метрики MTTR и % закрытых в SLA, журнал
исключений с владельцами и сроками (git-история `.trivyignore.yaml`), SBOM прод-образов,
Renovate-MR как доказательство регулярных обновлений.

</details>

**D6.** Renovate смёржил обновление digest базового образа ночью, утром часть подов падает на старте.

<details><summary>Ответ</summary>

Откатить digest (revert MR), посмотреть changelog/diff базового образа (изменились
библиотеки, пользователь, путь). Урок: automerge только при прохождении smoke/интеграционных
тестов, канареечный деплой, `minimumReleaseAge`.

</details>

**D7.** Разработчик в MR добавил в `.trivyignore` строку `CVE-2025-XXXX`, чтобы пайплайн позеленел.
Ревьюер — ты.

<details><summary>Ответ</summary>

Не принимать: нет срока, причины, тикета и владельца, нет триажа. Попросить формат
`.trivyignore.yaml` с `purls`, `expired_at` ≤ 90 дней и `statement`, или починить (часто
достаточно обновить зависимость). `CODEOWNERS` на файл исключений.

</details>

**D8.** Grype показывает CRITICAL, которого нет в отчёте Trivy по тому же образу, а у общей CVE —
разная severity.

<details><summary>Ответ</summary>

Разные сканеры используют разные базы и логику сопоставления пакетов (vendor vs NVD,
разные каталогизаторы). Проверить по трекеру дистрибутива и GHSA, какая оценка авторитетна
(`SeveritySource`), и достижима ли уязвимость. Выбрать один инструмент для gate, второй — для
перекрёстной проверки.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Пайплайн красный от сотни уязвимостей в базовом образе. Что будешь делать?

<details><summary>Ответ</summary>

Триаж вместо паники: уникальные CVE, статус (есть ли фикс), KEV/EPSS, достижимость, класс
   (ОС или зависимости). Gate — на CRITICAL с фиксом и KEV, остальное — в отчёт; пересобрать
   с актуальной базой, убрать лишнее (multi-stage, slim/distroless), исключения — со сроком.

</details>

**2.** Что такое CVSS? Почему нельзя приоритизировать только по нему?

<details><summary>Ответ</summary>

Стандарт оценки тяжести уязвимости (v3.1, v4.0). Base score не знает контекста: эксплойта,
   достижимости, ценности актива; HIGH из KEV срочнее CRITICAL без эксплойта.

</details>

**3.** Что такое EPSS и CISA KEV?

<details><summary>Ответ</summary>

EPSS — вероятность эксплуатации за 30 дней от FIRST; KEV — каталог CISA уже эксплуатируемых CVE.
   Используются как сигналы приоритета.

</details>

**4.** Как устроен процесс исключений для сканера?

<details><summary>Ответ</summary>

`.trivyignore.yaml` в git: `id`, сужение по `purls`/`paths`, `expired_at` ≤ 90 дней,
   `statement` с причиной, тикетом и владельцем; MR с ревью (CODEOWNERS), `--show-suppressed`,
   ежемесячный обзор; факты «не затронуты» — VEX.

</details>

**5.** Что такое SBOM и зачем он нужен?

<details><summary>Ответ</summary>

Перечень компонентов артефакта (CycloneDX/SPDX), генерируется в CI на каждый digest; позволяет
   пересканировать выпущенное и за минуты найти «где у нас X».

</details>

**6.** Как организовать обновление базовых образов?

<details><summary>Ответ</summary>

`FROM …@sha256:` + Renovate MR с новым digest, еженедельная пересборка без изменений кода,
   ночной рескан прод-образов, метрика возраста базового образа, automerge patch/digest при зелёном скане.

</details>

**7.** Какие SLA на устранение уязвимостей ты бы предложил?

<details><summary>Ответ</summary>

P0 (KEV/эксплуатация) — 24–72 часа, P1 — 7 дней, P2 — 30, P3 — 90, без фикса — компенсация;
   точка отсчёта — обнаружение при доступном фиксе; с оглядкой на регулятора (PCI 6.3.3 — месяц).

</details>

**8.** Чем отличается уязвимость в пакете ОС от уязвимости в зависимости приложения?

<details><summary>Ответ</summary>

ОС — чинится обновлением/сменой базового образа, часто фиксов нет, severity у дистрибутива;
   зависимости — обновлением lock-файла командой сервиса.

</details>

**9.** Что такое VEX?

<details><summary>Ответ</summary>

Машиночитаемое заявление о применимости уязвимости к продукту: `not_affected` с обоснованием,
   `affected`, `fixed`, `under_investigation`; Trivy учитывает через `--vex`.

</details>

**10.** Как защитить сам конвейер сканирования от атаки на цепочку поставки?

<details><summary>Ответ</summary>

Пин по digest/SHA, своё зеркало, `minimumReleaseAge`, минимум секретов у scan-джоб, проверка
    подписей инструментов, готовность ротировать — урок компрометации Trivy в марте 2026.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Читаю вектор CVSS v3.1/v4.0 и объясняю, почему base score — не риск
- [ ] ⭐ Проверяю CVE по EPSS и KEV скриптом, а не вручную
- [ ] ⭐ Триажу находку: KEV/EPSS → достижимость → фикс → решение, решение записано
- [ ] Разбираю JSON Trivy через `jq`: уникальные CVE, статусы, ОС vs зависимости
- [ ] Пишу `.trivyignore.yaml` со сроком и обоснованием и доказал, что срок работает
- [ ] Знаю разницу исключения и VEX, написал OpenVEX-документ
- [ ] Генерирую SBOM в CycloneDX/SPDX и пересканирую его без пересборки
- [ ] Renovate пинит digest базового образа, automerge только patch/digest
- [ ] Сканер в CI запинен по digest и не видит deploy-секретов
