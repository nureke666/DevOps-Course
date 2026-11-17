---
title: "2. Строительные блоки"
description: "DNS, CDN и балансировщики, API, кеш, выбор хранилища, масштабирование БД, очереди и события, файлы и поиск, rate limiting — как работает и как эксплуатировать"
---

<script setup>
import RoadmapChain from '../../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  {"title": "01. Вход в систему: DNS, CDN, балансировщики и API gateway", "desc": "Путь запроса от клиента до сервиса, DNS и GeoDNS, CDN для статики и динамики, L4 и L7, алгоритмы балансировки, health checks, API gateway, ingress и mesh", "status": "active", "link": "/system-design/building-blocks/01-edge-dns-cdn-lb"},
  {"title": "02. API: REST, gRPC, GraphQL, WebSocket и SSE", "desc": "Ресурсы и методы, коды ответов, версии, пагинация, идемпотентность и ошибки, gRPC и GraphQL, real-time: polling, SSE, WebSocket, вебхуки, совместимость и эксплуатация API", "status": "active", "link": "/system-design/building-blocks/02-api-design"},
  {"title": "03. Кеширование: где, как и когда кеш врёт", "desc": "Уровни кеша, cache-aside, read-through, write-through и write-behind, TTL и инвалидация, stampede и горячие ключи, вытеснение, hit ratio в числах, отказ кеша и эксплуатация Redis", "status": "active", "link": "/system-design/building-blocks/03-caching"},
  {"title": "04. Хранилища: SQL или NoSQL, B-tree или LSM", "desc": "Модели данных и типы хранилищ, выбор от паттернов доступа, индексы B-tree и LSM, строчное и колоночное хранение, OLTP и OLAP, PostgreSQL по умолчанию и когда от него уходить", "status": "active", "link": "/system-design/building-blocks/04-storage-choice"},
  {"title": "05. Масштабирование БД: от индекса до шардов", "desc": "Лестница роста: запросы и индексы, вертикальный рост, пул соединений, реплики чтения, кеш, партиционирование, разделение по сервисам, шардирование, ключ шарда и решардинг", "status": "active", "link": "/system-design/building-blocks/05-db-scaling"},
  {"title": "06. Асинхронность: очереди, pub/sub и события", "desc": "Синхронно или асинхронно, очередь задач, pub/sub и лог событий, порядок и партиции, ретраи, DLQ и идемпотентные потребители, outbox, выбор брокера и эксплуатация", "status": "active", "link": "/system-design/building-blocks/06-async-messaging"},
  {"title": "07. Файлы и поиск: объектное хранилище и инвертированный индекс", "desc": "Объектное хранилище, загрузка по presigned URL и multipart, метаданные в БД, классы хранения и CDN, полнотекстовый поиск, инвертированный индекс, Elasticsearch и синхронизация с БД", "status": "active", "link": "/system-design/building-blocks/07-blobs-search"},
  {"title": "08. Rate limiting: алгоритмы и где ставить лимиты", "desc": "Зачем ограничивать, по какому ключу, fixed и sliding window, token bucket и leaky bucket, распределённый лимитер на Redis, слои лимитов, 429 и Retry-After, квоты", "status": "active", "link": "/system-design/building-blocks/08-rate-limiting"},
]
</script>

# 2. Строительные блоки

Детали, из которых собирается почти любая схема на собесе и в design doc. Для каждого блока —
как он работает, когда его брать и когда нет, какие у него компромиссы и как его держать в
проде: в каждой теме есть раздел «⚙️ Эксплуатация» из тех же 7 вопросов, что и в задачах.

> Блок → [System Design](/system-design/) → 2. Строительные блоки. Опирается на
> [1. Основы и метод](/system-design/basics/). Теорию, которая уже подробно разобрана на сайте
> (DNS и HTTP, репликация и консистентное хеширование, Kafka и гарантии доставки), здесь
> не повторяем — на неё стоят ссылки.

```text:no-line-numbers
 клиент ──► DNS ──► CDN ──► балансировщик ──► API gateway ──► сервис        темы 01, 02, 08
                                                                 │
                                         ┌───────────────────────┼──────────────────────┐
                                         ▼                       ▼                      ▼
                                       кеш                   база данных          очередь/события
                                     тема 03              темы 04, 05              тема 06
                                                                 │
                                                                 ▼
                                                  файлы (S3) и поисковый индекс    тема 07
```

<RoadmapChain :items="lessons" />
