---
title: "04. Письмо: коммиты, MR, issues, чат, апдейты инцидентов"
description: "Блок → Английский для IT → тема 04. Опирается на ../../DevOps/SoftSkills/02writtencommunication.md"
---

# 04. Письмо: коммиты, MR, issues, чат, апдейты инцидентов

> Блок → Английский для IT → тема 04. Опирается на [../../DevOps/SoftSkills/02_written_communication.md](/softskills/02-written-communication)
> (BLUF, сообщения в чат, баг-репорты — там по существу), [../Git/11_collaboration.md](/git/11-collaboration)
> (описание MR, Conventional Commits), [../../DevOps/SRE/04_incident_management.md](/sre/04-incident-management)
> (апдейты инцидентов) и лексику из [03_vocabulary.md](/english/03-vocabulary). Здесь не повторяем,
> **что** писать, — здесь **как это звучит по-английски** и где ошибаются русскоговорящие.
>
> **После темы ты умеешь:** писать коммиты в повелительном наклонении по Conventional
> Commits; оформлять описание MR и отвечать на ревью по-английски; заводить issue и
> баг-репорт в open source; писать в чат вежливо, но прямо; писать апдейт инцидента
> и короткое письмо; не делать типичных ошибок: артикли, Present Perfect, порядок слов
> в вопросах, *make / do*, *it's / its*, тон.

---

## 🗺️ Карта темы

```text
 ЖАНР              ЧИТАТЕЛЬ                  ЧТО ВАЖНО ПО-АНГЛИЙСКИ
 ─────────────────────────────────────────────────────────────────────────────
 коммит            ты и команда через год    повелительное: Add, Fix — не Added
 MR / PR           ревьюер, 5 минут          What · Why · How to test · Risks
 ответ на ревью    ревьюер                   Good catch, fixed · I'd prefer… because
 issue / баг       мейнтейнер без контекста  Expected / Actual, версии, repro
 чат               коллега, 10 секунд        BLUF + вежливо, но прямо: Could you…
 апдейт инцидента  все, в стрессе            Status · Impact · Actions · Next update
 письмо            руководитель, 30 секунд   тема = суть, просьба и дата в начале
 ─────────────────────────────────────────────────────────────────────────────
 везде: короткие предложения · активный залог · простые слова · имена и цифры
```text
---

## 1. Три правила рабочего английского текста

1. **Короткие предложения.** Одна мысль — одно предложение. Длинное русское предложение
   с тремя придаточными по-английски разваливается.
2. **Активный залог.** *We rolled back the release* вместо *The release was rolled back
   by us*. Пассив уместен, когда исполнитель не важен: *The certificate was renewed.*
3. **Простые слова.** Чем проще, тем меньше шансов ошибиться и тем быстрее читают.

| ✗ Канцелярит | ✓ Просто |
|--------------|----------|
| utilize | use |
| commence | start |
| facilitate | help |
| in order to | to |
| at this point in time | now |
| due to the fact that | because |
| perform an investigation | investigate |
| make a decision regarding | decide on |

Как писать ясно по-английски — бесплатные курсы Google Technical Writing
(developers.google.com/tech-writing) и Google developer documentation style guide
(developers.google.com/style).

---

## 2. Коммиты

Правила (подробно — [../Git/11_collaboration.md](/git/11-collaboration), раздел 5):
- **Повелительное наклонение:** *Add*, *Fix*, *Remove* — не *Added*, *Fixes*, *Adding*.
  Так пишет и сам git: *Merge branch…*, *Revert "…"*.
- Заголовок — до ~50 символов (жёсткий предел — 72), без точки в конце; тело — через
  пустую строку, строки до 72 символов.
- Тело отвечает на **зачем**, а не пересказывает diff.
- По Conventional Commits описание после `type(scope):` обычно пишут со строчной буквы.

**Тест Криса Бимса** (статья «How to Write a Git Commit Message», cbea.ms/git-commit):
заголовок должен продолжать фразу *If applied, this commit will …*
*If applied, this commit will ~~fixed bug~~ → add Trivy scan stage.*

| ✗ Было | ✓ Стало |
|--------|---------|
| `fixed bug` | `fix(api): return 404 for unknown short links` |
| `Added new stage for trivy` | `ci: add Trivy scan stage` |
| `changes` | `docs: describe local setup in README` |
| `Update values.yaml` | `fix(helm): raise api memory limit to 512Mi` |
| `Fixes the issue with the DB connection when pool exhausted` | `fix(db): close idle connections to prevent pool exhaustion` |
| `WIP`, `final`, `final 2` | Сжать в осмысленные коммиты перед MR |

🇬🇧 Коммит с телом:
```text
fix(ci): retry registry push on 5xx errors

The registry returns 502 during its nightly garbage collection, which fails
about 1 in 20 pipelines. Retry the push up to 3 times with a 10-second delay.

Closes #412
```text
---

## 3. Описание MR и ответы на ревью

Заголовок MR — тоже в повелительном наклонении: *Add HPA for payment-service*.
Структура — как в [../Git/11_collaboration.md](/git/11-collaboration), раздел
«Хорошее описание MR», только по-английски.

🇬🇧 Шаблон:
```markdown
## What
Add a HorizontalPodAutoscaler for linkd-api (2–6 replicas, target CPU 70%).

## Why
During load tests, p99 latency went above 1 s at 150 RPS because a single replica
hit its CPU limit. Closes #57.

## How to test
kubectl -n linkd get hpa linkd-api
k6 run k6/load.js   # replicas should grow to 4+ within 2 minutes

## Risks and rollback
Replicas may flap if the target is too low. Rollback: revert this MR;
Argo CD prunes the HPA (auto-sync with pruning is enabled).

## Out of scope
Scaling on custom metrics (RPS) — #58.
```text
Полезные фразы: *This MR adds / removes / replaces…*, *Tested on staging*,
*No changes to prod values*, *Reviewer notes: please focus on…*, *Depends on !42*.
Незаконченный MR — с префиксом *Draft:* в GitLab или в статусе draft на GitHub.

### Ответы на комментарии ревью

