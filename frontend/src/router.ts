import { createRouter, createWebHashHistory } from 'vue-router'
import AccountsView from './views/AccountsView.vue'
import AssetsView from './views/AssetsView.vue'
import CreateView from './views/CreateView.vue'
import HomeView from './views/HomeView.vue'
import ModelsView from './views/ModelsView.vue'
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
    // Account pages work without a project (e.g. a new admin configuring the models).
    { path: '/account', component: SettingsView, meta: { project: false } },
    { path: '/accounts', component: AccountsView, meta: { project: false } },
    { path: '/models', component: ModelsView, meta: { project: false } },
    { path: '/settings', redirect: '/account' },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})
