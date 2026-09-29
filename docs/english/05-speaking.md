---
title: "05. Речь: стендап, созвоны, переспрос, демо"
description: "Блок → Английский для IT → тема 05. Опирается на произношение из"
---

# 05. Речь: стендап, созвоны, переспрос, демо

> Блок → Английский для IT → тема 05. Опирается на произношение из
> [03_vocabulary.md](/english/03-vocabulary) и шаблоны из [04_writing.md](/english/04-writing) — устно
> они те же, только короче. Как задавать вопросы по существу — в
> [../../DevOps/SoftSkills/03_asking_learning.md](/softskills/03-asking-learning),
> как строить демо — в [../../DevOps/SoftSkills/07_review_mentoring.md](/softskills/07-review-mentoring).
>
> **После темы ты умеешь:** провести стендап по формуле yesterday / today / blockers;
> объяснить проблему и попросить помощи; переспросить и проверить, что понял; честно
> сказать, что не понял; выиграть время на подумать; вежливо не согласиться; вести себя
> на созвоне; показать демо со структурой; понимать, какие звуки исправлять первыми;
> тренировать речь каждый день: shadowing, запись себя, клубы, преподаватель, ИИ.

---

## 🗺️ Карта темы

```text
 СИТУАЦИЯ                 ФОРМУЛА                                ГЛАВНАЯ ФРАЗА
 ─────────────────────────────────────────────────────────────────────────────────
 стендап                  yesterday → today → blockers           I'm blocked on…
 объяснить проблему       context → symptom → tried → guess → ask  I've tried X and Y, but…
 не понял                 переспросить, не кивать                Sorry, could you repeat…?
 проверить понимание      перефразировать                        Just to make sure I understand…
 нужно время              честная пауза                          Let me think for a second.
 не согласен              признать → сомнение → вариант → вопрос  I see your point, but…
 демо                     problem → demo → results → next steps  Let me share my screen.
 ─────────────────────────────────────────────────────────────────────────────────
 тренировка: shadowing · запись себя · живой разговор раз в неделю · ИИ — с осторожностью
```text
---

## 1. Речь — не письмо вслух

- **Короче.** Устная фраза — 8–12 слов. Длинное предложение ты потеряешь сам на середине.
- **Указатели** (signposting): *First…*, *The main problem is…*, *So, to sum up…* —
  слушатель не может «перечитать», ему нужны вехи.
- **Главное — повторить.** Имя сервиса, срок, просьбу скажи дважды: в начале и в конце.
- **Понятность важнее грамматики.** Ошибка в артикле не мешает, а неверное ударение
  в ключевом слове или пропуск главной мысли — мешает.
- **Готовые блоки.** Беглость — это не скорость мысли, а запас готовых фраз (*chunks*):
  пока говоришь *Let me check and get back to you*, мозг свободен думать о сути.
- **Акцент — не проблема.** Цель — чтобы тебя понимали с первого раза, а не звучать как
  носитель. В международных командах почти все говорят с акцентом.

---

## 2. Стендап

Формула: **что сделал → что делаю → что мешает**. 30–60 секунд, без деталей реализации.

| Часть | Время глагола | 🇬🇧 Фразы |
|-------|---------------|-----------|
| Вчера | Past Simple | *Yesterday I finished…*, *I fixed…*, *I looked into…* |
| Сегодня | *going to*, *will*, Present Continuous | *Today I'm going to…*, *I'll…*, *I'm working on…* |
| Не успел | Present Continuous + причина | *I'm still working on X. It's taking longer than expected because…* |
| Блокеры | — | *I'm blocked on…*, *I'm waiting for…*, *I need help with…*, *No blockers.* |

🇬🇧 Пример (~40 секунд):
```text
Yesterday I finished the Trivy stage in the CI pipeline and fixed two high
vulnerabilities in the base image.
Today I'm going to add dependency caching and test it on staging.
I'm blocked on access to the new registry. Yerzhan, could you help me with that
after the call?
```text
Если на стендапе задали вопрос, на который нужен долгий ответ:
🇬🇧 *Good question — it's a bit long for stand-up. Let's discuss it right after.*

Асинхронный стендап (текстом в канал) — та же формула, те же времена: удобно готовить
его письменно в понедельник-среду-пятницу по системе из [01_level_and_system.md](/english/01-level-and-system).

---

## 3. Объяснить проблему

Формула: **контекст → симптом → что пробовал → гипотеза → просьба**.

