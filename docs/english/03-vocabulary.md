---
title: "03. Лексика: глоссарий DevOps, фразовые глаголы, ложные друзья, произношение"
description: "Блок → Английский для IT → тема 03. Опирается на 01levelandsystem.md"
---

# 03. Лексика: глоссарий DevOps, фразовые глаголы, ложные друзья, произношение

> Блок → Английский для IT → тема 03. Опирается на [01_level_and_system.md](/english/01-level-and-system)
> (как вести свои слова в Anki) и [02_reading_docs.md](/english/02-reading-docs) (фразы
> документации). Здесь — слова, на которых держатся созвоны, чаты и инциденты.
> Термины инцидентов по существу — в [../../DevOps/SRE/04_incident_management.md](/sre/04-incident-management).
>
> **После темы ты умеешь:** понимать и использовать рабочую лексику по областям (инфра,
> CI/CD, инциденты, встречи); уверенно использовать фразовые глаголы IT (*spin up*,
> *roll back*, *look into*); писать слитно или раздельно *setup / set up*, *backup / back up*;
> не попадаться на ложных друзей переводчика (*actual*, *accurate*, *realize*,
> *exploitation*); произносить названия инструментов так, чтобы тебя понимали.

---

## 🗺️ Карта темы

```text
 ПАССИВНЫЙ СЛОВАРЬ  ──────────────────────►  АКТИВНЫЙ СЛОВАРЬ
 узнаёшь при чтении                           используешь сам в речи и письме
        │                                            ▲
        │   сочетания, а не слова:                   │
        │   mitigate the impact · file an issue      │
        ▼                                            │
 ┌───────────────┬─────────────┬────────────────┬──────────────┐
 │ глоссарий по  │ фразовые    │ ложные друзья  │ произношение │
 │ областям      │ глаголы     │ actual, realize│ nginx, cache │
 │ infra, CI/CD, │ spin up,    │ exploitation   │ etcd, Azure  │
 │ incidents,    │ roll back,  │ control        │ + ударения:  │
 │ meetings      │ look into   │                │ deVELop      │
 └───────────────┴─────────────┴────────────────┴──────────────┘
```text
---

## 1. Как учить лексику

- **Пассивный словарь** — слова, которые узнаёшь. **Активный** — которые сам вспоминаешь
  в разговоре. У айтишника пассивный обычно в разы больше. Цель — перевести рабочие слова
  в активный.
- **Сочетания, а не слова.** Носители говорят блоками: *file an issue*, *roll out
  a change*, *mitigate the impact*, *take a look*. Выучив блок, не надо гадать, какой
  глагол подходит.
- **Слово — из своего контекста.** Таблицы ниже — карта, а не список для зубрёжки:
  в Anki берёшь только то, что встретил в работе ([01_level_and_system.md](/english/01-level-and-system), раздел 7).
- **Сразу использовать.** Новое слово — в сегодняшнем сообщении, коммите или записи
  стендапа. Использованное один раз запоминается лучше десяти повторений карточки.

---

## 2. Глоссарий по областям

### Инфраструктура и эксплуатация

| Термин | Значение | 🇬🇧 В предложении |
|--------|----------|-------------------|
| provision | Выделить и подготовить ресурс | *Terraform provisions three VMs.* |
| deploy / deployment | Развернуть / развёртывание | *We deploy twice a day.* |
| scale out / scale in | Добавить / убрать экземпляры | *The service scales out to 10 pods at peak.* |
| scale up / scale down | Больше / меньше ресурсов или реплик | *Scale the deployment down to zero.* |
| workload | Приложение, которое крутится в кластере | *Stateful workloads need persistent volumes.* |
| throughput | Пропускная способность | *Throughput dropped to 200 RPS.* |
| latency | Задержка | *p99 latency is 300 ms.* |
| uptime / downtime | Время работы / простоя | *The migration requires no downtime.* |
| capacity | Ёмкость, запас | *We're running out of capacity.* |
| bottleneck | Узкое место | *The database is the bottleneck.* |
| overhead | Накладные расходы | *The sidecar adds some latency overhead.* |
| footprint | Сколько ресурсов занимает | *The new image has a smaller memory footprint.* |
| redundancy | Резервирование | *We have no redundancy for the load balancer.* |
| failover | Переключение на резерв | *Failover took 30 seconds.* |
| high availability (HA) | Высокая доступность | *Run etcd in HA mode with three members.* |
| drift | Расхождение реального состояния с кодом | *`terraform plan` shows drift in the security group.* |
| toil | Ручная повторяющаяся работа | *Automating cert renewal removed a lot of toil.* |
| decommission | Вывести из эксплуатации | *We'll decommission the old cluster next month.* |

### CI/CD и релизы

| Термин | Значение | 🇬🇧 В предложении |
|--------|----------|-------------------|
| pipeline, stage, job | Пайплайн, стадия, задача | *The `test` stage has three jobs.* |
| runner / agent | Машина, которая выполняет джобы | *The runner ran out of disk space.* |
| artifact | Результат сборки | *The image is the main build artifact.* |
| green / red build | Сборка прошла / упала | *Main is red — don't merge.* |
| flaky test | Нестабильный тест: то проходит, то падает | *It's a flaky test; rerun the job.* |
| release candidate (RC) | Кандидат в релиз | *v2.0.0-rc.1 is on staging.* |
| rollout | Выкатка | *The rollout is 50% done.* |
| canary release | Выкатка на малую часть трафика | *5% of traffic goes to the canary.* |
| blue-green deployment | Две копии окружения, переключение трафика | *Blue-green makes rollback instant.* |
| feature flag | Флаг, которым включают фичу без деплоя | *The new checkout is behind a feature flag.* |
| gate, approval | Ручное подтверждение перед шагом | *Prod deploys need a manual approval.* |
| promote | Продвинуть артефакт в следующее окружение | *Promote the image from staging to prod.* |
| pin / bump a version | Зафиксировать / поднять версию | *Pin the base image; bump the chart version.* |
| cache hit / miss | Попадание / промах кэша | *Every new branch was a cache miss.* |

