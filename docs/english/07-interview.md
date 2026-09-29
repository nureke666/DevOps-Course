---
title: "07. Собеседование на английском для DevOps-позиции"
description: "Блок → Английский для IT → собеседование."
---

# 07. Собеседование на английском для DevOps-позиции

> Блок → Английский для IT → собеседование.
> Англоязычное интервью — это то же интервью, что в
> [../../DevOps/SoftSkills/09_interview.md](/softskills/09-interview)
> (STAR, банк историй, мотивация — там по существу), только по-английски. Здесь —
> английские формулировки, готовые каркасы ответов, фразы, чтобы думать вслух,
> и ~35 коротких вопросов с примерами ответов.
>
> Технические темы подробно — в интервью блоков (например,
> [../../DevOps/Network/14_url_journey.md](/network/14-url-journey) для
> вопроса про URL). Речь и переспрос — в [05_speaking.md](/english/05-speaking).

---

## 🧭 Что на самом деле проверяют

| Этап | Что звучит | Что оценивают |
|------|------------|---------------|
| HR-скрининг (15–30 мин) | *Tell me about yourself*, *Why DevOps?*, *Salary expectations?* | Можно ли с тобой говорить по-английски без напряжения, мотивация |
| Техническое интервью | *How would you troubleshoot…?*, *Explain…* | Понимание + умение объяснить и рассуждать вслух |
| Behavioral | *Tell me about a time when…* | Поведение в прошлом, структура ответа (STAR) |
| Финал с тимлидом | Всё вместе + твои вопросы | Сможешь ли ты работать в команде каждый день |

> ⭐ Главное: **грамматику и акцент почти не оценивают.** Оценивают, понимаешь ли ты
> вопрос, отвечаешь ли по делу и со структурой, переспрашиваешь ли, когда не понял.
> Ошибка в артикле не провалит интервью. Молчание и ответ не на тот вопрос — провалят.

---

## 🙋 «Tell me about yourself»

Структура — та же, что в [../../DevOps/SoftSkills/09_interview.md](/softskills/09-interview):
**настоящее → прошлое → доказательство → будущее**, 60–90 секунд.

| Часть | 🇬🇧 Фразы | Время |
|-------|-----------|-------|
| Now | *I'm a backend developer at…, working mostly with…* | 15–20 с |
| Before / how I got here | *Over the last few months, I've taken on…*, *I realized that I enjoy…* | 20–30 с |
| Proof | *The best example is…*, *Most recently, I built…* | 20 с |
| Next | *Now I'm looking for a role where…*, *That's why this position caught my attention.* | 15 с |

🇬🇧 Пример для перехода из бэкенда (подставь своё — чужая история рассыпается на
уточняющих вопросах):
```text
I'm a backend developer at &lt;type of company&gt;, working mostly with &lt;stack&gt;.
Over the last few months, I've taken on more and more of the delivery side in my team:
I wrote the Dockerfile and the CI pipeline for our service, set up alerts, and joined
incident reviews. I realized that I enjoy how a service runs in production more than
building new features, so I started studying DevOps in a structured way.
The best proof is my pet project, linkd-platform. It's a small URL shortener with a full
platform around it: GitLab CI, Argo CD, Kubernetes, SLO-based monitoring, and backups
with restore tests. Everything is in a public repo with a README and ADRs.
Now I'm looking for a junior DevOps role where I can work on real infrastructure and
grow into on-call. That's why this position caught my attention: &lt;something specific
from the job description&gt;.
```text
Заметь *I realized that I enjoy* — здесь *realize* в правильном значении «осознал»
([03_vocabulary.md](/english/03-vocabulary)).

Правила: учить **каркас**, а не текст наизусть — заученный текст звучит монотонно
и ломается на первом уточнении; один сильный факт; без биографии; не начинать
с *Sorry for my English*.

### Переход бэкенд → DevOps по-английски

| ✗ Не так | ✓ А так |
|----------|---------|
| *I'm tired of programming.* | *I'm more interested in how services run in production: delivery, reliability, incidents.* |
| *DevOps pays more.* | *I've been taking DevOps tasks in my team for months, and it's the part of the job I enjoy most.* |
| *I just want to try.* | *I've completed a structured roadmap and built a pet project from CI to monitoring — here's the link.* |
| *Backend won't be useful anymore.* | *My backend background helps: I can read application code and stack traces and talk to developers in their language.* |