🇬🇧 Пример (~45 секунд):
```text
I'm deploying the notifications service to staging.
The helm upgrade fails with "field is immutable" on the Deployment selector.
I've checked the chart diff: the labels in the selector changed in MR 240.
My guess is that we have to delete the Deployment and install it again.
Before I do that on staging, could you confirm that it's safe?
Or is there a better way?
```text
| Часть | 🇬🇧 Фразы |
|-------|-----------|
| Контекст | *I'm working on…*, *We're trying to…* |
| Симптом | *It fails with…*, *It works locally, but on staging…*, *Since this morning…* |
| Что пробовал | *I've tried X and Y, but…*, *I've already checked…*, *I ruled out…* |
| Гипотеза | *My guess is that…*, *It looks like…*, *I suspect…* |
| Просьба | *Could you confirm…?*, *What would you check next?*, *Is there a better way?* |

---

## 4. Попросить помощи

Сначала таймбокс и попытка сам ([../../DevOps/SoftSkills/03_asking_learning.md](/softskills/03-asking-learning)),
потом — конкретный вопрос.

🇬🇧
- *Do you have 10 minutes today to help me with the Helm chart?*
- *I'm stuck on the ingress config. I've spent an hour on it — could you point me in
  the right direction?*
- *Who would be the best person to ask about the network policies?*
- *Could we pair on this for 15 minutes? I'd like to see how you debug it.*

---

## 5. Переспросить и проверить, что понял

| Цель | 🇬🇧 Фраза |
|------|-----------|
| Попросить подробнее | *Could you elaborate on that?* / *Could you say a bit more about the rollback plan?* |
| Проверить понимание | *Just to make sure I understand: you want the alert on staging too?* |
| Перефразировать | *So, if I understand correctly, we deploy on Monday and remove the flag on Friday?* |
| Уточнить термин | *What do you mean by "hard cutover"?* |
| Попросить пример | *Could you give me an example?* |
| Уточнить ожидания | *What does "done" look like for this task?* / *When do you need it by?* |

> ⭐ Перефразирование — главный инструмент: ты проверяешь и язык, и смысл. Если понял
> не так, тебя поправят сразу, а не через неделю работы.

---

## 6. Когда не понял

**Главное правило: не кивать.** «Ок, понял» при непонимании — это задача, сделанная
не так, и потеря доверия потом.

| Проблема | 🇬🇧 Фраза |
|----------|-----------|
| Не расслышал | *Sorry, could you say that again?* / *Sorry, I didn't catch that.* |
| Слишком быстро | *Could you speak a bit more slowly, please?* |
| Плохая связь | *Sorry, you're breaking up. Could you repeat the last part?* |
| Незнакомое слово | *Sorry, what does "backfill" mean here?* |
| Не расслышал имя или термин | *Could you spell that?* / *Could you type it in the chat?* |
| Не понял целиком | *Sorry, I'm not sure I followed. Could you explain it another way?* |

После созвона — итог в чат: 🇬🇧 *Thanks for the call! To summarize: … Please correct
me if I missed anything.* Это и страховка от непонимания, и практика письма.

---

## 7. Выиграть время и думать вслух

Вместо «эээ» и паузы в тишине — фразы, которые звучат естественно:

| Ситуация | 🇬🇧 Фраза |
|----------|-----------|
| Нужно подумать | *Let me think for a second.* / *That's a good question.* |
| Подбираешь слова | *How can I put it…* / *What I mean is…* |
| Ответ не точный | *Off the top of my head, about 200 RPS — but I'd need to check.* |
| Не уверен | *I'm not 100% sure, but I think…* |
| Не знаешь | *I don't know, but I'll find out and get back to you by tomorrow.* |
| Хочешь вернуться к мысли | *Going back to what Aliya said…* |

⚠️ Пообещал *get back to you* — вернись. Одно невыполненное «уточню» стоит дороже, чем
честное «не знаю».

---

## 8. Вежливо не согласиться

Структура: **признать → сомнение с причиной → альтернатива → вопрос**.

🇬🇧
```text
I see your point about speed, but I'm worried about the rollback: with a big-bang
migration, we can't go back quickly. What if we move one service first and see
how it goes?
```text
| ✗ Слишком резко | ✓ Нормально | ✗ Слишком мягко (не услышат) |
|-----------------|-------------|------------------------------|
| *That's wrong.* | *I see it differently.* / *I'm not sure that's right, because…* | *Maybe, I don't know, it's probably fine…* |
| *No, we can't do it.* | *I don't think we can do it by Friday. What we can do is…* | *OK…* (и молчать) |
| *Bad idea.* | *Have we considered…?* / *What if we…?* | |
| *You didn't think about X.* | *One thing I'm worried about is X.* | |

Полезно: *I might be wrong, but…*, *That's a fair point. At the same time…*,
*Could we try it on staging first?*, *I'd suggest… instead, because…*

---

## 9. Фразы для созвонов