### Инциденты и надёжность

| Термин | Значение | 🇬🇧 В предложении |
|--------|----------|-------------------|
| outage | Отказ, сервис недоступен | *A 40-minute outage of the payment API.* |
| degradation | Частичная деградация | *We see degraded performance in checkout.* |
| page / get paged | Вызвать дежурного / тебя вызвали | *I got paged at 3 am.* |
| on-call | Дежурство, дежурный | *I'm on call this week.* |
| acknowledge (ack) | Подтвердить, что взял алерт | *Please ack the page within 5 minutes.* |
| escalate | Эскалировать | *If there's no progress in 15 minutes, escalate.* |
| **mitigate** | Смягчить, уменьшить влияние (≠ устранить причину) | *We mitigated the impact by rolling back.* |
| workaround | Обходное решение | *The workaround is to restart the pod.* |
| hotfix | Срочное исправление в прод | *We shipped a hotfix within an hour.* |
| rollback / roll back | Откат / откатить | *Roll back to the previous release.* |
| root cause | Первопричина | *The root cause was an expired certificate.* |
| contributing factor | Способствующий фактор | *Missing alerts were a contributing factor.* |
| blast radius | Сколько всего заденет сбой или изменение | *Canary releases reduce the blast radius.* |
| impact | Влияние | *Customer impact: 15% of requests failed.* |
| postmortem | Разбор инцидента | *The postmortem is blameless.* |
| action items | Задачи по итогам с владельцами | *Each action item has an owner and a due date.* |
| incident commander (IC) | Координатор инцидента | *Aliya is the IC for this incident.* |
| resolved | Устранено | *The incident is resolved; we're monitoring.* |

### Встречи и рабочий процесс

| Термин | Значение | 🇬🇧 В предложении |
|--------|----------|-------------------|
| agenda | Повестка | *Here's the agenda for tomorrow.* |
| action items | Кто что делает после встречи | *Let's recap the action items.* |
| follow-up / follow up | Последующее действие / вернуться к вопросу | *I'll follow up in the thread.* |
| sync | Короткая встреча, синхронизация | *Can we have a quick sync on the migration?* |
| ETA | Когда будет готово | *What's the ETA for the fix?* |
| blocker / blocked on | Блокер / заблокирован чем-то | *I'm blocked on access to the registry.* |
| stand-up / standup | Ежедневная короткая встреча | *Let's discuss it after stand-up.* |
| retro | Ретроспектива | *Let's bring it up at the retro.* |
| 1:1 (one-on-one) | Встреча с руководителем один на один | *I'll raise it at my 1:1.* |
| heads-up | Предупреждение заранее | *Heads-up: staging will be down tomorrow.* |
| take it offline | Обсудить отдельно, не на общей встрече | *Let's take this offline.* |
| circle back | Вернуться к теме позже | *Let's circle back to this next week.* |
| bandwidth | Свободное время, ресурс | *I don't have the bandwidth this sprint.* |
| scope / out of scope | Объём задачи / не входит | *Autoscaling is out of scope for this task.* |
| stakeholder | Заинтересованная сторона | *We need sign-off from the stakeholders.* |
| ping | Написать, напомнить | *Ping me when the MR is ready.* |
| OOO, EOD | Нет на месте; конец дня | *I'm OOO on Friday. I'll send it by EOD.* |

---

## 3. Фразовые глаголы IT

Фразовый глагол = глагол + частица, и смысл часто не складывается из частей. В IT
без них не обходится ни один созвон.

| Глагол | Значение | 🇬🇧 Пример |
|--------|----------|-----------|
| spin up | Быстро поднять (ВМ, окружение) | *Let's spin up a test cluster.* |
| tear down | Снести целиком | *Tear down the environment after the test.* |
| roll out | Выкатить (постепенно) | *We'll roll out the change to 10% first.* |
| roll back | Откатить | *Roll back if the error rate goes up.* |
| look into | Разобраться, изучить | *I'll look into it after lunch.* |
| figure out | Понять, выяснить | *I can't figure out why the pod restarts.* |
| set up | Настроить | *I set up the CI pipeline.* |
| back up | Сделать бэкап | *Back up the database before the migration.* |
| log in / log out | Войти / выйти | *Log in to the server via the bastion.* |
| shut down | Выключить | *Shut down the old VM.* |
| bring up / bring down | Поднять / уронить (часто нечаянно) | *The migration brought down the database.* |
| break down | Сломаться; разбить на части | *Let's break down the task into smaller ones.* |
| run into | Столкнуться с проблемой | *I ran into a permissions issue.* |
| come up | Возникнуть | *Something came up, so I'll join later.* |
| fall back to | Перейти на запасной вариант | *The client falls back to HTTP/1.1.* |
| clean up | Прибрать | *Clean up old images in the registry.* |
| hand over / hand off | Передать (смену, задачу) | *I'll hand over the on-call shift at 9.* |
| follow up on | Вернуться, уточнить | *Can you follow up on the vendor ticket?* |
| catch up (on) | Наверстать; созвониться | *Let's catch up tomorrow.* |
| work around | Обойти | *We worked around the bug with an init container.* |
| sort out | Разобраться, решить | *The access issue is sorted out.* |
| kick off | Запустить | *Merging to main kicks off the pipeline.* |
| wrap up | Завершить | *Let's wrap up — we're out of time.* |
| point to | Указывать на | *The DNS record still points to the old IP.* |
| phase out | Постепенно вывести из использования | *We're phasing out Jenkins.* |
| fill in (for) | Подменить | *Can you fill in for me at stand-up?* |

---

## 4. Слитно или раздельно: *setup* или *set up*

Правило: **существительное и прилагательное — слитно** (или через дефис), **глагол —
раздельно**. Проверка: если можно поставить *to* перед словом и это действие — пиши
раздельно.

