<script setup lang="ts">
import { computed, inject } from 'vue'
import { features } from '../workbench/generation'
import { workbenchKey } from '../workbench/useWorkbench'
import LineIcon from './LineIcon.vue'

const w = inject(workbenchKey)!
const admin = computed(() => w.identity?.role === 'ADMIN')
</script>

<template>
  <aside class="side-nav" aria-label="工作台导航">
    <div class="brand">
      <span class="logo" aria-hidden="true">母</span>
      <strong>母婴商品图工作台</strong>
    </div>
    <nav>
      <router-link class="nav-link" to="/"
        ><LineIcon name="home" />首页</router-link
      >
      <div class="nav-group">图片生成</div>
      <router-link
        v-for="item in features"
        :key="item.id"
        class="nav-link"
        :to="`/create/${item.route}`"
        ><LineIcon :name="item.tone" />{{ item.name }}</router-link
      >
      <div class="nav-group">素材与作品</div>
      <router-link class="nav-link" to="/assets"
        ><LineIcon name="box" />素材管理</router-link
      >
      <router-link class="nav-link" to="/works"
        ><LineIcon name="grid" />我的作品</router-link
      >
      <router-link class="nav-link" to="/tasks"
        ><LineIcon name="clock" />任务记录</router-link
      >
      <div class="nav-group">设置</div>
      <router-link class="nav-link" to="/settings"
        ><LineIcon name="user" />账号与安全</router-link
      >
      <router-link v-if="admin" class="nav-link" to="/models"
        ><LineIcon name="cpu" />模型配置</router-link
      >
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
