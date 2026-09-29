<script setup lang="ts">
import { inject } from 'vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <header class="top-bar">
    <div class="project-tools">
      <label
        >当前项目<select
          v-model="w.project"
          :disabled="w.busy || w.loading || w.uncertain"
          @change="w.loadProject"
        >
          <option value="" disabled>请选择项目</option>
          <option v-for="p in w.projects" :key="p.id" :value="p.id">
            {{ p.name }}
          </option>
        </select></label
      >
      <form class="project-tools" @submit.prevent="w.createProject">
        <label
          >新项目名称<input
            v-model="w.projectName"
            maxlength="120"
            required
            :disabled="w.busy || w.uncertain"
        /></label>
        <button class="secondary" :disabled="w.busy || w.uncertain">
          创建项目
        </button>
      </form>
    </div>
    <div class="user-tools">
      <span class="avatar" aria-hidden="true">{{
        (w.identity?.username ?? 'U').slice(0, 1).toUpperCase()
      }}</span>
      <span
        >{{ w.identity?.username }}
        <small>{{
          w.identity?.role === 'ADMIN' ? '管理员' : '运营'
        }}</small></span
      >
      <router-link class="nav-link" to="/settings">账号与安全</router-link>
      <button class="secondary" :disabled="w.busy" @click="w.logout">
        退出本地账号
      </button>
    </div>
  </header>
</template>