---

## ⭐ STAR по-английски

| Буква | 🇬🇧 Фразы | Время глагола |
|-------|-----------|---------------|
| **S** — Situation | *At my current job, …*, *Last spring, our team…*, *The build was taking 20 minutes.* | Past Simple, Past Continuous для фона |
| **T** — Task | *My task was to…*, *I was asked to…*, *I volunteered to…* | Past Simple |
| **A** — Action | *First, I… Then I… I decided to… because…* — **I**, а не *we* | Past Simple |
| **R** — Result | *As a result, …*, *This reduced… from X to Y.*, *We haven't had… since.* | Past Simple; Present Perfect — если эффект длится |
| Вывод | *What I learned is…*, *Next time, I'd…* | Present Simple, *would* |

🇬🇧 История «сложная задача» (та же, что в SoftSkills/09, по-английски):
```text
At my current job, the CI build for our notifications service was taking about
20 minutes, and developers were waiting for reviews for half an hour. My team lead
asked me to look into it. First, I measured each stage and found that 12 minutes
went into installing dependencies. There was a cache, but its key depended on the
branch name, so every new branch started with an empty cache. I changed the key
to a hash of the lock file and split the tests into two parallel jobs. As a result,
the build went down to about 7 minutes. What I learned is to measure first and fix
second: I was sure the tests were the problem, but it was the dependencies.
```text
🇬🇧 История «ошибка»:
```text
I deployed a migration that added an index to a large table without CONCURRENTLY,
and it blocked writes for a few minutes, so some requests timed out. I noticed it
from an alert almost immediately, told the team in our channel that it was my
migration, and rolled back the release together with my team lead. Afterwards,
I added a checklist item about blocking migrations to our MR template. The lesson
for me: report it right away, and fix the process, not just your own mistake.
```text
---

## 🧠 Как объяснять технические вещи по-английски

Принцип: **ответ одной фразой → слои деталей → проверка**. После первого слоя спроси
🇬🇧 *Should I go deeper into any part?* — интервьюер сам скажет, что ему интересно.

### «What happens when you type a URL into a browser?»

Полная версия по шагам — [../../DevOps/Network/14_url_journey.md](/network/14-url-journey).
🇬🇧 Ответ за ~60 секунд:
```text
First, the browser parses the URL and checks its caches. Then it resolves the domain
name: it checks the hosts file and its own cache, and if needed, asks a recursive
resolver, which walks from the root servers down to the domain's authoritative server
and caches the answer for the TTL.
With the IP address, the OS picks a route. If the address isn't in the local network,
the packet goes to the default gateway, whose MAC address it learns via ARP.
Then the browser opens a TCP connection with a three-way handshake, and on top of it
a TLS handshake: the client sends the server name via SNI, the server presents its
certificate, the client verifies it, and they agree on session keys.
Inside the encrypted connection, the browser sends an HTTP request with the Host header.
On the server side, it goes through a firewall and a load balancer to a healthy
backend. The app may call a database or a cache, and returns a response.
Finally, the browser renders the HTML and loads the other resources, usually over
the same connection.
```text
### «Explain Kubernetes to a non-technical person»

🇬🇧
```text
Imagine a big restaurant kitchen with a very good manager. You don't tell the manager
which cook should do what. You just say: "I always want three cooks making pizza."
If one cook gets sick, the manager finds a replacement. If there are suddenly a lot
of orders, the manager brings in more cooks, and sends them home when it's quiet.
Kubernetes is that manager for applications. We describe what we want —
"run three copies of this app" — and Kubernetes keeps it that way on a group of servers:
it restarts what crashes, spreads the load, and adds copies when traffic grows.
By the way, the name comes from the Greek word for "helmsman".
```text
### «What's the difference between a container and a virtual machine?»