| Существительное (слитно) | Глагол (раздельно) | 🇬🇧 Пример |
|--------------------------|--------------------|-----------|
| setup | set up | *Set up the runner. The setup takes five minutes.* |
| backup | back up | *Back up the DB. Restore it from the latest backup.* |
| login | log in | *Log in with your SSO login.* |
| rollout | roll out | *We'll roll it out on Monday. The rollout is paused.* |
| rollback | roll back | *Roll back now. The rollback took 2 minutes.* |
| shutdown | shut down | *Shut down the node. The shutdown was clean.* |
| cleanup | clean up | *Clean up the namespace. Add a cleanup job.* |
| lookup | look up | *Look up the record. The DNS lookup failed.* |
| failover | fail over | *The DB will fail over automatically. Failover took 30 s.* |
| checkout | check out | *Check out the branch. The checkout step is slow.* |
| workaround | work around | *We can work around it. Here's a workaround.* |
| follow-up | follow up | *I'll follow up. Let's schedule a follow-up.* |
| teardown | tear down | *Tear down the stack. The teardown script failed.* |
| kickoff | kick off | *Let's kick off the project. The kickoff is on Monday.* |

---

## 5. Ложные друзья переводчика

Слова, похожие на русские, но с другим значением. Самые опасные — те, что встречаются
в работе каждый день.

| Слово | Кажется, что | На самом деле | Как сказать то, что хотел |
|-------|--------------|---------------|---------------------------|
| **actual** | актуальный | фактический, реальный | *current*, *up-to-date*, *relevant* |
| **accurate** | аккуратный | точный | *neat*, *careful*, *tidy* |
| **realize** | реализовать | осознать, понять | *implement* (фичу), *build* |
| **exploitation** | эксплуатация системы | использование уязвимости; эксплуатация людей | *operation*, *running in production* |
| **control** | контролировать (проверять) | управлять, иметь власть над | *check*, *monitor*, *keep track of* |
| **instance** | инстанция | экземпляр (ВМ, класса) | *authority*, *level* |
| **specific** | специфический | конкретный | *peculiar*, *unusual* |
| **eventually** | возможно | в конце концов, со временем | *possibly*, *perhaps* |
| **complex** | комплексный | сложно устроенный | *comprehensive*, *end-to-end* |
| **technique** | техника (оборудование) | метод, приём | *equipment*, *hardware* |
| **principal** | принципиальный | главный, основной | *fundamental* |
| **argument** | аргумент | спор (и довод) | *point*, *reason* |
| **protocol** (встречи) | протокол встречи | сетевой или дипломатический протокол | *meeting notes*, *minutes* |
| **pretend** | претендовать | притворяться | *apply for*, *claim* |
| **fabric** | фабрика | ткань; в IT — *network fabric* | *factory* |
| **magazine** | магазин | журнал | *shop*, *store* |
| **sympathetic** | симпатичный | сочувствующий | *nice*, *likable* |
| **intelligent** | интеллигентный | умный | *well-mannered*, *cultured* |
| **decade** | декада (10 дней) | десятилетие | *ten days* |
| **cabinet** | кабинет | шкаф; кабинет министров | *office* |

🇬🇧 Типичные ляпы и исправления:
```text
✗ This documentation is not actual anymore.     ✓ This documentation is out of date.
✗ We realized the new feature last sprint.       ✓ We implemented the new feature last sprint.
✗ The service is in exploitation since 2023.     ✓ The service has been in production since 2023.
✗ I will control the deployment.                 ✓ I'll monitor the deployment.
✗ We need a complex approach to monitoring.      ✓ We need a comprehensive approach to monitoring.
✗ Please be accurate with prod.                  ✓ Please be careful with prod.
```text
*Complex* vs *complicated*: оба «сложный», но *complex* — много связанных частей
(*a complex system*), *complicated* — запутанный, трудный для понимания
(*a complicated setup process*).

---

## 6. Произношение названий и терминов

Транскрипция упрощённая: ударный слог — ЗАГЛАВНЫМИ, рядом — приблизительно по-русски.
Послушать живых людей — YouGlish (youglish.com), словарные записи — Cambridge Dictionary.

| Слово | Как говорят | ≈ по-русски | ✗ Частая ошибка |
|-------|-------------|-------------|-----------------|
| nginx | ENGINE-ex | э́нджин-экс | «нги́нкс», «нжинкс» |
| kubectl | KOOB-control / koob-see-tee-EL / KOOB-cuddle | куб-контро́л / куб-си-ти-э́л / куб-ка́тл (kube — «куб» или «кьюб») | — официального нет, понятны все три |
| Kubernetes | koo-ber-NET-eez | ку-бер-нэ́-тис | «кубернете́с» |
| etcd | et-see-DEE | эт-си-ди́ | «эткд», «е-тэ-цэ-дэ» |
| sudo | SOO-doo (официально), SOO-doh | су́-ду, су́-доу | «судо́» |
| Linux | LIN-uks | ли́нукс | «ла́йнукс» |
| Debian | DEB-ee-en | дэ́биэн | «дебиа́н» |
| Ubuntu | oo-BOON-too | убу́нту | «юбу́нту» |
| cache | cash | кэш | «кейш», «ка́ше», «кэтч» |
| GUI | GOO-ee (или G-U-I) | гу́и | «гуй» |
| SQL | ess-kyoo-EL или SEE-kwel | эс-кью-э́л / си́квел | «эс-ку-э́ль» |
| PostgreSQL | POST-gres-kyoo-el, в речи — POST-gres | по́устгрес | «постгре-эс-ку-эль» |
| MySQL | my-ess-kyoo-EL (официально) | май-эс-кью-э́л | — «май-сиквел» тоже понимают |
| Azure | AZH-er | э́жер | «азу́р», «азю́р» |
| YAML | YAM-ul (как *camel*) | я́мл | «я-эм-э́л» |
| JSON | JAY-sun | джейсн | «жсон» |
| char | char (как в *charcoal*); встречаются «car», «care» | чар | — |
| Grafana | gruh-FAH-nuh | графа́на | «гра́фана» |
| Prometheus | pruh-MEE-thee-us | прэми́сиэс (th — межзубный) | «проме́теус» |
| Ansible | AN-suh-bul | э́нсибл | «анси́бл» |
| Vagrant | VAY-grunt | вэ́йгрэнт | «ваграунт» |
| Git | git (твёрдое g) | гит | «джит» |
| Jira | JEER-uh | джи́ра | «жи́ра» |
| Redis | RED-iss | рэ́дис | «реди́с» |
| Istio | IS-tee-oh | и́стиоу | «исти́о» |
| daemon | DEE-mun | ди́мэн | «дэмо́н» |
| queue | kyoo | кью | «кюэ́» |
| suite | sweet | свит | «сьют» (это *suit*) |
| height | hite | хайт | «хейт», «хайтс» |
| width | width (в конце — межзубный th) | уидс, но с межзубным th | «вайдс» |
| route | root (UK, US) или rowt (US) | рут / раут | — оба верны; *router* — «ру́тер» (UK), «ра́утер» (US) |

