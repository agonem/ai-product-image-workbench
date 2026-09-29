import { createRouter, createWebHashHistory } from 'vue-router'
import AssetsView from './views/AssetsView.vue'
import CreateView from './views/CreateView.vue'
import HomeView from './views/HomeView.vue'
import SettingsView from './views/SettingsView.vue'
import TasksView from './views/TasksView.vue'
import WorksView from './views/WorksView.vue'

// Hash history keeps the intranet deployment a plain static site (no server rewrites).
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/create/:feature(gift|scene|selling)', component: CreateView },
    { path: '/assets', component: AssetsView },
    { path: '/tasks', component: TasksView },
    { path: '/works', component: WorksView },
    // Account settings work without a project (e.g. a new admin configuring the provider).
    { path: '/settings', component: SettingsView, meta: { project: false } },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})
