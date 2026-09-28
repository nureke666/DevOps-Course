<script setup lang="ts">
import { withBase } from 'vitepress'

interface RoadmapItem {
  title: string
  desc?: string
  status?: 'active' | 'soon'
  link?: string
}

defineProps<{
  items: RoadmapItem[]
}>()
</script>

<template>
  <ol class="roadmap">
    <li v-for="(item, i) in items" :key="item.title" class="roadmap-item" :class="item.status">
      <div class="node-col">
        <span class="node">{{ i + 1 }}</span>
        <span v-if="i < items.length - 1" class="line" />
      </div>

      <component
        :is="item.status === 'active' && item.link ? 'a' : 'div'"
        :href="item.status === 'active' && item.link ? withBase(item.link) : undefined"
        class="card"
      >
        <div class="card-head">
          <span class="card-title">{{ item.title }}</span>
          <span v-if="item.status === 'soon'" class="badge">скоро</span>
        </div>
        <p v-if="item.desc" class="card-desc">{{ item.desc }}</p>
      </component>
    </li>
  </ol>
</template>

<style scoped>
.roadmap {
  list-style: none;
  margin: 32px 0;
  padding: 0;
  max-width: 640px;
}

.roadmap-item {
  display: flex;
  gap: 16px;
}

.node-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
}

.node {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-size: 14px;
  font-weight: 600;
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-2);
  border: 2px solid var(--vp-c-divider);
}

.roadmap-item.active .node {
  background: var(--vp-c-brand-1);
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-white);
}

.line {
  flex: 1;
  width: 2px;
  min-height: 24px;
  background: var(--vp-c-divider);
}

.roadmap-item.active .line {
  background: var(--vp-c-brand-1);
}

.card {
  display: block;
  flex: 1;
  margin-bottom: 20px;
  padding: 14px 18px;
  border-radius: 10px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-soft);
  text-decoration: none;
  transition: border-color 0.2s, transform 0.2s, background-color 0.2s;
}

a.card {
  cursor: pointer;
}

a.card:hover {
  border-color: var(--vp-c-brand-1);
  background: var(--vp-c-bg-elv);
  transform: translateX(2px);
}

div.card {
  opacity: 0.6;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-weight: 600;
  font-size: 16px;
  color: var(--vp-c-text-1);
}

a.card .card-title {
  color: var(--vp-c-brand-1);
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--vp-c-default-soft);
  color: var(--vp-c-text-2);
}

.card-desc {
  margin: 6px 0 0;
  font-size: 13.5px;
  line-height: 1.5;
  color: var(--vp-c-text-2);
}
</style>