| Момент | 🇬🇧 Фраза |
|--------|-----------|
| Связь | *Can you hear me?* / *You're on mute.* / *I think we lost Daniyar.* |
| Экран | *Let me share my screen. Can everyone see it?* |
| Опоздал / уходишь | *Sorry I'm late.* / *Sorry, I have to drop off in five minutes.* |
| Вставить слово | *Can I add something?* / *Sorry to interrupt, but…* |
| Вернуть слово | *Sorry, go ahead.* / *You were saying…?* |
| Спросить мнение | *Aliya, what do you think?* |
| Ссылка | *Let me drop a link in the chat.* |
| Не по теме | *Let's take this offline.* / *Can we park this for now?* |
| Итог | *So, to sum up: …* / *Let's recap the action items.* |
| Задачи | *I'll take that.* / *Who's going to own this?* / *What's the deadline?* |
| Завершить | *I think that's it. Thanks, everyone!* / *I'll follow up in the thread.* |

---

## 10. Демо и короткая презентация

Структура (подробнее о демо — [../../DevOps/SoftSkills/07_review_mentoring.md](/softskills/07-review-mentoring)):

```text
 1. Problem       что было плохо, одной фразой с цифрой        30 с
 2. What I built  что сделал, одной фразой                      30 с
 3. Demo          показать главное, а не всё                    3–5 мин
 4. Results       цифры: было → стало                          30 с
 5. Next steps    что дальше, что нужно от слушателей           30 с
 6. Questions     вопросы
```text
| Этап | 🇬🇧 Фразы |
|------|-----------|
| Начало | *Today I'd like to show you our new deploy pipeline.* |
| Проблема | *Before, a deploy took 40 minutes, and rollback was manual.* |
| Переходы | *Let's start with…*, *Moving on to…*, *Now let's look at…* |
| Показ | *As you can see here…*, *Notice that…*, *If I click here…* |
| Что-то сломалось | *Looks like the demo isn't cooperating. Let me show you a recording instead.* |
| Итог | *To wrap up: deploys now take 5 minutes, and rollback is one command.* |
| Вопросы | *Any questions?* / *Great question.* / *I don't know, but I'll find out and follow up.* |

---

## 11. Произношение: что исправлять первым

Цель — понятность. Эти ошибки чаще всего мешают понять русскоговорящего:

| Проблема | Пары для тренировки | Совет |
|----------|---------------------|-------|
| *th* как «з», «с», «ф» | *think / sink*, *three / free*, *with* | Кончик языка между зубами |
| *w* как «в» | *west / vest*, *wait*, *network* | Губы трубочкой, как «у» |
| Долгие и краткие гласные | *ship / sheep*, *full / fool*, *live / leave* | Долгие — тянуть |
| Оглушение конечных звонких | *log / lock*, *bad / bat*, *need / neat* | Звонкий в конце звонкий; гласный перед ним длиннее |
| *h* как «х» | *host*, *hotfix*, *HTTP* | Лёгкий выдох, без хрипа |
| Окончание *-ed* | *fixed* [t], *deployed* [d], *started* [ɪd] | [ɪd] только после t и d |
| Ударение | *deVELop*, *comPOnent*, *enVIronment* | Проверять со словом ([03_vocabulary.md](/english/03-vocabulary)) |
| Интонация | *Is it down?* ↗ · *Why is it down?* ↘ | Да/нет — вверх, вопрос со словом — вниз |

*Log* и *lock* — хороший тест: скажи *check the log* так, чтобы не услышали *check
the lock*.

---

## 12. Как тренировать речь

| Метод | Как | Зачем |
|-------|-----|-------|
| **Shadowing** | Повторять за спикером вслух с задержкой в полсекунды | Ритм, интонация, беглость |
| **Запись себя** | Стендап, объяснение темы, ответ на вопрос — 1–2 минуты, переслушать | Видишь свои паузы и ошибки |
| **Разговор с собой** | Во время работы описывать вслух, что делаешь: *Now I'm checking the pod logs…* | Бесплатная ежедневная практика |
| **Разговорный клуб** | Офлайн в городе или онлайн, раз в неделю | Живые люди, разные акценты |
| **Преподаватель** | italki, Preply и похожие; лучше с опытом Business или IT English | Исправляет то, чего не слышишь сам |
| **Языковой обмен** | Tandem, HelloTalk: ты помогаешь с русским, тебе — с английским | Бесплатно, но нужна дисциплина |
| **ИИ в голосовом режиме** | Мок-стендап, мок-интервью, вопросы по теме | Объём речи без стеснения |
| **Работа** | Вызваться на международный созвон, демо на английском | Реальная ставка — быстрее рост |

### Shadowing по шагам