> 💡 Если сомневаешься, как назвать инструмент, — послушай, как его называют в докладах
> его авторов. Для команд вроде `kubectl` единого стандарта нет: говори уверенно любой
> распространённый вариант.

### Ударения, которые путают русскоговорящие

| Слово | Ударение | Комментарий |
|-------|----------|-------------|
| develop, developer | de-VEL-op | не «дЕвелопер» |
| deploy, deployment | de-PLOY | не «дЕплой» |
| component | com-PO-nent | не «компонЕнт» |
| environment | en-VY-ron-ment | не «энвайронмЕнт» |
| architecture | AR-ki-tek-chur | *ch* = «к» |
| infrastructure | IN-fra-struk-chur | ударение в начале |
| configure | con-FIG-ure | US: con-FIG-yer |
| determine | de-TER-min | не «детерма́йн» |
| variable | VAIR-ee-uh-bul | не «вариЭйбл» |
| hierarchy | HY-er-ar-kee | *ch* = «к» |
| parameter | pa-RAM-i-ter | не «параметЕр» |
| security | se-KYUR-i-tee | |
| category | KAT-uh-gor-ee | не «катЕгори» |

**Сдвиг ударения: существительное — на первый слог, глагол — на второй:**
*an UPdate* / *to upDATE*, *a REcord* / *to reCORD*, *an INcrease* / *to inCREASE*,
*an EXport* / *to exPORT*, *an OBject* / *to obJECT*.

### Артикль перед аббревиатурой — по звучанию

*a* или *an* выбирают по **первому звуку**, а не по букве:

| 🇬🇧 | Почему |
|-----|--------|
| *an SSH key*, *an HTTP request*, *an S3 bucket* | «эс», «эйч» — гласный звук |
| *a URL*, *a UUID*, *a user* | «ю» — согласный звук [j] |
| *an nginx config* | «энджин» — гласный звук |
| *a YAML file*, *a JSON payload* | согласный звук |
| *an SQL query* / *a SQL query* | зависит от того, как читаешь: «эс-кью-эл» или «сиквел» |
| *an hour*, *an API* | h не читается; «эй» |

---

## 7. Грабли

| Грабля | Последствие | Как правильно |
|--------|-------------|---------------|
| Учить слова списками | Узнаёшь, но не используешь | Сочетания из своего контекста, сразу в дело |
| *Actual* вместо *current* | «Фактическая документация» вместо «актуальной» | Карточка на каждого ложного друга, которого поймал у себя |
| *Realize* вместо *implement* | «Мы осознали фичу» | *Implement a feature* |
| *Exploitation* в резюме | Звучит как взлом или эксплуатация людей | *Operations*, *running in production* |
| *Setup* как глагол | *Please setup the runner* — ошибка | Глагол раздельно: *set up* |
| Учить произношение по написанию | «Кейш», «нгинкс», «проме́теус» | Проверять в словаре и на YouGlish |
| Бояться произносить название | Паузы и «ну, этот, как его» на созвоне | Выбрать распространённый вариант и говорить уверенно |
| Ударение как в русском | «ДЕвелопер», «компонЕнт» — понимают с трудом | Ударение проверять вместе со словом |
| *Mitigate* = *fix* | «Mitigated» в апдейте, хотя причина не устранена, — или наоборот | Mitigate — смягчили, fix / resolve — устранили |

---

## 💼 Как это в DevOps

- В инцидентах лексика — часть процесса: *mitigated*, *resolved*, *monitoring*,
  *root cause*, *blast radius* — у каждого слова строгий смысл в апдейте.
- Фразовые глаголы — основа устной речи на созвонах: *I'll look into it*, *let's roll
  it back*, *I ran into an issue*. Без них речь звучит как перевод.
- Произношение названий — первое, что слышит интервьюер: «энджин-экс» и «кэш» сразу
  звучат уверенно.
- Ложные друзья чаще всего всплывают в резюме и на собесе: *realized*, *exploitation*,
  *actual technologies* — классика, которую замечают сразу.

---

## 📌 Шпаргалка

| Вопрос | Ответ |
|--------|-------|
| Как учить слова | Сочетаниями, из своего контекста, сразу использовать |
| mitigate vs resolve | Смягчить влияние vs устранить |
| outage vs degradation | Недоступен vs работает хуже |
| scale out vs scale up | Больше экземпляров vs больше ресурсов |
| setup vs set up | Существительное слитно, глагол раздельно |
| actual / accurate | Фактический / точный (актуальный — *current*, аккуратный — *careful*) |
| realize / exploitation | Осознать / взлом (реализовать — *implement*, эксплуатация — *operations*) |
| nginx, cache, etcd | э́нджин-экс, кэш, эт-си-ди́ |
| Azure, YAML, sudo | э́жер, я́мл, су́-ду |
| kubectl | Любой из трёх: kube-control, kube-C-T-L, kube-cuddle |
| a или an | По звуку: *an SSH key*, *a URL*, *an nginx config* |
| UPdate / upDATE | Существительное — ударение на первый слог, глагол — на второй |

