---
title: "Базы данных"
description: "Курс по базам данных для DevOps: PostgreSQL, бэкапы, репликация, мониторинг, MySQL, миграции схемы"
---

<script setup>
import RoadmapChain from '../.vitepress/theme/components/RoadmapChain.vue'

const lessons = [
  { title: '01. База данных глазами DevOps', desc: 'Какие бывают базы, транзакции и ACID, WAL и MVCC, индексы, типовые грабли', status: 'active', link: '/databases/01-db-for-devops' },
  { title: '02. PostgreSQL: установка и устройство', desc: 'Установка из PGDG/RHEL/Docker, где что лежит, psql, reload vs restart', status: 'active', link: '/databases/02-pg-install' },
  { title: '03. Доступ: pg_hba.conf, роли и права', desc: 'Аутентификация vs авторизация, формат pg_hba.conf, роли и GRANT, TLS', status: 'active', link: '/databases/03-pg-hba-access' },
  { title: '04. postgresql.conf — основные параметры', desc: 'Память, соединения, WAL и checkpoint, autovacuum, таймауты, логирование', status: 'active', link: '/databases/04-postgresql-conf' },
  { title: '05. Бэкап и восстановление', desc: 'Логический и физический бэкап, PITR, WAL-G/pgBackRest, стратегия 3-2-1', status: 'active', link: '/databases/05-backup-restore' },
  { title: '06. Репликация PostgreSQL', desc: 'Потоковая и логическая репликация, слоты, lag, promote/failover, Patroni', status: 'active', link: '/databases/06-replication' },
  { title: '07. Мониторинг баз данных', desc: 'pg_stat_*, postgres_exporter/Prometheus/Grafana, алгоритм «база тормозит»', status: 'active', link: '/databases/07-db-monitoring' },
  { title: '08. Базовый SQL для DevOps', desc: 'SELECT/INSERT/GRANT/EXPLAIN, безопасный UPDATE на проде, типичные грабли', status: 'active', link: '/databases/08-sql-basics' },
  { title: '09. Redis, MongoDB, ClickHouse', desc: 'Кэш и сессии, документы, аналитика — обзорно: зачем, как поднять, метрики', status: 'active', link: '/databases/09-redis-mongo-clickhouse' },
  { title: '10. Практика: 7 лаб', desc: 'PostgreSQL с нуля, бэкап/PITR, реплика и promote, мониторинг, релиз схемы без простоя', status: 'active', link: '/databases/10-practice-labs' },
  { title: '11. Вопросы с собеседований', desc: '7 главных вопросов и 48 дополнительных — бэкапы, репликация, мониторинг, MySQL', status: 'active', link: '/databases/11-interview' },
  { title: '12. MySQL и MariaDB', desc: 'Для тех, кто знает PostgreSQL: my.cnf, права, бэкапы, PITR по binlog, HA', status: 'active', link: '/databases/12-mysql' },
  { title: '13. Миграции схемы', desc: 'Как менять схему без простоя: expand/contract, блокировки, откаты, тесты в CI', status: 'active', link: '/databases/13-schema-migrations' },
]
</script>

# Базы данных

От устройства PostgreSQL и бэкапов до репликации, мониторинга и миграций схемы без простоя.

<RoadmapChain :items="lessons" />