🇬🇧
```text
A virtual machine virtualizes hardware: a hypervisor runs several VMs, and each one has
its own full operating system and kernel. A container virtualizes at the OS level:
all containers on a host share the host's kernel and are isolated with namespaces
and cgroups.
Because of that, containers are much lighter: they start in seconds and use less memory,
so you can run many more of them on the same machine. VMs give stronger isolation,
and you can run a different OS, for example Windows on a Linux host.
An analogy: VMs are separate houses, each with its own foundation and plumbing.
Containers are apartments in one building: they share the infrastructure but have
their own locked doors.
In practice, we often use both: containers run inside VMs in the cloud.
```text
---

## 💭 Думать вслух

На технических и ситуационных вопросах молчание — худший вариант: интервьюер не видит
твой ход мысли. Говори, что проверяешь и почему.

| Момент | 🇬🇧 Фраза |
|--------|-----------|
| Начать | *Let me think out loud.* / *First, I'd want to understand…* |
| Уточнить условие | *Could I ask a clarifying question?* / *Are we talking about one service or the whole cluster?* |
| Гипотеза | *My first guess would be…* / *It could be… or…* |
| План | *I'd start by checking… If that's not it, the next thing I'd look at is…* |
| Нет опыта | *I haven't used it in production, but I know that…* |
| Не уверен | *I'm not sure, but my understanding is that…* |
| Подвести итог | *So, to summarize my approach: …* |

🇬🇧 Пример: *The website is slow. What do you do?*
```text
First, I'd clarify the scope: is it slow for everyone or for some users, and since when?
Then I'd check what changed recently: deploys, config changes, traffic spikes.
Next, I'd look at the dashboards: latency, traffic, errors, and saturation for the
frontend, the backend, and the database. If the backend latency is high, I'd open
a slow trace to see which span takes the time — often it's a database query or an
external call. Meanwhile, if it started right after a deploy, I'd suggest rolling back
first and investigating after that.
```text
**Если не понял вопрос** — не угадывай:
🇬🇧 *Sorry, could you repeat the question?* · *Do you mean X or Y?* ·
*Just to make sure I got it right: you're asking about…?*

---

## 📚 ~35 коротких вопросов с примерами ответов

> Примеры — каркас. Меняй на свой опыт: интервьюер задаст уточняющий вопрос.

### Мотивация и опыт

1. **Why do you want to move from backend to DevOps?** — *I enjoy the production side
   most: delivery, reliability, incidents. I've been doing DevOps tasks in my team and
   built a full pet project to prove it's a deliberate choice.*
2. **Why this company?** — *You run Kubernetes in production with GitOps, and your
   engineering blog shows a strong incident culture. That's exactly what I want to learn.*
3. **Where do you see yourself in three years?** — *As a mid-level DevOps engineer
   who can own a part of the platform, go on call independently, and mentor juniors.*
4. **What are your strengths?** — *My backend background: I can read code and stack traces.
   I learn fast, and I finish what I start.*
5. **What's your biggest weakness?** — *I don't have much production experience with
   Kubernetes yet. I'm closing the gap with my pet project and by taking on-call shadow
   shifts at work.*
6. **Why should we hire you?** — *I bring a developer's view of the app, a working
   platform I built end to end, and a habit of documenting and communicating clearly.*

### Команда и процесс

7. **How do you work with developers?** — *Like with customers: I try to understand what
   they need and give them an easy, safe path, not just restrictions.*
8. **What do you do when you disagree with your manager?** — *I explain my concerns with
   facts and suggest an alternative. If the decision stays the same, I commit to it and
   we review the results later.*
9. **How do you prioritize when everything is urgent?** — *I compare the impact of each
   task, agree on the order with my lead, and tell the others what will be delayed.*
10. **What do you do when you're stuck?** — *I timebox my own attempt, then ask a specific
    question: what I'm trying to do, what I've tried, and my guess.*
11. **How do you handle feedback?** — *I ask for examples, change what I can, and check
    back later. For example, my lead said my status was unclear, so I started daily
    written updates.*
12. **Have you worked remotely?** — *Yes, partly. I rely on written communication:
    clear messages with context, updates without reminders, decisions written down.*

### Технические вопросы на скрининге

13. **What is DevOps?** — *A culture and a set of practices that bring development and
    operations together to deliver changes quickly and reliably: automation, CI/CD,
    infrastructure as code, monitoring, and shared ownership.*