---

## 🧠 Что запомнить

1. ⭐ Учи сочетания (*roll back a release*), а не отдельные слова.
2. Слово переходит в активный словарь, только когда ты его используешь сам.
3. ⭐ *Mitigate* — смягчить влияние, *resolve* — устранить; в апдейте инцидента это разные статусы.
4. Фразовые глаголы — основа разговорного IT-английского: *spin up*, *look into*, *figure out*.
5. ⭐ Существительное слитно, глагол раздельно: *a backup* / *to back up*.
6. ⭐ *Actual* ≠ актуальный, *realize* ≠ реализовать, *exploitation* ≠ эксплуатация.
7. *Control* — управлять, а не проверять; проверять — *check*, *monitor*.
8. Произношение проверяют по словарю и YouGlish, а не угадывают по написанию.
9. Ударение — часть слова: *deVELop*, *comPOnent*, *enVIronment*.
10. *A* или *an* выбирают по звуку: *an SSH key*, *a URL*.

➡️ Дальше: [04_writing.md](/english/04-writing) · задачи: 03_vocabulary_tasks.md


---

### Блок A. Теория


**A1.** Чем пассивный словарь отличается от активного? Как слово переходит из одного
в другой?

<details><summary>Ответ</summary>

Пассивный — узнаёшь при чтении и на слух; активный — вспоминаешь сам, когда
говоришь или пишешь. Слово становится активным, когда ты несколько раз используешь его
сам: в сообщении, коммите, записи стендапа.

</details>

**A2.** ⭐ Почему учить сочетания полезнее, чем отдельные слова? Приведи три сочетания
из DevOps.

<details><summary>Ответ</summary>

Носители говорят блоками; выучив сочетание, не гадаешь, какой глагол или предлог
подходит, и звучишь естественно. *File an issue*, *roll back a release*, *mitigate
the impact* (а не *make an issue*, *do a rollback of*, *decrease the impact*).

</details>

**A3.** ⭐ Чем *mitigate* отличается от *resolve* и *fix*? Почему это важно в апдейте
инцидента?

<details><summary>Ответ</summary>

*Mitigate* — уменьшили влияние на пользователей (откат, переключение), причина
может оставаться. *Resolve* / *fix* — проблема устранена. В апдейте это разные статусы:
написать *fixed* после рестарта — ввести в заблуждение.

</details>

**A4.** Чем *outage* отличается от *degradation*? Что такое *blast radius*?

<details><summary>Ответ</summary>

*Outage* — сервис недоступен; *degradation* — работает, но хуже (медленно,
часть ошибок). *Blast radius* — сколько всего заденет сбой или изменение: сервисы,
пользователи, регионы.

</details>

**A5.** Чем *scale out* отличается от *scale up*?

<details><summary>Ответ</summary>

*Scale out* — добавить экземпляры (горизонтально); *scale up* — дать экземпляру
больше ресурсов (вертикально). В Kubernetes *scale up/down* часто говорят и про число
реплик — смысл ясен из контекста.

</details>

**A6.** Что значат *toil*, *drift*, *flaky test*, *canary release*?

<details><summary>Ответ</summary>

*Toil* — ручная повторяющаяся работа без долгосрочной ценности. *Drift* —
расхождение реального состояния с кодом (IaC). *Flaky test* — то проходит, то падает
без изменений в коде. *Canary release* — новая версия сначала получает малую долю трафика.

</details>

**A7.** Что значат на встрече *take it offline*, *circle back*, *heads-up*, *bandwidth*?

<details><summary>Ответ</summary>

*Take it offline* — обсудить отдельно, не занимая общую встречу. *Circle back* —
вернуться к теме позже. *Heads-up* — предупреждение заранее. *Bandwidth* — свободное
время и силы.

</details>

**A8.** ⭐ Назови восемь фразовых глаголов IT со значениями.

<details><summary>Ответ</summary>

*Spin up* — поднять; *tear down* — снести; *roll out* — выкатить; *roll back* —
откатить; *look into* — разобраться; *figure out* — понять; *run into* — столкнуться;
*set up* — настроить; *fall back to* — перейти на запасной; *wrap up* — завершить.

</details>

**A9.** ⭐ Сформулируй правило *setup / set up*. Приведи ещё четыре такие пары.

<details><summary>Ответ</summary>

Существительное и прилагательное — слитно, глагол — раздельно. *Backup / back up*,
*login / log in*, *rollout / roll out*, *cleanup / clean up*, *shutdown / shut down*,
*lookup / look up*.

</details>

**A10.** ⭐ Что на самом деле значат *actual*, *accurate*, *realize*, *exploitation*,
*control*, *eventually*? Как сказать то, что обычно хотят сказать?

<details><summary>Ответ</summary>

*Actual* — фактический (актуальный — *current, up-to-date*). *Accurate* — точный
(аккуратный — *careful, neat*). *Realize* — осознать (реализовать — *implement*).
*Exploitation* — эксплуатация уязвимости или людей (эксплуатация системы — *operations,
running in production*). *Control* — управлять (проверять — *check, monitor*).
*Eventually* — в конце концов, со временем (возможно — *possibly*; иногда — *sometimes*).

</details>

**A11.** Как произносятся nginx, etcd, cache, Azure, YAML, sudo? Есть ли официальное
произношение `kubectl`?

<details><summary>Ответ</summary>

nginx — «э́нджин-экс», etcd — «эт-си-ди́», cache — «кэш», Azure — «э́жер»,
YAML — «я́мл», sudo — «су́-ду» (официально) или «су́-доу». У `kubectl` официального
произношения нет: kube-control, kube-C-T-L, kube-cuddle — все понятны.

</details>

**A12.** Как меняется ударение в парах *update*, *record*, *increase*?