```text
 1. Клип 1–2 минуты с транскриптом (доклад, подкаст, туториал)
 2. Послушать целиком, понять смысл, разобрать незнакомые слова
 3. Повторять вслух по фразе — с паузой, глядя в транскрипт
 4. Повторять одновременно со спикером, с задержкой ~0,5 с, без транскрипта
 5. Записать себя, сравнить с оригиналом, повторить трудные места
```text
### Как работать с преподавателем

- Приноси **свой материал**: стендап, объяснение Kubernetes, «Tell me about yourself».
- Проси вести **список твоих ошибок** и присылать после урока — это готовые карточки Anki.
- Раз в месяц — **мок-интервью** на английском с разбором.

### ИИ как собеседник — с осторожностью

- Хорош для объёма: не устаёт, не осуждает, можно в 11 вечера.
- Плохо ловит ошибки произношения и иногда хвалит там, где надо поправить.
- ⚠️ Не рассказывать рабочие детали: имена клиентов, адреса, инциденты под NDA.
- Произношение — сверять с записью себя и с преподавателем.

---

## 13. Грабли

| Грабля | Последствие | Как правильно |
|--------|-------------|---------------|
| Кивать, когда не понял | Задача сделана не так | Переспросить, перефразировать, итог — в чат |
| Читать стендап с листа | Монотонно, ломаешься на первом вопросе | Три опорных слова вместо текста |
| Длинные сложные фразы | Теряешь нить сам | 8–12 слов, указатели *First…*, *So…* |
| Молчать на созвонах | Тебя не слышат, навык не растёт | Одна реплика на каждой встрече |
| Извиняться за английский | Слушатели ищут ошибки вместо смысла | Просто говорить, переспрашивать при нужде |
| Ждать, когда станет не страшно | Страх уходит только от практики | Запись себя с первого дня, потом люди |
| Учить звуки по отдельности без контекста | В речи всё возвращается | Пары слов и фразы из работы |
| Только ИИ-собеседник | Не привыкаешь к живым акцентам и перебиваниям | Живой разговор хотя бы раз в неделю |
| *I'll get back to you* — и не вернуться | Теряется доверие | Записать и вернуться в срок |
| Спорить прямо: *That's wrong* | Звучит грубо | Признать → сомнение → вариант → вопрос |

---

## 💼 Как это в DevOps

- Стендап и созвоны по инцидентам — ежедневная устная практика в международной команде.
  Короткая речь по формуле ценится выше красивой.
- На инцидент-бридже важно переспрашивать и подтверждать: *Just to confirm, I'm rolling
  back payments now.* Ошибка понимания здесь стоит минут простоя.
- DevOps-инженер часто объясняет разработчикам и менеджерам, как устроена платформа:
  демо со структурой — навык, который замечают.
- На собесе оценивают не акцент, а умение объяснить и переспросить — об этом
  [07_interview.md](/english/07-interview).

---

## 📌 Шпаргалка

| Ситуация | 🇬🇧 Главная фраза |
|----------|--------------------|
| Стендап | *Yesterday I… Today I'm going to… I'm blocked on…* |
| Объяснить проблему | *I've tried X and Y, but… My guess is… Could you confirm…?* |
| Попросить помощи | *Could you point me in the right direction?* |
| Уточнить | *Could you elaborate on that?* |
| Проверить понимание | *Just to make sure I understand: …* |
| Не понял | *Sorry, could you say that again? / Could you type it in the chat?* |
| Нужно время | *Let me think for a second.* |
| Не знаю | *I don't know, but I'll find out and get back to you.* |
| Не согласен | *I see your point, but… What if we…?* |
| Демо | Problem → What I built → Demo → Results → Next steps |
| Звуки первыми | th, w, долгие гласные, звонкие в конце (*log / lock*), *-ed* |
| Тренировка | Shadowing, запись себя, клуб или преподаватель раз в неделю |

---

## 🧠 Что запомнить

1. ⭐ Устная речь — короткие фразы и указатели, а не письмо вслух.
2. Стендап: Past Simple → *going to* → блокеры; 30–60 секунд без деталей.
3. Проблему объясняют по формуле: контекст → симптом → что пробовал → гипотеза → просьба.
4. ⭐ Не понял — переспроси; понял — перефразируй, чтобы проверить.
5. Пауза с фразой *Let me think for a second* лучше «эээ» и лучше выдуманного ответа.
6. ⭐ Не соглашаются через признание, причину и альтернативу.
7. Демо: проблема → решение → показ главного → цифры → что дальше.
8. Понятность важнее акцента; исправляй то, что мешает понять: th, w, *log / lock*, ударение.
9. ⭐ Беглость — это запас готовых фраз; shadowing и запись себя их набирают.
10. Живой разговор раз в неделю обязателен: ИИ не заменяет людей и их акценты.

