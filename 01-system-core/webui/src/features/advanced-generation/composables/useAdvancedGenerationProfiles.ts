import { computed, ref } from 'vue'
import {
  advancedGenerationApi,
  type AdvancedGenerationProfile,
} from '@/api/client'
import { formatAccessErrorMessage } from '@/api/http'

export function useAdvancedGenerationProfiles() {
  const profiles = ref<AdvancedGenerationProfile[]>([])
  const isLoading = ref(false)
  const loadError = ref('')

  const activeProfiles = computed(() => profiles.value.filter((item) => item.status === 'active'))
  const scaffoldProfiles = computed(() => profiles.value.filter((item) => item.status !== 'active'))

  async function loadProfiles() {
    isLoading.value = true
    loadError.value = ''
    try {
      const { data } = await advancedGenerationApi.listProfiles()
      profiles.value = data.profiles
    } catch (e: unknown) {
      loadError.value = formatAccessErrorMessage(e) || '科研生成链路配置读取失败'
    } finally {
      isLoading.value = false
    }
  }

  return {
    profiles,
    isLoading,
    loadError,
    activeProfiles,
    scaffoldProfiles,
    loadProfiles,
  }
}