<details><summary>Ответ</summary>

Существительное — ударение на первый слог (*an UPdate*, *a REcord*,
*an INcrease*), глагол — на второй (*to upDATE*, *to reCORD*, *to inCREASE*).

</details>

**A13.** Как выбрать *a* или *an* перед аббревиатурой? Приведи примеры с SSH, URL, nginx.

<details><summary>Ответ</summary>

По первому звуку, а не букве: *an SSH key* («эс»), *a URL* («ю»),
*an nginx config* («энджин»).

</details>

---

### Блок B. «Что тут не так»


Найди ошибки в английском тексте и перепиши правильно.

**B1.** 🇬🇧 *This documentation is not actual, please use the actual version from the wiki.*

<details><summary>Ответ</summary>

⚠️ *Actual* — «фактический». ✓ *This documentation is out of date. Please use
the current version from the wiki.*

</details>

**B2.** 🇬🇧 *Last sprint we realized autoscaling, and now I control all deployments.*

<details><summary>Ответ</summary>

⚠️ *Realized* — «осознали», *control* — «управляю, имею власть». ✓ *Last sprint
we implemented autoscaling, and now I'm responsible for all deployments* (или *I monitor
all deployments*).

</details>

**B3.** 🇬🇧 *Please setup the runner and backup the database before the roll out.*

<details><summary>Ответ</summary>

⚠️ Глаголы раздельно, существительное слитно. ✓ *Please set up the runner
and back up the database before the rollout.*

</details>

**B4.** 🇬🇧 Апдейт инцидента: *We fixed the problem by restarting pods, root cause is
unknown, incident is closed.*

<details><summary>Ответ</summary>

⚠️ Рестарт — это *mitigated*, а не *fixed*; при неизвестной причине инцидент
не закрывают — наблюдают. Пропущены артикли. ✓ *We mitigated the issue by restarting
the pods. The root cause is still unknown. We're monitoring and investigating.*

</details>

**B5.** 🇬🇧 Строка в резюме: *3 years of exploitation of Linux servers, accurate work with
production.*

<details><summary>Ответ</summary>

⚠️ *Exploitation* — взлом или эксплуатация людей; *accurate* — «точный».
✓ *3 years of running Linux servers in production; careful, well-tested changes.*

</details>

**B6.** 🇬🇧 *I need to look after this bug, I can't figure it why it happens.*

<details><summary>Ответ</summary>

⚠️ *Look after* — присматривать (за ребёнком); разобраться — *look into*;
*figure out why*. ✓ *I need to look into this bug. I can't figure out why it happens.*

</details>

**B7.** 🇬🇧 *Eventually the build fails, maybe once a day, so it's probably a flaky test.*

<details><summary>Ответ</summary>

⚠️ *Eventually* — «в конце концов». ✓ *The build fails occasionally, about once
a day, so it's probably a flaky test.*

</details>

**B8.** 🇬🇧 *Let's make a protocol of the meeting and send it to all.*

<details><summary>Ответ</summary>

⚠️ *Protocol* — не протокол встречи; *to all* неестественно. ✓ *Let's take notes
and send them to everyone* (формально — *the minutes of the meeting*).

</details>

**B9.** 🇬🇧 *I pretend on the middle DevOps position.*

<details><summary>Ответ</summary>

⚠️ *Pretend* — «притворяться»; *middle* — не грейд. ✓ *I'm applying for
a mid-level DevOps position.*

</details>

**B10.** 🇬🇧 *Our DB is a bottle neck, we need to scale out it vertically.*

<details><summary>Ответ</summary>

⚠️ *Bottleneck* — одним словом; вертикально — это *scale up*; местоимение
после частицы: *scale it up*. ✓ *Our DB is a bottleneck. We need to scale it up.*

</details>

**B11.** 🇬🇧 *The nginx instance is down, please give me a login to the server so I can login.*

<details><summary>Ответ</summary>

⚠️ *A login* — логин/экран входа; просят доступ или учётные данные; глагол —
*log in*. ✓ *The nginx instance is down. Could you give me access to the server so
I can log in?*

</details>

**B12.** 🇬🇧 *There is a decade until the release, so we have enough time.*

<details><summary>Ответ</summary>

⚠️ *Decade* — десятилетие. ✓ *There are ten days until the release, so we have
enough time.*

</details>

**B13.** 🇬🇧 *I generated a SSH key and sent an URL to an user.*

<details><summary>Ответ</summary>

⚠️ Артикли по звуку. ✓ *I generated an SSH key and sent a URL to a user.*

</details>

---

### Блок C. Практика


### C1. 🔑 Свой глоссарий
Выпиши 20 терминов, которые встретил или использовал за эту неделю (доки, чат, созвоны,
логи). Для каждого — предложение из реального контекста. Сделай из них cloze-карточки.

### C2. 🔑 Фразовые глаголы
Вставь подходящий глагол в нужной форме: *spin up, roll back, look into, run into,
tear down, fall back to, kick off, roll out, figure out, wrap up, hand over, point to*.
**1.** 🇬🇧 *Can you ___ a test environment for the demo?*

<details><summary>Ответ</summary>

*This documentation is out of date.*

</details>

**2.** 🇬🇧 *The error rate went up after the release, so we ___ it ___.*

<details><summary>Ответ</summary>

*Last sprint we implemented monitoring.* (или *set up monitoring*)

</details>

**3.** 🇬🇧 *I'm not sure why the job fails — I'll ___ it after lunch.*

<details><summary>Ответ</summary>

*The service has been in production since 2023.*

</details>

**4.** 🇬🇧 *We ___ a permissions issue while deploying to prod.*

<details><summary>Ответ</summary>

*We need to monitor the rollout.* (или *keep an eye on the rollout*)

</details>

**5.** 🇬🇧 *Don't forget to ___ the environment after the load test.*

<details><summary>Ответ</summary>

*We need a comprehensive approach to security.*

</details>

**6.** 🇬🇧 *The client ___ HTTP/1.1 if HTTP/2 isn't available.*