14. **What is CI/CD?** — *CI means every change is automatically built and tested when
    it's merged. CD means every change that passes the pipeline can be released
    automatically, safely, and often.*
15. **Continuous delivery vs continuous deployment?** — *With continuous delivery, every
    change is ready to release, but a person approves the production deploy. With
    continuous deployment, every change that passes the pipeline goes to production
    automatically.*
16. **What is infrastructure as code?** — *Describing infrastructure in code, like
    Terraform or Ansible, stored in Git and reviewed like any code. It makes environments
    reproducible and changes auditable.*
17. **Image vs container?** — *An image is a read-only template with the app and its
    dependencies. A container is a running instance of an image.*
18. **What is a pod?** — *The smallest deployable unit in Kubernetes: one or more
    containers that share a network namespace and volumes and are scheduled together.*
19. **Deployment vs StatefulSet?** — *A Deployment is for stateless apps: pods are
    interchangeable. A StatefulSet gives each pod a stable name and its own persistent
    volume, and starts pods in order — for databases and similar workloads.*
20. **How do you roll back a bad release in Kubernetes?** — *`kubectl rollout undo
    deployment/&lt;name&gt;` goes back to the previous revision. With GitOps, I revert the
    commit, and Argo CD syncs the cluster.*
21. **Liveness vs readiness probes?** — *If a liveness probe fails, the kubelet restarts
    the container. If a readiness probe fails, the pod is removed from the Service
    endpoints, so it stops getting traffic.*
22. **How do you manage secrets?** — *Never in Git in plain text. A secrets manager like
    Vault, synced into the cluster with something like External Secrets, with access
    by role and regular rotation.*
23. **Blue-green vs canary?** — *Blue-green runs two full environments and switches all
    traffic at once, so rollback is instant. Canary sends a small share of traffic
    to the new version first and increases it gradually.*
24. **What are the four golden signals?** — *Latency, traffic, errors, and saturation,
    from the Google SRE book.*
25. **What is an SLO?** — *A target for a service level indicator over a time window,
    for example "99.9% of requests succeed over 30 days". The gap to 100% is the error
    budget.*
26. **What does OOMKilled mean?** — *The container used more memory than its limit, and
    the kernel killed it; the exit code is 137. I'd check memory usage and the limits,
    and look for a leak.*
27. **TCP vs UDP?** — *TCP is connection-oriented and reliable: ordered delivery with
    retransmissions. UDP has no connection or delivery guarantees, but lower overhead —
    used for DNS, video, and similar.*
28. **What does Terraform state do?** — *It maps the resources in your code to real
    objects in the cloud, so Terraform can calculate what to change. It should be stored
    remotely with locking, and protected, because it can contain secrets.*
29. **What is GitOps?** — *The desired state of the system lives in Git, and an agent in
    the cluster, like Argo CD or Flux, pulls it and keeps the cluster in sync. Changes
    go through merge requests.*

### Инциденты

30. **You get paged at 3 am. What do you do?** — *Acknowledge the page, check the impact
    on the dashboards, check what changed, and follow the runbook. If I can't make
    progress in about 15 minutes, I escalate.*
31. **What is a blameless postmortem?** — *A review that asks how the system allowed
    the failure, not who is to blame. The output is action items with owners and dates.*
32. **Tell me about an incident you were involved in.** — *STAR: what happened, what
    I did, how we mitigated it, what changed afterwards.* Учебный инцидент называй учебным.

### Завершение

33. **What are your salary expectations?** — *Based on the market for this role, I'm
    looking at &lt;range&gt; per month, &lt;net / gross&gt;. I'm also interested in the whole
    package: on-call compensation and learning budget.*
34. **When can you start?** — *My notice period is &lt;two weeks / one month&gt;, so I could
    start on &lt;date&gt;.*
35. **Do you have any questions for us?** — Всегда да — см. ниже.

---

## ❓ Вопросы работодателю

