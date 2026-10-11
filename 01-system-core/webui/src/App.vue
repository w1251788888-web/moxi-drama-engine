<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import { Toaster } from '@/components/ui/sonner'
import { useAuthStore } from '@/stores/auth'

const SESSION_MONITOR_INTERVAL_MS = 30_000

const router = useRouter()
const auth = useAuthStore()

let sessionMonitorTimer: ReturnType<typeof window.setInterval> | null = null
let sessionMonitorRunning = false

async function verifySavedUserSession() {
  if (!auth.userSession?.session_token || sessionMonitorRunning) return
  sessionMonitorRunning = true
  try {
    const isValid = await auth.ensureUserSessionValid({ force: true })
    if (!isValid && router.currentRoute.value.meta.requiresAuth !== false) {
      void router.replace('/login')
    }
  } finally {
    sessionMonitorRunning = false
  }
}

function handleWindowFocus() {
  void verifySavedUserSession()
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    void verifySavedUserSession()
  }
}

onMounted(() => {
  void verifySavedUserSession()
  window.addEventListener('focus', handleWindowFocus)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  sessionMonitorTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      void verifySavedUserSession()
    }
  }, SESSION_MONITOR_INTERVAL_MS)
})

onUnmounted(() => {
  window.removeEventListener('focus', handleWindowFocus)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  if (sessionMonitorTimer) {
    window.clearInterval(sessionMonitorTimer)
  }
})
</script>

<template>
  <Toaster position="bottom-center" :duration="3000" rich-colors />
  <RouterView />
</template>
