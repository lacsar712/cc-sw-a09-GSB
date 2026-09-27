import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import JobDetailView from './views/JobDetailView.vue'
import PrefixBookView from './views/PrefixBookView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/jobs/:id', name: 'job-detail', component: JobDetailView, props: true },
    { path: '/prefixes', name: 'prefix-book', component: PrefixBookView },
  ],
})

export default router