➡️ Дальше: [06_practice_labs.md](/english/06-practice-labs) · задачи: 05_speaking_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Чем устная речь отличается от письма? Назови четыре приёма, которые делают
речь понятнее.

<details><summary>Ответ</summary>

Устная фраза короче, её нельзя перечитать, поэтому нужны вехи. Приёмы: короткие
фразы (8–12 слов); указатели (*First…*, *So, to sum up…*); повтор главного в начале
и конце; готовые фразы-блоки; понятность важнее грамматики.

</details>

**A2.** Почему беглость — это запас готовых фраз, а не скорость мысли?

<details><summary>Ответ</summary>

Пока говоришь заученный блок (*Let me check and get back to you*), мозг свободен
думать о сути. Без запаса блоков каждую фразу приходится строить с нуля — отсюда паузы.

</details>

**A3.** ⭐ Из каких частей состоит стендап? Какие времена глаголов в каждой части?

<details><summary>Ответ</summary>

Вчера — Past Simple (*I finished*); сегодня — *going to* / *will* / Present
Continuous (*I'm going to add…*); блокеры — *I'm blocked on… / I'm waiting for… /
No blockers.*

</details>

**A4.** По какой формуле объясняют проблему? Приведи по одной английской фразе на каждую
часть.

<details><summary>Ответ</summary>

Контекст (*I'm working on…*) → симптом (*It fails with…*) → что пробовал
(*I've tried X and Y, but…*) → гипотеза (*My guess is that…*) → просьба (*Could you
confirm…?*).

</details>

**A5.** ⭐ Как переспросить и как проверить, что понял? Почему перефразирование — главный
инструмент?

<details><summary>Ответ</summary>

*Could you elaborate on that?*, *What do you mean by…?*, *Just to make sure
I understand: …*, *So, if I understand correctly, …* Перефразирование проверяет сразу
и язык, и смысл: если понял не так, поправят сейчас, а не после недели работы.

</details>

**A6.** Что делать, если на созвоне не понял? Назови четыре фразы. Что сделать после
созвона?

<details><summary>Ответ</summary>

*Sorry, could you say that again?*, *Could you speak a bit more slowly?*,
*Sorry, you're breaking up*, *Could you type it in the chat?* После — итог в чат
с просьбой поправить, если что-то упустил.

</details>

**A7.** Как выиграть время на подумать? Чем опасно *I'll get back to you*?

<details><summary>Ответ</summary>

*Let me think for a second.*, *That's a good question.*, *Off the top of my
head…*, *I'm not 100% sure, but…* Опасность: пообещал вернуться и не вернулся — потеря
доверия.

</details>

**A8.** ⭐ Как вежливо не согласиться? Из каких четырёх шагов состоит структура?

<details><summary>Ответ</summary>

Признать позицию → сомнение с причиной → альтернатива → вопрос. *I see your point,
but I'm worried about X. What if we…?*

</details>

**A9.** Назови по фразе на каждый момент созвона: связь, экран, вставить слово, итог,
завершение.

<details><summary>Ответ</summary>

*Can you hear me? / You're on mute.* — *Let me share my screen. Can everyone see
it?* — *Can I add something? / Sorry to interrupt, but…* — *So, to sum up… / Let's recap
the action items.* — *I think that's it. Thanks, everyone!*

</details>

**A10.** Из каких частей состоит демо? Что сказать, если демо сломалось?

<details><summary>Ответ</summary>

Problem → What I built → Demo → Results → Next steps → Questions. Если сломалось:
*Looks like the demo isn't cooperating. Let me show you a recording instead.*

</details>

**A11.** ⭐ Какие пять особенностей произношения русскоговорящих мешают пониманию сильнее
всего?

<details><summary>Ответ</summary>

*th* как «з/с»; *w* как «в»; нет разницы между долгими и краткими гласными;
оглушение звонких на конце (*log* → *lock*); неверное ударение (*DEvelop*). Ещё: *h*
как «х», *-ed* всегда как [ɪd].

</details>

**A12.** Как делать shadowing? Как использовать преподавателя и ИИ-собеседника?

<details><summary>Ответ</summary>

Shadowing: клип 1–2 минуты с транскриптом → понять → повторять по фразе →
повторять синхронно с задержкой → записать себя и сравнить. Преподавателю — свой
материал и просьба о списке ошибок; ИИ — для объёма речи, без рабочих данных, произношение
сверять отдельно.

</details>

---

### Блок B. «Что тут не так»


Расшифровки устной речи. Найди ошибки и скажи правильно.

**B1.** 🇬🇧 Стендап: *Yesterday I have worked on CI. Today I will continue to work on CI.
Blockers — no.*

<details><summary>Ответ</summary>

⚠️ *Yesterday* + Present Perfect; «работал над CI» — процесс без результата;
*Blockers — no* — калька. ✓ *Yesterday I added the test stage to the CI pipeline. Today
I'm going to set up caching. No blockers.*

</details>

**B2.** 🇬🇧 *I am blocking by access to registry.*

<details><summary>Ответ</summary>

⚠️ *I am blocking* — «я блокирую»; нужен пассив и артикль. ✓ *I'm blocked —
I'm waiting for access to the registry.*

</details>

**B3.** На созвоне ничего не понял про новый процесс релизов, но ответил: 🇬🇧 *Yes, yes,
OK, I understood.*

<details><summary>Ответ</summary>

⚠️ Кивать при непонимании — главная ошибка. ✓ *Sorry, I'm not sure I followed
the part about release branches. Could you explain it once more?* После — итог в чат.

</details>

**B4.** 🇬🇧 *Repeat please.*

<details><summary>Ответ</summary>

⚠️ Звучит как приказ. ✓ *Sorry, could you repeat that, please?*

</details>

**B5.** 🇬🇧 *No, this is bad idea, we must do it my way.*

<details><summary>Ответ</summary>

⚠️ Резко, без причины, нет артикля. ✓ *I'm not sure it's the best option,
because rollback would take hours. What if we try it on one service first?*

</details>

**B6.** 🇬🇧 Сеньору: *Help me with helm, it is not working.*

<details><summary>Ответ</summary>

⚠️ Приказ, нет контекста. ✓ *Do you have 10 minutes to help me with the Helm
chart? The upgrade fails with "field is immutable", and I've already checked the diff.*

</details>

**B7.** 🇬🇧 *What you mean?*

<details><summary>Ответ</summary>

⚠️ Нет вспомогательного глагола. ✓ *What do you mean?* / *What do you mean
by "cutover"?*

</details>

**B8.** 🇬🇧 *So, yesterday I start to deploy and then was error, and I tried many things
and nothing, maybe it's network, I don't know, what to do?*

<details><summary>Ответ</summary>

⚠️ Хронология без структуры; *I start* → *I started*; *was error* →
*there was an error*; *what to do?* — вопрос без адресата. ✓ *Yesterday I started the
deploy to staging, and it failed with a timeout. I've checked the pods and the image —
both look fine. My guess is a network policy. Could you help me check it?*

</details>

**B9.** 🇬🇧 Начало демо: *Hello, now I will show you everything about our pipeline, it will
take 30 minutes.*

<details><summary>Ответ</summary>

⚠️ «Всё» за 30 минут — никто не досидит; нет проблемы и цели. ✓ *Today I'd like
to show you how our new pipeline cut deploy time from 40 to 5 minutes. It'll take about
five minutes, and then questions.*

</details>

**B10.** 🇬🇧 *Sorry for my bad English, I will try to explain.*

<details><summary>Ответ</summary>

⚠️ Принижает себя и заставляет слушателей искать ошибки. ✓ Просто начать:
*Let me explain how it works.*

</details>

**B11.** 🇬🇧 Перебивая коллегу: *Wait, wait, I want to say!*

<details><summary>Ответ</summary>

⚠️ Грубо, нет *something*. ✓ *Sorry to interrupt — can I add something?*

</details>

**B12.** На вопрос интервьюера — 15 секунд тишины, потом: 🇬🇧 *Eeeh… hmm… I don't know.*

<details><summary>Ответ</summary>

⚠️ Тишина и «не знаю» без попытки. ✓ *That's a good question. Let me think for
a second… I haven't worked with it directly, but I'd start by checking…*

</details>

**B13.** Как это прозвучало (русскими буквами): «Ай чекд зе лок фор эррорс»,
а хотел сказать 🇬🇧 *I checked the log for errors.*

<details><summary>Ответ</summary>

⚠️ *th* → «з»; оглушённое *g* превратило *log* в *lock*; *checked* здесь
верно — [t]. ✓ Межзубный *th* в *the*, звонкое *g* и чуть более долгий гласный в *log*.

</details>

---

### Блок C. Практика


### C1. 🔑 Пять стендапов
Пять рабочих дней подряд записывай стендап на 30–60 секунд. Не текст, а **три опорных
слова** на бумажке. В пятницу переслушай все пять: времена глаголов, паузы, слова-паразиты,
длина.

### C2. 🔑 Объяснить реальную проблему
Возьми проблему, с которой застревал на этой неделе, и объясни её вслух за 45–60 секунд
по формуле: context → symptom → what I tried → my guess → ask. Запиши, переслушай,
запиши второй раз.

### C3. Shadowing на 5 дней
Выбери 1–2 минуты доклада KubeCon с английскими субтитрами. 10 минут в день по шагам
из раздела 12. Запиши себя в первый и в пятый день, сравни.

### C4. Смягчить
Скажи вежливо, но прямо:
**1.** 🇬🇧 *Explain this again.*

<details><summary>Ответ</summary>

*Just to make sure I understand: no deploys from Thursday evening until the migration
   is done?*

</details>

**2.** 🇬🇧 *Your plan is bad.*

<details><summary>Ответ</summary>

*So I own alerting, and I keep Aliya updated — right?*

</details>

**3.** 🇬🇧 *I can't do it by Friday.*

<details><summary>Ответ</summary>

*So we start the canary in the EU region only, and the rest later?*

</details>

**4.** 🇬🇧 *You're speaking too fast.*

<details><summary>Ответ</summary>

*Just to make sure: the idea is fine, but the ticket should be smaller — should I
   split it?*

</details>

**5.** 🇬🇧 *Give me the link.*

<details><summary>Ответ</summary>

*So the hard deadline is the audit, and the target is early next week?*

</details>

**6.** 🇬🇧 *We don't need to discuss it now.*

<details><summary>Ответ</summary>

*Maybe we could take this offline and discuss it after the call?*

</details>

### C5. Перефразировать
Для каждой реплики скажи проверочную фразу *Just to make sure I understand…*:
**1.** 🇬🇧 *We'll freeze deploys from Thursday evening until the migration is done.*

<details><summary>Ответ</summary>

*Just to make sure I understand: no deploys from Thursday evening until the migration
   is done?*

</details>

**2.** 🇬🇧 *Can you own the alerting part, but keep Aliya in the loop?*

<details><summary>Ответ</summary>

*So I own alerting, and I keep Aliya updated — right?*

</details>

**3.** 🇬🇧 *Let's go with the canary, but only for the EU region at first.*

<details><summary>Ответ</summary>

*So we start the canary in the EU region only, and the rest later?*

</details>

**4.** 🇬🇧 *The ticket is fine, just scope it down a bit.*

<details><summary>Ответ</summary>

*Just to make sure: the idea is fine, but the ticket should be smaller — should I
   split it?*

</details>

**5.** 🇬🇧 *We need it before the audit, ideally early next week.*

<details><summary>Ответ</summary>

*So the hard deadline is the audit, and the target is early next week?*

</details>

### C6. Произношение
Запиши пары: *log / lock*, *ship / sheep*, *think / sink*, *west / vest*, *need / neat*.
Распредели окончания *-ed* по звукам [t], [d], [ɪd] и произнеси вслух: *fixed, deployed,
started, pushed, merged, restarted, rolled, updated, stopped, scaled*.

### C7. 🔑 План демо
Подготовь по-английски план 5-минутного демо пайплайна linkd (коммит → CI → Argo CD →
кластер): фраза на каждый этап структуры из раздела 10, переходы, что скажешь, если
что-то сломается. Проведи демо на запись.

### C8. Живой разговор
Одна встреча в разговорном клубе или с преподавателем. Принеси свой стендап и объяснение
«What is Kubernetes?». Попроси список своих ошибок — и сделай из него карточки Anki.

---

### Блок D. Инциденты


**D1.** Бридж инцидента на английском. IC: 🇬🇧 *Daniyar, can you roll back payments to the
previous version and confirm?* Ты — Данияр, и не уверен, какая версия «предыдущая»:
вчера было два релиза.

<details><summary>Ответ</summary>

Подтвердить, прежде чем делать. 🇬🇧 *Sure. Just to confirm: there were two
releases yesterday. Do you mean 2.14, the one from this morning, or 2.13 from yesterday
afternoon?* После отката: *Payments is rolled back to 2.13. Error rate is going down.*

</details>

**D2.** Коллега говорит быстро и с сильным акцентом; ты пропустил главное — срок.

<details><summary>Ответ</summary>

🇬🇧 *Sorry, I missed the part about the deadline. Could you repeat it? When do
you need it by?* После созвона: *To confirm: the deadline is Thursday, Oct 9 — right?*

</details>

**D3.** На стендапе менеджер: 🇬🇧 *Why is the migration delayed again?* Причина — ждёте
firewall-правила от сетевой команды. Ответь за 30 секунд.

<details><summary>Ответ</summary>

🇬🇧
```text
We're still waiting for the firewall rules from the network team. Everything else
is ready: three of five services are already moved. I've escalated it to their lead
today. If we get the rules by Tuesday, we'll finish on Thursday.
```text
</details>

**D4.** Сеньор предлагает на созвоне перевезти все сервисы за одни выходные. Ты считаешь
это рискованным: откат долгий, если что-то пойдёт не так. Скажи это.

<details><summary>Ответ</summary>

🇬🇧
```text
I see the benefit of doing it in one go, but I'm worried about rollback: if something
goes wrong on Sunday night, moving everything back would take hours. What if we move
one low-risk service this weekend and the rest next week?
```text
</details>

**D5.** Во время демо пайплайн падает в прямом эфире.

<details><summary>Ответ</summary>

Спокойно, без долгих извинений. 🇬🇧 *Looks like the demo isn't cooperating —
the runner seems to be down. Let me show you a recording from this morning instead,
and I'll share the fix in the channel later.*

</details>

**D6.** На архитектурном ревью тебя спрашивают: 🇬🇧 *How does Istio rotate mTLS
certificates?* Ты не знаешь.

<details><summary>Ответ</summary>

🇬🇧 *I don't know how Istio handles that in detail. My understanding is that
istiod issues short-lived certificates to the sidecars, but I'd need to check how
rotation works. I'll look it up and share it in the thread by tomorrow.* — и вернуться.

</details>

**D7.** Ты подключился к созвону на 10 минут позже, обсуждение в разгаре, и тебя
спрашивают мнение.

<details><summary>Ответ</summary>

🇬🇧 *Sorry I'm late. I missed the beginning — could someone give me a quick
summary, or should I catch up after the call?* Если мнение нужно сейчас: *From what
I've heard so far, … but I may be missing context.*

</details>

---

### Блок E. Вопросы с собеседования


**1.** 🇬🇧 *How do you give a status update to your team?*

<details><summary>Ответ</summary>

🇬🇧 *I keep it short: what I did yesterday, what I'm doing today, and what's blocking
   me. For longer tasks, I also post a short written update at the end of the day,
   so nobody has to ask.*

</details>

**2.** 🇬🇧 *How do you explain a complex technical issue to someone less technical?*

<details><summary>Ответ</summary>

🇬🇧 *I start with the impact, not the technology: what users see, how much it costs,
   and what we can do. I use a simple analogy, check if it makes sense, and leave
   the details for questions.*

</details>

**3.** 🇬🇧 *What do you do when you disagree with a senior engineer?*

<details><summary>Ответ</summary>

🇬🇧 *I explain my concern with facts, not opinions, and suggest an alternative.
   I also ask questions — often they know something I don't. If the decision goes
   the other way, I support it and we check the results later.*

</details>

**4.** 🇬🇧 *How do you ask for help when you're stuck?*

<details><summary>Ответ</summary>

🇬🇧 *First, I timebox my own attempt. Then I ask a specific question: what I'm trying
   to do, what I've tried, what I see, and my guess. I ask in the team channel, so
   the answer helps others too.*

</details>

**5.** 🇬🇧 *Tell me about a presentation or a demo you gave.*

<details><summary>Ответ</summary>

🇬🇧 STAR коротко: *I demoed our new CI pipeline to the backend team. I started with
   the problem — 40-minute deploys — showed one change going to staging, and finished
   with the numbers. The pipeline failed during the demo, so I switched to a recording.
   Two teams asked to move to it the next week.*

</details>

**6.** 🇬🇧 *How do you make sure everyone is on the same page after a meeting?*

<details><summary>Ответ</summary>

🇬🇧 *At the end, I recap the decisions and action items with owners and dates, and
   then post the same summary in the channel. If I'm not sure I understood something,
   I rephrase it during the meeting.*

</details>

**7.** 🇬🇧 *What would you do if you didn't understand a task you were given?*

<details><summary>Ответ</summary>

🇬🇧 *I'd ask right away rather than guess: I'd rephrase the task to check my
   understanding and ask what "done" looks like and when it's needed. Then I'd write
   it down in the ticket.*

</details>

**8.** 🇬🇧 *What do you do when someone asks you something you don't know in a meeting?*

<details><summary>Ответ</summary>

🇬🇧 *I say honestly that I don't know, share what I do know or how I'd find out,
   and promise to follow up by a specific time. Then I actually follow up.*

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Записал пять стендапов подряд, последний — без текста, до 60 секунд
- [ ] Объясняю реальную проблему по формуле за 45–60 секунд
- [ ] ⭐ Переспрашиваю и перефразирую вместо «OK, I understood»
- [ ] Не соглашаюсь через признание, причину и альтернативу
- [ ] Знаю фразы для созвона: связь, экран, вставить слово, итог
- [ ] Провёл демо по структуре на английском (на запись или вживую)
- [ ] Тренировал пары *log / lock*, *think / sink*, *west / vest* и окончания *-ed*
- [ ] Пять дней shadowing, записи первого и пятого дня сравнены
- [ ] ⭐ Была хотя бы одна живая разговорная практика со списком своих ошибок