<details><summary>Ответ</summary>

*This is a non-standard setting that isn't in the docs.* (или *an unusual setting*;
   *a specific setting* значило бы «конкретная настройка»)

</details>

**7.** 🇬🇧 *Merging to main ___ the deployment pipeline.*

<details><summary>Ответ</summary>

*Please be careful with prod.*

</details>

**8.** 🇬🇧 *We'll ___ the new version to 10% of users first.*

<details><summary>Ответ</summary>

*I'll send the meeting notes tonight.*

</details>

**9.** 🇬🇧 *I still can't ___ why the pod gets OOMKilled.*

<details><summary>Ответ</summary>

*I'm applying for a mid-level position.*

</details>

**10.** 🇬🇧 *Let's ___ — we're out of time.*
**11.** 🇬🇧 *I'll ___ the on-call shift to Aliya at 9 am.*

<details><summary>Ответ</summary>

) hand over. 12) points to.

</details>

**12.** 🇬🇧 *The DNS record still ___ the old load balancer.*
### C3. Слитно или раздельно
**1.** 🇬🇧 *Please ___ the monitoring for the new service.* (setup / set up)

<details><summary>Ответ</summary>

*This documentation is out of date.*

</details>

**2.** 🇬🇧 *The ___ failed last night.* (backup / back up)

<details><summary>Ответ</summary>

*Last sprint we implemented monitoring.* (или *set up monitoring*)

</details>

**3.** 🇬🇧 *Don't forget to ___ the volume.* (backup / back up)

<details><summary>Ответ</summary>

*The service has been in production since 2023.*

</details>

**4.** 🇬🇧 *I can't ___ to Grafana.* (login / log in)

<details><summary>Ответ</summary>

*We need to monitor the rollout.* (или *keep an eye on the rollout*)

</details>

**5.** 🇬🇧 *The ___ is paused at 50%.* (rollout / roll out)

<details><summary>Ответ</summary>

*We need a comprehensive approach to security.*

</details>

**6.** 🇬🇧 *We need to ___ the release.* (rollback / roll back)

<details><summary>Ответ</summary>

*This is a non-standard setting that isn't in the docs.* (или *an unusual setting*;
   *a specific setting* значило бы «конкретная настройка»)

</details>

**7.** 🇬🇧 *Add a ___ step to the pipeline.* (cleanup / clean up)

<details><summary>Ответ</summary>

*Please be careful with prod.*

</details>

**8.** 🇬🇧 *The DNS ___ takes 2 seconds.* (lookup / look up)

<details><summary>Ответ</summary>

*I'll send the meeting notes tonight.*

</details>

**9.** 🇬🇧 *Let's schedule a ___ next week.* (follow-up / follow up)

<details><summary>Ответ</summary>

*I'm applying for a mid-level position.*

</details>

**10.** 🇬🇧 *Our local ___ uses kind.* (setup / set up)
### C4. 🔑 Ложные друзья: перевод
Переведи на английский, не попавшись на ложных друзей:
**1.** Эта документация неактуальна.

<details><summary>Ответ</summary>

*This documentation is out of date.*

</details>

**2.** В прошлом спринте мы реализовали мониторинг.

<details><summary>Ответ</summary>

*Last sprint we implemented monitoring.* (или *set up monitoring*)

</details>

**3.** Сервис в эксплуатации с 2023 года.

<details><summary>Ответ</summary>

*The service has been in production since 2023.*

</details>

**4.** Нужно проконтролировать выкатку.

<details><summary>Ответ</summary>

*We need to monitor the rollout.* (или *keep an eye on the rollout*)

</details>

**5.** Нам нужен комплексный подход к безопасности.

<details><summary>Ответ</summary>

*We need a comprehensive approach to security.*

</details>

**6.** Это специфическая настройка, её нет в доке.

<details><summary>Ответ</summary>

*This is a non-standard setting that isn't in the docs.* (или *an unusual setting*;
   *a specific setting* значило бы «конкретная настройка»)

</details>

**7.** Аккуратнее с продом, пожалуйста.

<details><summary>Ответ</summary>

*Please be careful with prod.*

</details>

**8.** Протокол встречи пришлю вечером.

<details><summary>Ответ</summary>

*I'll send the meeting notes tonight.*

</details>

**9.** Я претендую на позицию мидла.

<details><summary>Ответ</summary>

*I'm applying for a mid-level position.*

</details>

### C5. 🔑 Произношение: запись
Запиши на телефон 15 слов из таблицы раздела 6 (nginx, cache, etcd, Azure, YAML, sudo,
Linux, Debian, Grafana, Prometheus, queue, suite, height, width, daemon). Сравни каждое
с YouGlish. Отметь три худших, повторяй их неделю и запиши снова.

### C6. Ударение
Прочитай вслух и запиши: 🇬🇧 *I need to record a demo. — The record is in the logs.*
*We'll update the chart. — The update broke staging.* *Traffic will increase. — We saw
an increase in errors.* Составь ещё по одной паре с *export* и *object*.

### C7. Лексика инцидента
Опиши по-английски в 5–6 предложениях реальный или учебный инцидент, используя:
*outage* или *degradation*, *impact*, *mitigate*, *root cause*, *roll back*, *blast radius*.

### C8. Итоги встречи
Напиши итог встречи (5–7 строк) по-английски: *agenda*, *action items* с владельцами,
*follow-up*, *ETA*, *blocker*.

---

### Блок D. Инциденты


**D1.** В англоязычном канале инцидента спрашивают: 🇬🇧 *Is it mitigated or resolved?*
Ты перезапустил поды, ошибки прекратились, причина неизвестна.

<details><summary>Ответ</summary>

🇬🇧
```text
Mitigated, not resolved. Restarting the pods stopped the errors at 14:32 UTC,
but we don't know the root cause yet. We're monitoring and investigating.
Next update at 15:00 UTC.
```text
</details>

