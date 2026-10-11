import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

type Theme = 'light' | 'dark'

export const useThemeStore = defineStore('theme', () => {
  // 从 localStorage 读取保存的主题，默认 'light'
  const savedTheme = localStorage.getItem('theme') as Theme | null
  const theme = ref<Theme>(savedTheme || 'light')

  // 应用主题到 document
  function applyTheme(newTheme: Theme) {
    const root = document.documentElement
    if (newTheme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }

  // 切换主题
  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  // 设置指定主题
  function setTheme(newTheme: Theme) {
    theme.value = newTheme
  }

  // 监听主题变化并保存
  watch(theme, (newTheme) => {
    localStorage.setItem('theme', newTheme)
    applyTheme(newTheme)
  }, { immediate: true })

  // 初始化时应用主题
  applyTheme(theme.value)

  return { theme, toggleTheme, setTheme, applyTheme }
})
