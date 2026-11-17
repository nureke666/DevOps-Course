# System Design — раздел скрыт (deprecated)

С 2026-11-18 курс System Design не публикуется на сайте. Файлы лежат здесь, но VitePress их
не собирает: в `docs/.vitepress/config.mts` стоит `srcExclude: ['system-design/**']`.

Что скрыто: обзор курса, блок 1 «Основы и метод», блок 2 «Строительные блоки», разбор
«Сокращатель ссылок». Черновики блока 3 и короткая версия урока про кеш не входят в `main`.

Как вернуть раздел на сайт:

1. Убрать `srcExclude` в `docs/.vitepress/config.mts`.
2. Раскомментировать пункт «System Design» в `nav` там же.
3. Вернуть раздел на главную `docs/index.md` и ссылку в `docs/career/03-system-design-devops.md`
   (их можно взять из истории git, коммит, где раздел скрыли).
