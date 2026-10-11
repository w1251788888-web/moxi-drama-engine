import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { i18n, getLocale } from './i18n'

// 初始化主题（在应用挂载前执行，避免闪烁）
const savedTheme = localStorage.getItem('theme') as 'light' | 'dark' | null
if (savedTheme === 'dark') {
  document.documentElement.classList.add('dark')
}

// 同步初始 lang 属性到 <html>，方便 SEO/可访问性
document.documentElement.lang = getLocale()

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)

app.mount('#app')