| 🇬🇧 Вопрос | Что узнаёшь |
|------------|-------------|
| *What would success look like in the first three months?* | Ожидания и онбординг |
| *Who would I learn from? Is there a mentor or a buddy?* | Будет ли у кого учиться |
| *How does on-call work: rotation, team size, how often are people paged at night?* | Нагрузка и зрелость |
| *How do you run postmortems?* | Культура blameless |
| *How does career growth work here? Is there a leveling framework?* | Можно ли вырасти |
| *What does your infrastructure look like: cloud or on-prem, Kubernetes in production?* | Реальные задачи |
| *What's the biggest pain point in your infrastructure right now?* | Что ждёт на самом деле |
| *What language does the team use day to day?* | Сколько английского реально нужно |

---

## 💬 Зарплата и оффер: фразы

| Ситуация | 🇬🇧 |
|----------|-----|
| Узнать вилку | *What's the salary range for this position?* |
| Уточнить формат | *Is that gross or net?* / *Is that before or after tax?* |
| Бонусы | *Are there any bonuses or on-call compensation?* |
| Не называть первым | *I'd like to understand the role better first. Could you share the range?* |
| Назвать вилку | *I'm looking for something in the range of X to Y.* |
| Взять время | *Thank you! Could I have a couple of days to think it over?* |
| Письменно | *Could you send me the offer in writing?* |

Подход к цифрам и переговорам — [../../DevOps/SoftSkills/09_interview.md](/softskills/09-interview),
раздел про зарплатные переговоры.

---

## 🚩 Красные флаги англоязычного интервью

| Флаг | Почему плохо | Как правильно |
|------|--------------|---------------|
| *Sorry for my bad English* в начале | Интервьюер начинает искать ошибки | Просто начать отвечать |
| Заученный текст | Монотонно, ломается на уточнении | Учить каркас, говорить своими словами |
| Молчание вместо рассуждения | Не видно хода мысли | *Let me think out loud…* |
| Кивать, не поняв вопрос | Ответ не на тот вопрос | *Do you mean X or Y?* |
| Монолог на 5 минут | Не умеешь выделять главное | 1–2 минуты, потом *Should I go deeper?* |
| Слова-паразиты: *like*, *you know*, *actually* | Звучит неуверенно | Короткая пауза вместо паразита |
| Ложные друзья в рассказе о себе | *I realized CI/CD*, *exploitation of servers* | *Implemented*, *ran in production* |
| Ответы «yes / no» | Нет информации для оценки | Да/нет + пример |

---

## 🧠 Как отвечать: практические приёмы

1. **Каркас, а не текст.** Учишь структуру и ключевые фразы, а слова приходят сами.
2. **Первая фраза — ответ.** Потом детали: так интервьюер не теряется.
3. **1–2 минуты и вопрос-проверка:** *Should I go deeper into any part?*
4. **Past Simple в историях**, *I* в действиях, цифра в результате.
5. **Переспросить — нормально.** Это показывает внимательность, а не слабый английский.
6. **Думать вслух** на технических вопросах: гипотеза → проверка → следующий шаг.
7. **Проговорить вслух заранее** — минимум два тренировочных интервью
   ([06_practice_labs.md](/english/06-practice-labs), лаба 5).
8. **Честно про опыт:** *I haven't used it in production, but…* звучит сильнее выдумки.

---

## ✅ Финальный самоконтроль

- [ ] *Tell me about yourself* — до 90 секунд, своими словами, с одним сильным фактом
- [ ] Переход из бэкенда объясняю по-английски: мотивация, доказательства, польза бэкенд-опыта
- [ ] Три истории STAR по-английски, в Past Simple, с *I* и результатом
- [ ] Объясняю URL, Kubernetes для нетехнического человека и контейнер vs ВМ — каждое до 2 минут
- [ ] Думаю вслух на ситуационных вопросах, переспрашиваю, когда не понял
- [ ] Отвечаю на ~35 коротких вопросов без подготовленного текста
- [ ] Есть 3–4 своих вопроса работодателю на английском
- [ ] Провёл два тренировочных интервью, второе — с живым человеком

➡️ Назад к карте блока: [00_INDEX.md](/english/) · Behavioral на русском:
[../../DevOps/SoftSkills/09_interview.md](/softskills/09-interview) ·
Практика: [06_practice_labs.md](/english/06-practice-labs)