| Ситуация | 🇬🇧 Фраза |
|----------|-----------|
| Согласен, исправил | *Good catch, fixed in a1b2c3d.* / *Done, thanks!* |
| Не согласен | *I'd prefer to keep it as is, because the chart already sets a default. What do you think?* |
| Не понял комментарий | *Could you clarify what you mean by "move it up"? The whole block or just the probe?* |
| Хорошая идея, но не сейчас | *Good point. It's out of scope for this MR, so I've created #123 to follow up.* |
| Прошу повторное ревью | *I've addressed all comments. Could you take another look?* |
| Прошу ревью | *PTAL when you have a moment. No rush — sometime today is fine.* |

Метки Conventional Comments ([../../DevOps/SoftSkills/07_review_mentoring.md](/softskills/07-review-mentoring))
уже английские: 🇬🇧 *nitpick (non-blocking): "set up" is a verb here, not "setup".*
*question: why 30 s? The upstream timeout is 10 s.*

---

## 4. Issue и баг-репорт

Структура — из [../../DevOps/SoftSkills/02_written_communication.md](/softskills/02-written-communication),
раздел 4. По-английски:

🇬🇧 Шаблон:
```markdown
**Title:** POST /orders returns 502 for orders with more than 50 items (staging, v1.42.0)

**Summary**
Creating an order with more than 50 items fails with 502 after 30 seconds.

**Environment**
staging, shop-api v1.42.0, Kubernetes 1.33, ingress-nginx

**Steps to reproduce**
1. `curl -X POST https://stage.shop.example.com/api/orders -d @order-60.json`
2. An order with 10 items takes 0.8 s; an order with 60 items fails 5 out of 5 times.

**Expected behavior**
201 Created.

**Actual behavior**
502 from the ingress after 30 s (upstream timeout).

**Impact**
About 2% of orders in prod are this large (wholesale customers): 37 last week.

**What I've tried**
Pods don't hit their limits; payments alone responds in about 1 s.
Trace abc123 shows 28 s in the call to payments.
```text
**Этикет open source:**
- сначала поиск по существующим issues; нашёл похожий — дополни его, а не заводи дубль;
- заполни шаблон проекта, укажи версии и минимальный пример (*minimal reproducible example*);
- одна проблема — один issue;
- не пиши *Any update?* через день; через пару недель — вежливо и с пользой:
  🇬🇧 *Is anyone working on this? I'd be happy to open a PR if the approach below works.*

---

## 5. Сообщения в чат

BLUF и «no hello» — в [../../DevOps/SoftSkills/02_written_communication.md](/softskills/02-written-communication),
разделы 2–3. По-английски добавляется **тон**: русская прямота в переводе часто звучит
резко, а попытка смягчить — слишком церемонно.

| ✗ Слишком прямо | ✓ Нормально | ✗ Перебор |
|-----------------|-------------|-----------|
| *Fix the pipeline.* | *Could you take a look at the pipeline? The build stage has been failing since this morning.* | *Would you be so kind as to have a look at the pipeline, if it's not too much trouble?* |
| *Why did you change this?* | *Could you help me understand why this changed? I want to make sure I don't break it.* | *Sorry, I'm probably wrong, but maybe…* |
| *You're wrong.* | *I see it differently: …* / *I'm not sure that's right, because…* | *With all due respect…* (часто звучит как наезд) |
| *Answer ASAP.* | *Could you reply by 3 pm? It's blocking the release.* | *Sorry to bother you, I'm really sorry, but…* |
| *Give me access.* | *Could you give me read access to the registry? I need it for OPS-123.* | |
| *Waiting for your answer.* | *Let me know what you think.* | |

**Смягчители:** *Could you…?*, *Would you mind + -ing?* (*Would you mind checking…?*),
*I was wondering if…*, *Maybe we could…*, *I think…*, *It looks like…*,
*It might be worth…*. Одного на сообщение достаточно.

🇬🇧 Фразы на каждый день:

| Фраза | Когда |
|-------|-------|
| *Quick question: …* | Короткий вопрос, сразу по делу |
| *Heads-up: …* / *FYI: …* | Предупредить / к сведению |
| *No rush.* / *Not urgent — sometime this week is fine.* | Явно снять срочность |
| *When you have a moment, …* | Вежливо, без давления |
| *Thanks in advance!* | В конце просьбы |
| *Sorry for the delay.* | Ответ спустя время — без долгих оправданий |
| *I'll get back to you by EOD.* | Нужно время на ответ |
| *Following up on my message above: …* | Напомнить о вопросе |
| *Does that make sense?* | Проверить, понят ли ты |

🇬🇧 Пример:
```text
✗ Hello
  I have question
  Why deploy is not working??

✓ Hi team! Deploying notifications to staging fails on `helm upgrade` with
  "field is immutable" (log below). I think MR !240 changed the selector labels.
  Should I delete the Deployment and reinstall? Not a blocker, but I'd like to ship
  it today.
