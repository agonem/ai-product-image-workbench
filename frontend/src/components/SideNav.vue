<script setup lang="ts">
import { computed, inject } from 'vue'
import { features } from '../workbench/generation'
import { workbenchKey } from '../workbench/useWorkbench'
import LineIcon from './LineIcon.vue'

// Grouped by kind of work, like the New API console (ADR-20260930-E); admin tools last.
const w = inject(workbenchKey)!
const admin = computed(() => w.identity?.role === 'ADMIN')
const groups = computed(() => [
  { name: '概览', items: [{ to: '/', label: '首页', icon: 'home' }] },
  {
    name: '图片生成',
    items: features.map((item) => ({
      to: `/create/${item.route}`,
      label: item.name,
      icon: item.tone,
    })),
  },
  {
    name: '素材与作品',
    items: [
      { to: '/assets', label: '素材管理', icon: 'box' },
      { to: '/works', label: '我的作品', icon: 'grid' },
      { to: '/tasks', label: '任务记录', icon: 'clock' },
    ],
  },
  {
    name: '个人中心',
    items: [{ to: '/account', label: '我的账号', icon: 'user' }],
  },
  ...(admin.value
    ? [
        {
          name: '管理员',
          items: [
            { to: '/accounts', label: '账号管理', icon: 'users' },
            { to: '/models', label: '模型配置', icon: 'cpu' },
          ],
        },
      ]
    : []),
])
</script>

<template>
  <aside class="side-nav" aria-label="工作台导航">
    <nav>
      <template v-for="group in groups" :key="group.name">
        <div class="nav-group">{{ group.name }}</div>
        <router-link
          v-for="item in group.items"
          :key="item.to"
          class="nav-link"
          :to="item.to"
          :title="item.label"
          :aria-label="item.label"
          ><LineIcon :name="item.icon" /><span>{{
            item.label
          }}</span></router-link
        >
      </template>
    </nav>
    <div class="user-card">
      <span class="avatar" aria-hidden="true">{{
        (w.identity?.username ?? 'U').slice(0, 1).toUpperCase()
      }}</span>
      <div class="who">
        <strong>{{ w.identity?.username }}</strong>
        <span class="tag">{{ admin ? '管理员' : '运营' }}</span>
      </div>
      <button
        type="button"
        class="icon-btn danger"
        aria-label="退出登录"
        title="退出登录"
        :disabled="w.busy"
        @click="w.logout"
      >
        <LineIcon name="out" :size="18" />
      </button>
    </div>
  </aside>
</template>
