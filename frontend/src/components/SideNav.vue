<script setup lang="ts">
import { features } from '../workbench/generation'
</script>

<template>
  <aside class="side-nav" aria-label="工作台导航">
    <div class="brand">
      <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">
        <circle cx="20" cy="20" r="19" fill="#eef3ff" />
        <circle cx="20" cy="22" r="11" fill="#ffe8d6" />
        <path
          d="M11 17c2-7 16-8 18 0"
          fill="none"
          stroke="#f4a261"
          stroke-width="3"
          stroke-linecap="round"
        />
        <circle cx="16" cy="22" r="1.4" fill="#374151" />
        <circle cx="24" cy="22" r="1.4" fill="#374151" />
        <path
          d="M17 26c2 1.6 4 1.6 6 0"
          fill="none"
          stroke="#e76f51"
          stroke-width="1.6"
          stroke-linecap="round"
        />
      </svg>
      <div>
        <strong>母婴商品图工作台</strong><small>AI 让商品图更简单</small>
      </div>
    </div>
    <router-link class="nav-link" to="/">首页</router-link>
    <div class="nav-group">
      <span>图片生成</span>
      <router-link
        v-for="item in features"
        :key="item.id"
        class="nav-link nav-sub"
        :to="`/create/${item.route}`"
        >{{ item.name }}</router-link
      >
    </div>
    <router-link class="nav-link" to="/assets">素材管理</router-link>
    <router-link class="nav-link" to="/tasks">任务记录</router-link>
    <router-link class="nav-link" to="/works">我的作品</router-link>
    <p class="side-foot">
      商品原图永久保留 · 生成结果需人工审核 · 仅生成与下载，不自动上架
    </p>
  </aside>
</template>