```text
---

## 6. Апдейт инцидента по-английски

Ритм и правила — [../../DevOps/SRE/04_incident_management.md](/sre/04-incident-management),
раздел 6. Тот же шаблон по-английски:

🇬🇧 Внутренний апдейт:
```text
[SEV2][UPDATE #3] 14:45 UTC — Checkout errors
Status:   🔴 Investigating | 🟡 Identified, mitigating | 🟢 Mitigated, monitoring
Impact:   ~15% of /checkout requests have been failing since 14:05 UTC
Actions:  We rolled back release 1.42 at 14:40. The error rate is going down.
Next:     Monitoring for 30 minutes. Next update at 15:15 UTC.
IC: @aliya · Ops: @daniyar · Channel: #inc-2026-09-27-checkout
```text
**Времена в апдейте** — самое частое место ошибок:

| Что описываешь | Время | 🇬🇧 |
|----------------|-------|-----|
| Длится с момента до сейчас | Present Perfect (Continuous) | *Requests have been failing since 14:05.* |
| Сделали в конкретный момент | Past Simple | *We rolled back the release at 14:40.* |
| Происходит сейчас | Present Continuous | *We're monitoring the error rate.* |
| Будет дальше | *will* / *going to* | *The next update will be at 15:15 UTC.* |

🇬🇧 Внешний апдейт (статус-страница). Статусы — как у многих status page:
*Investigating → Identified → Monitoring → Resolved*. Без внутренних деталей и догадок:
```text
Investigating — Some customers may see errors when placing orders. We're investigating
and will post an update within 30 minutes.

Monitoring — We've applied a fix, and error rates are back to normal. We're monitoring
the results.

Resolved — This incident has been resolved. Between 14:05 and 14:45 UTC, about 15% of
checkout attempts failed. We apologize for the inconvenience.
```text
---

## 7. Короткие письма

| Часть | 🇬🇧 Как |
|-------|---------|
| Тема | Суть и срок: *Decision needed by Oct 3: standby database for payments* |
| Приветствие | *Hi Aliya,* / *Hi team,* / *Hello Mr. Smith,* (внешний формальный адресат) |
| Первая строка | Просьба или вывод (BLUF) |
| Тело | Пункты, цифры, варианты |
| Концовка | *Thanks,* / *Best regards,* / *Best,* + имя |

🇬🇧 Пример:
```text
Subject: Access request: read-only access to prod logs in Grafana

Hi Yerzhan,

Could you give me read-only access to prod logs in Grafana by Friday?
I'm on call starting next Monday, and I need logs to handle alerts.

- Scope: read-only, Loki datasource, prod folder
- Ticket: OPS-910
- My manager (Aliya) has approved it in the ticket.

Thanks,
Nurdaulet
```text
Не нужно: *Dear Sir or Madam* (в IT почти не пишут), *I hope this email finds you well*
(допустимо, но шаблонно), *Please find attached* (лучше *I've attached…*),
*Kindly revert* — ⚠️ в индийском английском *revert* = «ответить», но в IT
*revert* = «откатить»; пиши *Please reply*.

---

## 8. Типичные ошибки русскоговорящих

### Артикли

В русском артиклей нет, поэтому их либо пропускают, либо ставят наугад. Минимум для
рабочих текстов:

| Правило | 🇬🇧 Пример |
|---------|-----------|
| **a / an** — первое упоминание, «один из многих», исчисляемое в единственном числе | *I found a bug in the parser.* *I have a question.* |
| **the** — читатель знает, о чём речь: упоминали, единственный в контексте | *The bug is in line 42.* *Check the main branch.* *What's the root cause?* |
| Без артикля — множественное и неисчисляемое в общем смысле | *Logs are in Loki.* *Monitoring is important.* |
| Без артикля — имена продуктов | *Kubernetes*, *GitLab*, *Docker* — но *the Kubernetes API*, *the Docker daemon* |

Проверка: можно подставить «один» (*one*) — ставь *a / an*. Читатель точно знает,
какой именно, — *the*.
```text
✗ I have question about deployment.     ✓ I have a question about the deployment.
✗ There is error in logs.               ✓ There's an error in the logs.
✗ Please check a main branch.           ✓ Please check the main branch.
```text
### Present Perfect или Past Simple

| Когда | Время | 🇬🇧 |
|-------|-------|-----|
| Результат важен сейчас, время не названо | Present Perfect | *I've deployed the fix.* (он уже на проде) |
| Названо или понятно конкретное время в прошлом | Past Simple | *I deployed it yesterday at 5 pm.* |
| Период ещё не закончился | Present Perfect | *The job has failed three times today.* |
| С какого-то момента до сейчас (*since*, *for*) | Present Perfect (Continuous) | *I've been working as a backend developer for two years.* |

```text
✗ I have deployed it yesterday.        ✓ I deployed it yesterday.
✗ I work here since 2024.              ✓ I've worked here since 2024.
✗ It is down since 14:05.              ✓ It's been down since 14:05.
✗ When have you deployed it?          ✓ When did you deploy it?  (вопрос «когда» — Past Simple)
```text
### Порядок слов в вопросах

| ✗ | ✓ |
|---|---|
| *What means this flag?* | *What does this flag mean?* |
| *Why the pod doesn't start?* | *Why doesn't the pod start?* |
| *How it works?* | *How does it work?* |
| *Can you tell me where is the config?* | *Can you tell me where the config is?* (косвенный вопрос — прямой порядок) |
| *How to deploy it?* (как вопрос в чат) | *How do I deploy it?* (*How to deploy* — нормально как заголовок) |

### Неисчисляемые, make / do и другие

| Тема | ✗ | ✓ |
|------|---|---|
| Неисчисляемые | *informations, feedbacks, advices, softwares* | *information, feedback, advice, software*; *a piece of advice* |
| *code* | *I wrote some codes* | *I wrote some code* (*error codes* — можно) |
| *make* — создать, произвести | *do a mistake, do a decision* | *make a mistake, make a decision, make a change, make sure* |
| *do* — выполнить работу | *make a research, make a review* | *do research, do a code review* |
| IT-глаголы | *make a command, make an issue* | *run a command*, *open / file an issue*, *leave a comment*, *give feedback* |
| *it's / its* | *Its been down for an hour.* *The pod lost it's logs.* | *It's* = *it is / it has*; *its* — «его»: *The pod lost its logs.* |
| *agree* | *I am agree.* | *I agree.* |
| *-ing / -ed* | *I'm interesting in DevOps.* | *I'm interested in DevOps.* |
| Предлоги | *discuss about, explain me, depend of* | *discuss it, explain to me, depend on* |
| Срок | *Send it until Friday.* (как дедлайн) | *by Friday* — дедлайн; *until* — действие длится до момента: *I'm on call until Friday.* |
| Отрицание | *I didn't understood.* | *I didn't understand.* |

### Тон: грабли перевода

| Фраза | Проблема | ✓ Лучше |
|-------|----------|---------|
| *Please do the needful.* | Индийский английский, многим непонятно или звучит устаревше | Назвать действие: *Could you restart the runner?* |
| *Kindly revert.* | В IT *revert* = «откатить» | *Please reply.* |
| *Dear colleagues* в Slack | Слишком официально для чата | *Hi team,* |
| *Sorry for disturbing.* | Лишнее извинение | *Hi Aliya, quick question: …* |
| *Sorry for my bad English.* | Принижает тебя, отвлекает от сути | Просто пиши; попроси переспросить, если непонятно |
| *Tell me, please, …* | Калька, звучит как приказ | *Could you tell me…?* |

---

## 9. Было / стало

🇬🇧 MR:
```text
✗ Title: changes
  I did the changes in the helm chart, please check.

✓ Title: Add readiness probe to linkd-api
  What: add an HTTP readiness probe on /healthz (period 10 s, failure threshold 3).
  Why: during rollouts, traffic went to pods that weren't ready, causing ~40 errors
  per deploy. Closes #61.
  How to test: `kubectl rollout restart deploy/linkd-api -n linkd` while k6 is running —
  no 5xx.
  Risks: a slow start could fail the probe; initialDelaySeconds is 5.
```text
🇬🇧 Сообщение тимлиду:
```text
✗ Hello! Sorry for disturbing. I wanted to say that I was working on the CI task,
  and there were some problems with the runner, and I think maybe I will not finish
  until Friday, sorry.

✓ Hi Aliya! The CI task (OPS-934) won't be ready by Friday: our runner can't pull
  from the new registry, and fixing that takes about two days.
  Options: (A) I ship the pipeline without the publish step on Friday, and the rest
  next Wednesday; (B) we move the deadline to Wednesday. Which works better for you?
```text
---

## 10. Грабли

| Грабля | Последствие | Как правильно |
|--------|-------------|---------------|
| Писать по-русски в голове и переводить | Длинные предложения, кальки, странный тон | Думать короткими фразами, использовать готовые шаблоны |
| *Added / Fixes* в коммитах | Непоследовательная история | Повелительное: *Add*, *Fix* |
| Описание MR «please check» | Ревьюер не знает, что и зачем | What / Why / How to test / Risks |
| Прямые приказы | Звучит грубо | *Could you…?* + причина и срок |
| Пять извинений в сообщении | Звучит неуверенно, теряется суть | Одно *sorry* — когда виноват; суть — первой |
| Пропущенные артикли | Текст понятен, но режет глаз | Проверка «можно ли подставить *one*?» |
| *I have done it yesterday* | Классическая ошибка, заметна сразу | С конкретным временем — Past Simple |
| *Kindly revert*, *do the needful* | Непонятно или двусмысленно | Назвать конкретное действие |
| ИИ пишет за тебя | Навык не растёт, тексты «чужие» | Сначала сам, ИИ — проверка ([01_level_and_system.md](/english/01-level-and-system), раздел 9) |
| *Mitigated* и *resolved* как синонимы | Люди думают, что всё починено | Разные статусы ([03_vocabulary.md](/english/03-vocabulary)) |

---

## 💼 Как это в DevOps

- Коммиты, MR и README pet-проекта на английском — первое, что видит зарубежный
  работодатель в твоём GitHub/GitLab.
- В международной команде почти вся работа — письменная и асинхронная: хорошее письмо
  на английском заменяет половину созвонов.
- Апдейты инцидентов читают руководители и поддержка: ошибка во времени глагола
  (*is resolved* вместо *has been mitigated*) меняет смысл для всех.
- Issue в open source с понятным английским и минимальным примером разбирают быстрее —
  проверено каждым, кто заводил issue в kubernetes или helm.
- На собесе иногда дают задание «напиши сообщение команде» или просят показать свои MR.

---

## 📌 Шпаргалка

| Вопрос | Ответ |
|--------|-------|
| Коммит | `type(scope): add …` — повелительное, ≤ 50 символов, без точки; тело — зачем |
| Тест заголовка | *If applied, this commit will …* |
| MR | What · Why · How to test · Risks and rollback · Out of scope |
| Ответ на ревью | *Good catch, fixed in …* · *I'd prefer … because …* · *Created #123 to follow up* |
| Issue | Summary · Environment · Steps · Expected · Actual · Impact · What I've tried |
| Чат | BLUF + *Could you…?* + причина + срок; одно смягчение, без приказов и лишних извинений |
| Апдейт инцидента | Status · Impact · Actions · Next update; *have been failing since*, *rolled back at* |
| Письмо | Тема = суть; *Hi Aliya,* · просьба с датой первой · *Thanks,* |
| Артикли | *a* — один из многих, *the* — известный читателю, без артикля — множественное и продукты |
| Perfect vs Past | Время названо — Past Simple; результат сейчас — Present Perfect |
| Вопросы | *What does it mean?* · *Do you know where it is?* |
| Не писать | *informations*, *feedbacks*, *do a mistake*, *kindly revert*, *do the needful* |

---

## 🧠 Что запомнить

1. ⭐ Короткие предложения, активный залог, простые слова — главное в рабочем английском.
2. ⭐ Коммит — в повелительном наклонении: *If applied, this commit will …*
3. Описание MR по-английски — те же What / Why / How to test / Risks.
4. На каждый комментарий ревью — ответ: исправил, не согласен и почему, или вынес в задачу.
5. Issue в open source: поиск дублей, версии, минимальный пример, *expected / actual*.
6. ⭐ Вежливо, но прямо: *Could you…?* + причина + срок. Без приказов и без церемоний.
7. В апдейте инцидента время глагола несёт смысл: *have been failing since*, *rolled back at*.
8. ⭐ Конкретное время в прошлом — Past Simple; результат сейчас — Present Perfect.
9. Артикль: можно подставить *one* — *a / an*; читатель знает, какой, — *the*.
10. *Information*, *feedback*, *advice*, *code* — без *-s*; *make a mistake*, *do research*.

➡️ Дальше: [05_speaking.md](/english/05-speaking) · задачи: 04_writing_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Назови три правила рабочего английского текста. Замени простыми словами:
*utilize*, *commence*, *in order to*, *due to the fact that*.

<details><summary>Ответ</summary>

Короткие предложения, активный залог, простые слова. *Use*, *start*, *to*, *because*.

</details>

**A2.** ⭐ Почему заголовок коммита пишут в повелительном наклонении? Что за тест
*If applied, this commit will…*?

<details><summary>Ответ</summary>

Заголовок описывает, что коммит **сделает** при применении; так пишет и сам git
(*Merge branch*, *Revert*). Тест Криса Бимса: заголовок должен грамматично продолжать
фразу *If applied, this commit will…* — *add Trivy scan stage* подходит, *added trivy* нет.

</details>

**A3.** Какие ограничения на длину заголовка и тела коммита? Что писать в теле?

<details><summary>Ответ</summary>

Заголовок — до ~50 символов (жёстко — 72), без точки; тело — после пустой строки,
строки до 72 символов. В теле — зачем изменение и что важно знать, а не пересказ diff.

</details>

**A4.** Из каких разделов состоит описание MR на английском? Как назвать незаконченный MR?

<details><summary>Ответ</summary>

What, Why, How to test, Risks and rollback, Out of scope, ссылка на задачу.
Незаконченный — префикс *Draft:* в GitLab или draft PR на GitHub.

</details>

**A5.** ⭐ Как по-английски ответить на комментарий ревью: согласен; не согласен;
не понял; хорошая идея, но не в этом MR?

<details><summary>Ответ</summary>

*Good catch, fixed in a1b2c3d.* / *I'd prefer to keep it as is, because… What do
you think?* / *Could you clarify what you mean by…?* / *Good point — it's out of scope for
this MR, so I've created #123 to follow up.*

</details>

**A6.** Из каких разделов состоит issue по-английски? Назови три правила этикета
open source.

<details><summary>Ответ</summary>

Summary, Environment, Steps to reproduce, Expected behavior, Actual behavior,
Impact, What I've tried. Этикет: искать дубли; заполнять шаблон с версиями
и минимальным примером; одна проблема — один issue; не торопить мейнтейнеров.

</details>

**A7.** ⭐ Почему русская прямота в английском чате звучит резко? Назови пять смягчителей.

<details><summary>Ответ</summary>

По-английски повелительное наклонение и *You must…* без смягчения звучат как
приказ, а вежливость строится вопросами и оговорками. Смягчители: *Could you…?*,
*Would you mind + -ing?*, *I was wondering if…*, *Maybe we could…*, *It looks like…*,
*It might be worth…*.

</details>

**A8.** Какие статусы у внешнего апдейта инцидента? Какие времена глаголов используют
в апдейте и для чего?

<details><summary>Ответ</summary>

*Investigating → Identified → Monitoring → Resolved.* Present Perfect (Continuous) —
что длится с момента до сейчас (*have been failing since*); Past Simple — действия
в конкретное время (*rolled back at 14:40*); Present Continuous — что идёт сейчас
(*we're monitoring*); *will* — следующий апдейт.

</details>

**A9.** Из каких частей состоит короткое рабочее письмо? Чего в нём лучше избегать?

<details><summary>Ответ</summary>

Тема = суть и срок; приветствие *Hi Aliya,*; просьба или вывод первой строкой;
пункты с цифрами; *Thanks,* + имя. Избегать: *Dear Sir or Madam*, *Kindly revert*,
*Please do the needful*, длинных вступлений.

</details>

**A10.** ⭐ Сформулируй правило выбора *a / an / the / без артикля* для рабочих текстов.

<details><summary>Ответ</summary>

*A / an* — первое упоминание, «один из многих», исчисляемое в единственном числе.
*The* — читатель знает, о чём речь. Без артикля — множественное и неисчисляемое
в общем смысле, имена продуктов (*Kubernetes*, но *the Kubernetes API*).

</details>

**A11.** ⭐ Когда Present Perfect, а когда Past Simple? Почему *I have deployed it
yesterday* — ошибка?

<details><summary>Ответ</summary>

Present Perfect — результат важен сейчас, время не названо, или период не
закончился, или *since / for*. Past Simple — конкретное время в прошлом. *Yesterday* —
конкретное время, поэтому *I deployed it yesterday*.

</details>

**A12.** Как строится прямой и косвенный вопрос? Исправь *What means this flag?*
и *Can you tell me where is the config?*

<details><summary>Ответ</summary>

Прямой вопрос — вспомогательный глагол перед подлежащим: *What does this flag
mean?* Косвенный — прямой порядок слов: *Can you tell me where the config is?*

</details>

**A13.** Назови пять неисчисляемых существительных из IT. Когда *make*, а когда *do*?

<details><summary>Ответ</summary>

*Information, feedback, advice, software, hardware, equipment, knowledge, research,
documentation, code.* *Make* — создать, произвести (*make a change, a decision, a mistake*);
*do* — выполнить работу (*do research, do a code review*).

</details>

**A14.** Что не так с *Please do the needful* и *Kindly revert*?

<details><summary>Ответ</summary>

*Do the needful* — индийский английский, многим непонятно, что именно сделать.
*Revert* в индийском английском — «ответить», а в IT — «откатить»: двусмысленно.
Лучше назвать действие и написать *Please reply*.

</details>

---

### Блок B. «Что тут не так»


Найди ошибки в английском тексте и перепиши правильно.

**B1.** 🇬🇧 История коммитов:

<details><summary>Ответ</summary>

⚠️ Прошедшее время и *-ing*, разный регистр, точка, дублирование *fix: Fixed*,
нет смысла. ✓
```text
fix(api): return 404 for unknown short links
ci: add Trivy scan stage
docs: describe local setup in README
fix(k8s): add memory limits to prevent OOMKills
```text
</details>

```text:no-line-numbers
Fixed bug
```text
```text:no-line-numbers
added trivy
```text
```text:no-line-numbers
Updating readme.
```text
```text:no-line-numbers
fix: Fixed the problem with pods
```text
**B2.** 🇬🇧 Описание MR: *In this MR I have added HPA. Please check it. It was tested.*

<details><summary>Ответ</summary>

⚠️ Нет зачем, как проверить, рисков; *It was tested* — где и как? ✓ *What: add
an HPA for linkd-api (2–6 replicas, CPU 70%). Why: p99 went above 1 s at 150 RPS.
How to test: run k6 and watch `kubectl get hpa`. Risks: flapping; rollback — revert.*

</details>

**B3.** 🇬🇧 Сообщение в канал: *Hello. I have question. Why build is failing? Answer me
please ASAP.*

<details><summary>Ответ</summary>

⚠️ Одинокое *Hello*, нет артиклей, неправильный порядок слов, нет контекста,
*Answer me ASAP* — грубо. ✓ *Hi team! The build for notifications has been failing
since 10:00 with "no space left on device" (job link). Could someone who manages
the runners take a look? It blocks today's release.*

</details>

**B4.** 🇬🇧 Сеньору в личку: *Give me access to prod database, I need it for debug.*

<details><summary>Ответ</summary>

⚠️ Приказ, без артиклей, без причины и срока; доступ к проду просят через
процесс. ✓ *Could you help me get read-only access to the prod database? I need to
debug OPS-123. If there's a safer way, like a masked dump, that works for me too.*

</details>

**B5.** 🇬🇧 Апдейт инцидента: *Incident is resolved. We are restarting pods since 14:00
and the error rate decrease.*

<details><summary>Ответ</summary>

⚠️ *Resolved* при том, что поды ещё перезапускают; *are restarting since* →
Present Perfect Continuous; *decrease* → *is decreasing*; нет артиклей. ✓ *We've been
restarting the pods since 14:00, and the error rate is decreasing. The incident isn't
resolved yet; next update at 14:30 UTC.*

</details>

**B6.** 🇬🇧 Письмо: *Dear Sir, I hope this email finds you well. Kindly revert with the
access. Please do the needful. Waiting for your answer.*

<details><summary>Ответ</summary>

⚠️ *Dear Sir* и шаблонная вежливость, *Kindly revert*, *do the needful*,
*Waiting for your answer* — всё вместе звучит и старомодно, и давяще; главное — не
сказано, какой доступ. ✓ *Hi Yerzhan, could you give me read-only access to the prod
logs in Grafana by Friday? Ticket: OPS-910. Thanks!*

</details>

**B7.** 🇬🇧 Issue в open source: *It doesn't work!!! Your helm chart is broken, fix it ASAP.*

<details><summary>Ответ</summary>

⚠️ Нет версий, шагов, ожидаемого и фактического; обвинение и *ASAP* в адрес
волонтёров. ✓ *`helm install` fails with "…" on chart v2.3.0 (Helm 3.x, Kubernetes 1.33).
Steps: … Expected: … Actual: … I'm happy to provide more details.*

</details>

**B8.** 🇬🇧 Ответ на ревью: *No, it's correct, I don't want to change it.*

<details><summary>Ответ</summary>

⚠️ Отказ без причины. ✓ *I'd prefer to keep it as is, because the default comes
from the chart and can be overridden in values. Happy to change it if you see a case
where that doesn't work.*

</details>

**B9.** 🇬🇧 *I have deployed the fix yesterday and since then there is no errors.*

<details><summary>Ответ</summary>

⚠️ *Yesterday* → Past Simple; *there is no errors* → *there have been no errors*.
✓ *I deployed the fix yesterday, and there have been no errors since then.*

</details>

**B10.** 🇬🇧 *Can you tell me where is the runbook for this alert and what means "burn rate"?*

<details><summary>Ответ</summary>

⚠️ Косвенные вопросы — прямой порядок слов. ✓ *Can you tell me where the runbook
for this alert is and what "burn rate" means?*

</details>

**B11.** 🇬🇧 *We need to make a research about which monitoring softwares to use, I will give
you a feedback tomorrow.*

<details><summary>Ответ</summary>

⚠️ *Do research* (без артикля, без *about* → *on*), *software* и *feedback*
неисчисляемые. ✓ *We need to do some research on which monitoring tools to use. I'll give
you feedback tomorrow.*

</details>

**B12.** 🇬🇧 *Its not a bug, the service works as expected, it's config just points to the
old database.*

<details><summary>Ответ</summary>

⚠️ *Its* → *It's* (it is); *it's config* → *its config* (притяжательное).
✓ *It's not a bug. The service works as expected; its config just points to the old
database.*

</details>

**B13.** 🇬🇧 *I'm agree with you, lets discuss about it on the retro.*

<details><summary>Ответ</summary>

⚠️ *I'm agree* → *I agree*; *lets* → *let's*; *discuss about* → *discuss*;
*on the retro* → *at the retro*. ✓ *I agree with you. Let's discuss it at the retro.*

</details>

---

### Блок C. Практика


### C1. 🔑 Пять своих коммитов
Возьми 5 последних коммитов с работы или из linkd. Перепиши по Conventional Commits
на английском: повелительное наклонение, до 50 символов, тело «зачем» там, где нужно.
Каждый проверь тестом *If applied, this commit will…*

### C2. 🔑 Описание MR
Напиши по-английски описание MR для реального изменения или для linkd (например,
«добавить readiness probe» или «кэш зависимостей в CI»): What, Why, How to test,
Risks and rollback, Out of scope.

### C3. Артикли
Вставь *a / an / the* или ничего (—):
**1.** 🇬🇧 *I found ___ bug in ___ CI pipeline.*

<details><summary>Ответ</summary>

*Hi! Where can I find the values for shop-api on staging? Not urgent — before lunch
   is fine.*

</details>

**2.** 🇬🇧 *___ bug is in ___ cache key.*

<details><summary>Ответ</summary>

*Could you review my MR by tomorrow? It's a small change in the CI config.*

</details>

**3.** 🇬🇧 *___ logs are usually stored in Loki.*

<details><summary>Ответ</summary>

*I won't make it by Friday: I need access to the registry, and my request has been
   pending since Monday.*

</details>

**4.** 🇬🇧 *Could you create ___ SSH key for ___ new runner?*

<details><summary>Ответ</summary>

*Thanks for the review! I've fixed everything except the timeout — I explained why
   in the comment.*

</details>

**5.** 🇬🇧 *We use ___ Kubernetes in production.*

<details><summary>Ответ</summary>

*Following up on my question above: it's blocking the 3 pm release.*

</details>

**6.** 🇬🇧 *___ Kubernetes API server was unavailable for five minutes.*

<details><summary>Ответ</summary>

Проверка: заголовок понятен из списка issues; есть *Expected* и *Actual*;
шаги повторит человек без контекста; версии указаны.

</details>

**7.** 🇬🇧 *I have ___ question about ___ deployment we discussed yesterday.*

<details><summary>Ответ</summary>

🇬🇧
```text
Subject: Decision needed by Oct 3: standby database for payments

Hi Aliya,

If the payments database server fails, payments will be down for 2–4 hours.
I suggest building a standby database with automatic failover. Could you decide
by Friday, Oct 3?

Options:
A. Standby with automatic failover: 2 weeks, +90,000 KZT/month, downtime of minutes
B. Backups every 15 minutes: 2 days, +10,000 KZT/month, 2–4 hours of downtime
C. Do nothing: no cost, the risk stays

I recommend A: the 11.11 sale is our busiest day, and a few hours without payments
would cost more. Technical details are in the RFC (link).

Thanks,
Nurdaulet
```text
</details>

**8.** 🇬🇧 *___ monitoring is ___ important part of ___ DevOps.*

<details><summary>Ответ</summary>

1) *What does this error mean?* 2) *Why is the pipeline red?* 3) *Where can
I find the runbook?* 4) *Do you know when the release is?* 5) *How does it work with
Helm?* 6) *Could you tell me what the ETA is?*

</details>

**9.** 🇬🇧 *There's ___ error in ___ logs of ___ payments service.*

<details><summary>Ответ</summary>

) an, the, the. 10) an, the.

</details>

**10.** 🇬🇧 *It took ___ hour to find ___ root cause.*
### C4. Present Perfect или Past Simple
**1.** 🇬🇧 *I ___ (deploy) the fix — you can check it now.*

<details><summary>Ответ</summary>

*Hi! Where can I find the values for shop-api on staging? Not urgent — before lunch
   is fine.*

</details>

**2.** 🇬🇧 *I ___ (deploy) the fix yesterday at 6 pm.*

<details><summary>Ответ</summary>

*Could you review my MR by tomorrow? It's a small change in the CI config.*

</details>

**3.** 🇬🇧 *The job ___ (fail) three times today.*

<details><summary>Ответ</summary>

*I won't make it by Friday: I need access to the registry, and my request has been
   pending since Monday.*

</details>

**4.** 🇬🇧 *The job ___ (fail) three times yesterday.*

<details><summary>Ответ</summary>

*Thanks for the review! I've fixed everything except the timeout — I explained why
   in the comment.*

</details>

**5.** 🇬🇧 *I ___ (work) as a backend developer since April.*

<details><summary>Ответ</summary>

*Following up on my question above: it's blocking the 3 pm release.*

</details>

**6.** 🇬🇧 *When ___ you ___ (notice) the errors?*

<details><summary>Ответ</summary>

Проверка: заголовок понятен из списка issues; есть *Expected* и *Actual*;
шаги повторит человек без контекста; версии указаны.

</details>

**7.** 🇬🇧 *Requests ___ (fail) since 14:05 UTC.*

<details><summary>Ответ</summary>

🇬🇧
```text
Subject: Decision needed by Oct 3: standby database for payments

Hi Aliya,

If the payments database server fails, payments will be down for 2–4 hours.
I suggest building a standby database with automatic failover. Could you decide
by Friday, Oct 3?

Options:
A. Standby with automatic failover: 2 weeks, +90,000 KZT/month, downtime of minutes
B. Backups every 15 minutes: 2 days, +10,000 KZT/month, 2–4 hours of downtime
C. Do nothing: no cost, the risk stays

I recommend A: the 11.11 sale is our busiest day, and a few hours without payments
would cost more. Technical details are in the RFC (link).

Thanks,
Nurdaulet
```text
</details>

**8.** 🇬🇧 *___ you ___ (check) the logs yet?*

<details><summary>Ответ</summary>

1) *What does this error mean?* 2) *Why is the pipeline red?* 3) *Where can
I find the runbook?* 4) *Do you know when the release is?* 5) *How does it work with
Helm?* 6) *Could you tell me what the ETA is?*

</details>

### C5. 🔑 Сообщения в чат: перевод с тоном
Переведи так, чтобы звучало вежливо, но прямо:
**1.** «Привет! Подскажи, где лежат values для shop-api на stage? Не срочно, до обеда».

<details><summary>Ответ</summary>

*Hi! Where can I find the values for shop-api on staging? Not urgent — before lunch
   is fine.*

</details>

**2.** «Можешь посмотреть мой MR до завтра? Там небольшое изменение в CI».

<details><summary>Ответ</summary>

*Could you review my MR by tomorrow? It's a small change in the CI config.*

</details>

**3.** «Не успеваю к пятнице: нужен доступ к registry, заявка висит с понедельника».

<details><summary>Ответ</summary>

*I won't make it by Friday: I need access to the registry, and my request has been
   pending since Monday.*

</details>

**4.** «Спасибо за ревью! Всё поправил, кроме таймаута — объяснил в комментарии».

<details><summary>Ответ</summary>

*Thanks for the review! I've fixed everything except the timeout — I explained why
   in the comment.*

</details>

**5.** «Напоминаю про вопрос выше: он блокирует релиз в 15:00».

<details><summary>Ответ</summary>

*Following up on my question above: it's blocking the 3 pm release.*

</details>

### C6. Баг-репорт
Возьми поломку из журнала linkd (`docs/journal.md`) или с работы и оформи issue
по-английски по шаблону из раздела 4.

### C7. Письмо с просьбой о решении
Напиши по-английски короткую версию письма из
[../../DevOps/SoftSkills/02_written_communication.md](/softskills/02-written-communication),
раздел 9 (резервная база для payments): тема, просьба и дата, варианты A/B/C, рекомендация.

### C8. Порядок слов в вопросах
Исправь:
**1.** 🇬🇧 *What means this error?*

<details><summary>Ответ</summary>

*Hi! Where can I find the values for shop-api on staging? Not urgent — before lunch
   is fine.*

</details>

**2.** 🇬🇧 *Why the pipeline is red?*

<details><summary>Ответ</summary>

*Could you review my MR by tomorrow? It's a small change in the CI config.*

</details>

**3.** 🇬🇧 *Where I can find the runbook?*

<details><summary>Ответ</summary>

*I won't make it by Friday: I need access to the registry, and my request has been
   pending since Monday.*

</details>

**4.** 🇬🇧 *Do you know when is the release?*

<details><summary>Ответ</summary>

*Thanks for the review! I've fixed everything except the timeout — I explained why
   in the comment.*

</details>

**5.** 🇬🇧 *How it works with Helm?*

<details><summary>Ответ</summary>

*Following up on my question above: it's blocking the 3 pm release.*

</details>

**6.** 🇬🇧 *Could you tell me what is the ETA?*

<details><summary>Ответ</summary>

Проверка: заголовок понятен из списка issues; есть *Expected* и *Actual*;
шаги повторит человек без контекста; версии указаны.

</details>

---

### Блок D. Инциденты


**D1.** Напиши по-английски первый внутренний апдейт: SEV2, 09:12 UTC; с 09:00 около 30%
логинов падают с 500; расследуете, подозрение на релиз auth-сервиса в 08:55; следующий
апдейт в 09:30.

<details><summary>Ответ</summary>

🇬🇧
```text
[SEV2][UPDATE #1] 09:12 UTC — Login errors
Status:   🔴 Investigating
Impact:   ~30% of login requests have been failing with 500 since 09:00 UTC
Actions:  Investigating. We suspect the auth-service release deployed at 08:55.
Next:     Next update at 09:30 UTC.
IC: @aliya · Channel: #inc-2026-10-01-login
```text
</details>

**D2.** Продолжение: в 09:25 откатили релиз, в 09:28 ошибки вернулись к норме. Напиши
внутренний апдейт #3 и внешний апдейт со статусом *Resolved* (в 10:00).

<details><summary>Ответ</summary>

🇬🇧
```text
[SEV2][UPDATE #3] 09:40 UTC — Login errors
Status:   🟢 Mitigated, monitoring
Impact:   ~30% of logins failed between 09:00 and 09:28 UTC
Actions:  We rolled back auth-service at 09:25. The error rate returned to normal at 09:28.
Next:     Monitoring until 10:00 UTC, then we'll close the incident.

Resolved — This incident has been resolved. Between 09:00 and 09:28 UTC, some users
couldn't log in. We apologize for the inconvenience.
```text
</details>

**D3.** Инженер из другой команды поменял общий ConfigMap, и у тебя сломался stage.
Напиши ему по-английски: вежливо, но прямо.

<details><summary>Ответ</summary>

🇬🇧
```text
Hi Jonas! Staging for notifications has been broken since 11:20: the change to the shared
`app-config` ConfigMap removed the SMTP_HOST key we depend on. Could we restore that key,
or agree on a new name? For the future, could we ping each other in #platform before
changing shared config? Thanks!
```text
</details>

**D4.** Ревьюер: 🇬🇧 *Why did you hardcode the timeout to 30s? Shouldn't this be
configurable?* На деле 30 с — значение по умолчанию, его можно переопределить в values.
Ответь.

<details><summary>Ответ</summary>

🇬🇧
```text
Good question! 30s is just the default — it can be overridden with `timeout` in values
(see values.yaml, line 42). I'll add a comment there to make it clearer.
```text
</details>

**D5.** Ревьюер резок: 🇬🇧 *This is wrong. Did you even test it?* Ты действительно
не проверил один сценарий. Ответь профессионально.

<details><summary>Ответ</summary>

Не защищаться и не отвечать резкостью; признать то, что правда. 🇬🇧
```text
You're right, I didn't test the case with an empty ConfigMap. I've added a test and
fixed the template in c4d5e6f. Could you take another look?
```text
</details>

**D6.** Англоязычный тимлид в личке: 🇬🇧 *Can you give me a quick status on the migration?*
Сделано 3 из 5 сервисов, осталось 2, блокер — firewall-правила от сетевой команды,
новый срок — четверг.

<details><summary>Ответ</summary>

🇬🇧
```text
Migration status: 3 of 5 services are done (auth, orders, notifications).
Remaining: payments and search. Blocker: we're waiting for firewall rules from the
network team (NET-77). New ETA: Thursday, if we get the rules by Tuesday.
```text
</details>

**D7.** Ты сам сломал stage неудачным изменением в Helm-чарте. Напиши в англоязычный канал.

<details><summary>Ответ</summary>

🇬🇧
```text
Heads-up: I broke staging for linkd-api at 15:10 with a change to the Helm chart
(wrong service port). I'm rolling it back now, ETA 10 minutes.
I'll post here when it's fixed. Sorry for the trouble!
```text
Одно извинение, без самобичевания; главное — что сломано, что делаешь и когда будет.

</details>

---

### Блок E. Вопросы с собеседования


**1.** 🇬🇧 *How do you write a good commit message?*

<details><summary>Ответ</summary>

🇬🇧 *I follow Conventional Commits: a type, an optional scope, and a short subject
   in the imperative mood, like "fix(ci): retry registry push on 5xx errors". If the
   change isn't obvious, I add a body that explains why.*

</details>

**2.** 🇬🇧 *What makes a good pull request?*

<details><summary>Ответ</summary>

🇬🇧 *It's small and focused on one thing. The description explains what, why, how
   to test, and how to roll back, with a link to the ticket. I review my own diff before
   I ask anyone else.*

</details>

**3.** 🇬🇧 *How do you handle disagreements in code review?*

<details><summary>Ответ</summary>

🇬🇧 *I try to understand the reviewer's concern first. If I disagree, I explain my
   reasons and ask what they think. If we can't agree after a couple of comments, we
   jump on a short call and write the outcome in the thread.*

</details>

**4.** 🇬🇧 *How do you communicate during an incident?*

<details><summary>Ответ</summary>

🇬🇧 *Updates in one channel at a regular interval: status, impact, what we're doing,
   and when the next update is. For external updates, I use simple language without
   internal details or guesses about the cause.*

</details>

**5.** 🇬🇧 *How do you work with a remote, distributed team?*

<details><summary>Ответ</summary>

🇬🇧 *I write things down: short daily updates on long tasks, questions in public
   channels, and meeting outcomes in the thread. I always give full context in one
   message, so people in other time zones can answer without a call.*

</details>

**6.** 🇬🇧 *How do you report a bug to another team or an open-source project?*

<details><summary>Ответ</summary>

🇬🇧 *I search for existing issues first, then write a clear title, the versions,
   steps to reproduce, expected and actual behavior, and logs as text. For open source,
   I try to provide a minimal repro.*

</details>

**7.** 🇬🇧 *How do you document your work?*

<details><summary>Ответ</summary>

🇬🇧 *README and how-to guides in the repo, updated in the same MR as the code;
   runbooks for alerts; ADRs for decisions. If I answer the same question twice,
   I write it down.*

</details>

**8.** 🇬🇧 *Tell me about a time you had to explain a technical problem in writing.*

<details><summary>Ответ</summary>

🇬🇧 STAR коротко: *Our builds were slow, and the team lead asked me to find out why.
   I measured each stage and wrote a short summary with the numbers, the cause —
   a cache key tied to the branch name — and two options. The team picked one in the
   thread without a meeting, and build time dropped from 9 to 4 minutes.*

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Пишу коммиты в повелительном наклонении по Conventional Commits
- [ ] ⭐ Описание MR на английском: What / Why / How to test / Risks
- [ ] Отвечаю на ревью по-английски: исправил, не согласен и почему, вынес в задачу
- [ ] Оформил issue по-английски по шаблону
- [ ] ⭐ Пишу в чат вежливо, но прямо: *Could you…?* + причина + срок
- [ ] Пишу апдейт инцидента с правильными временами глаголов
- [ ] Написал короткое письмо с просьбой и датой в первой строке
- [ ] Ставлю артикли и выбираю Present Perfect / Past Simple без подсказок
- [ ] Не использую *kindly revert*, *do the needful*, *informations*, *I'm agree*