**D2.** Коллега: 🇬🇧 *What's the blast radius if we rotate the internal CA today?*
Сертификаты от этого CA используют 12 сервисов и ingress.

<details><summary>Ответ</summary>

Blast radius — все 12 сервисов и ingress: при ошибке в ротации TLS может
отвалиться всё сразу. 🇬🇧
```text
The blast radius is large: 12 services and the ingress trust this CA.
To reduce it, I suggest rotating in stages: staging first, then one low-risk service
in prod, then the rest. Both CAs will be trusted during the transition.
```text
</details>

**D3.** Стендап по-английски. Нужно сказать: «Вчера разбирался, почему падает сборка —
нашёл, дело в кэше. Сегодня доделаю фикс и выкачу на stage. Блокер — нет доступа
к registry».

<details><summary>Ответ</summary>

🇬🇧
```text
Yesterday I looked into the failing build and figured out it was a cache issue.
Today I'll finish the fix and roll it out to staging.
I'm blocked on access to the registry — could someone help me with that after the call?
```text
</details>

**D4.** В резюме написано: 🇬🇧 *Exploitation and control of Kubernetes clusters, realization
of CI/CD pipelines, actual technologies.* Перепиши.

<details><summary>Ответ</summary>

🇬🇧
```text
Operated and maintained Kubernetes clusters in production;
implemented CI/CD pipelines with GitLab CI and Argo CD.
```text
*Actual technologies* убрать совсем — лучше конкретный стек.

</details>

**D5.** На созвоне: 🇬🇧 *Let's take this offline and circle back on Thursday.* Что сейчас
произойдёт и что тебе делать?

<details><summary>Ответ</summary>

Тему уберут с общей встречи и обсудят отдельно; вернутся к ней в четверг.
Твоё действие — не ждать пассивно: 🇬🇧 *Sounds good. I'll set up a short call with
Jonas and share the outcome in the thread before Thursday.*

</details>

**D6.** Ревьюер: 🇬🇧 *nit: "setup" should be "set up" here (it's a verb).* Ответь.

<details><summary>Ответ</summary>

🇬🇧 *Good catch, thanks! Fixed.* — коротко, без оправданий.

</details>

**D7.** На созвоне иностранный коллега дважды не понял твои «ка́ше» и «нги́нкс».
Что сделать сейчас и потом?

<details><summary>Ответ</summary>

Сейчас: не повторять то же самое громче, а сказать иначе или написать в чат —
🇬🇧 *Sorry, I mean the cache — C-A-C-H-E. Let me type it in the chat.* Потом: проверить
произношение на YouGlish, сделать карточки с аудио, записать себя в предложениях
с этими словами.

</details>

---

### Блок E. Вопросы с собеседования


**1.** 🇬🇧 *What's the difference between scaling up and scaling out?*

<details><summary>Ответ</summary>

🇬🇧 *Scaling up means giving a single instance more resources, like more CPU or memory.
   Scaling out means adding more instances behind a load balancer. Scaling out is usually
   better for availability, but the app must be stateless or handle shared state.*

</details>

**2.** 🇬🇧 *What does "blast radius" mean? How do you reduce it?*

<details><summary>Ответ</summary>

🇬🇧 *Blast radius is how much of the system or how many users a failure or a change
   can affect. You reduce it with canary releases, feature flags, separate environments
   and accounts, and by splitting large changes into smaller ones.*

</details>

**3.** 🇬🇧 *What's the difference between mitigating and resolving an incident?*

<details><summary>Ответ</summary>

🇬🇧 *Mitigation reduces the user impact quickly, for example with a rollback or
   a failover, even if we don't know the cause yet. Resolution means the underlying
   problem is fixed. In an incident, we mitigate first and investigate later.*

</details>

**4.** 🇬🇧 *What is toil? Give an example of toil you automated.*

<details><summary>Ответ</summary>

🇬🇧 *Toil is manual, repetitive work that doesn't add long-term value and grows with
   the system. For example, we renewed certificates by hand every few months; I set up
   cert-manager, and the task disappeared.*

</details>

**5.** 🇬🇧 *What is configuration drift, and how do you detect it?*

<details><summary>Ответ</summary>

🇬🇧 *Drift is when the real infrastructure no longer matches the code, usually because
   someone changed something by hand. I detect it with a scheduled `terraform plan` in CI
   and, for Kubernetes, with Argo CD, which shows resources that are out of sync.*

</details>

**6.** 🇬🇧 *What is a canary release?*

<details><summary>Ответ</summary>

🇬🇧 *A canary release sends a small part of the traffic, say 5%, to the new version
   first. If the error rate and latency look good, we gradually increase it; if not,
   we roll back, and only a few users are affected.*

</details>

**7.** 🇬🇧 *What is a flaky test, and what do you do about it?*

<details><summary>Ответ</summary>

🇬🇧 *A flaky test passes or fails without any code changes. I don't just rerun it
   forever: I track it, quarantine it if it blocks the team, and find the cause —
   usually timing, shared state, or an external dependency.*

</details>

**8.** 🇬🇧 *What does a good on-call rotation look like?*

<details><summary>Ответ</summary>

🇬🇧 *At least two people per shift, a primary and a secondary, clear escalation
   paths, runbooks for every alert, and time off after a bad night. Alerts should be
   actionable, and we should regularly remove noisy ones.*

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Собрал свой глоссарий из 20 терминов с реальными предложениями
- [ ] Использую фразовые глаголы на созвонах и в чате: *look into*, *roll back*, *figure out*
- [ ] ⭐ Пишу *set up* / *setup*, *back up* / *backup* без ошибок
- [ ] ⭐ Не путаю *actual*, *realize*, *exploitation*, *control*, *eventually*
- [ ] Различаю *mitigated* и *resolved* в апдейтах
- [ ] Записал себя на 15 словах и исправил три худших
- [ ] Ставлю ударение в *develop*, *component*, *environment* правильно
- [ ] Выбираю *a* / *an* перед аббревиатурами по звуку
