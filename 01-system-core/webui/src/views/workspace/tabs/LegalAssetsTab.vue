<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Archive, CheckCircle2, FileCheck2, RefreshCw, ShieldAlert, UploadCloud } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { legalAssetsApi, type EvidencePackage, type LegalMaterialItem, type LegalMaterialMatrix, type RightsCheckResult } from '@/api/client'
import { notifyApiError } from '@/api/http'
import { toast } from 'vue-sonner'

const props = defineProps<{
  projectId: string
}>()

const matrix = ref<LegalMaterialMatrix | null>(null)
const gate = ref<RightsCheckResult | null>(null)
const aiStatement = ref('')
const generatedPackage = ref<EvidencePackage | null>(null)
const isLoading = ref(false)
const isGenerating = ref(false)
const selectedPackageType = ref('delivery')
const materialDraft = ref<Record<string, string>>({})

const packageTypes = [
  { value: 'registration', label: '登记包' },
  { value: 'delivery', label: '投递包' },
  { value: 'legal', label: '法务包' },
  { value: 'dispute', label: '争议包' },
  { value: 'broadcast_prefight', label: '广电备案预检包' },
]

const statusTone = computed(() => {
  if (gate.value?.status === 'blocked') return 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
  if (gate.value?.status === 'warning') return 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300'
  return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
})

function materialStatusLabel(status: string) {
  if (status === 'ready') return '已齐全'
  if (status === 'missing') return '待补'
  if (status === 'pending') return '待确认'
  return status
}

function materialStatusClass(status: string) {
  if (status === 'ready') return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  if (status === 'missing') return 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
  return 'bg-blue-500/10 text-blue-700 dark:text-blue-300'
}

async function loadAll() {
  isLoading.value = true
  try {
    const [matrixRes, gateRes, aiRes] = await Promise.all([
      legalAssetsApi.getMatrix(props.projectId),
      legalAssetsApi.getExportGate(props.projectId),
      legalAssetsApi.getAiStatement(props.projectId),
    ])
    matrix.value = matrixRes.data
    gate.value = gateRes.data
    aiStatement.value = aiRes.data.content
  } catch (e) {
    notifyApiError(toast.error, e, '加载法律资料失败')
  } finally {
    isLoading.value = false
  }
}

async function saveMaterial(item: LegalMaterialItem, provider: string) {
  const content = materialDraft.value[item.material_type]?.trim()
  if (!content) {
    toast.error('请先填写资料内容')
    return
  }
  try {
    await legalAssetsApi.saveMaterial(props.projectId, {
      material_type: item.material_type,
      title: item.title,
      content_text: content,
      provider,
      status: 'ready',
    })
    toast.success('资料已补录')
    materialDraft.value[item.material_type] = ''
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '补录资料失败')
  }
}

async function generatePackage() {
  isGenerating.value = true
  try {
    const { data } = await legalAssetsApi.createPackage(props.projectId, selectedPackageType.value)
    generatedPackage.value = data
    toast.success('法律资产包已生成')
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '生成资产包失败')
  } finally {
    isGenerating.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <section class="h-full min-h-[680px] overflow-auto bg-background">
    <div class="space-y-4">
      <div class="rounded-lg border bg-card p-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold">法律资料与确权中心</h2>
            <p class="text-sm text-muted-foreground">系统资料、人工资料、外部回填统一纳入正式交付门禁</p>
          </div>
          <Button size="sm" variant="outline" class="gap-1.5" :disabled="isLoading" @click="loadAll">
            <RefreshCw class="h-4 w-4" />
            刷新
          </Button>
        </div>
        <div class="mt-4 grid gap-3 md:grid-cols-3">
          <div class="rounded-lg border p-3">
            <p class="text-xs text-muted-foreground">资料完整度</p>
            <p class="mt-1 text-2xl font-semibold">{{ matrix?.rights_score ?? 0 }}%</p>
          </div>
          <div class="rounded-lg border p-3">
            <p class="text-xs text-muted-foreground">确权状态</p>
            <p class="mt-1 text-lg font-semibold">{{ matrix?.rights_status || 'draft' }}</p>
          </div>
          <div class="rounded-lg border p-3" :class="statusTone">
            <p class="text-xs">正式导出门禁</p>
            <p class="mt-1 text-lg font-semibold">{{ gate?.status || 'checking' }}</p>
          </div>
        </div>
      </div>

      <div v-if="gate && (gate.blockers.length || gate.warnings.length)" class="rounded-lg border p-4" :class="statusTone">
        <div class="flex items-center gap-2 font-medium">
          <ShieldAlert class="h-4 w-4" />
          导出前需处理
        </div>
        <ul class="mt-2 space-y-1 text-sm">
          <li v-for="item in gate.blockers" :key="`b-${item}`">阻塞：{{ item }}</li>
          <li v-for="item in gate.warnings" :key="`w-${item}`">提示：{{ item }}</li>
        </ul>
      </div>

      <div class="grid gap-4 lg:grid-cols-3">
        <section class="rounded-lg border bg-card p-4">
          <h3 class="mb-3 flex items-center gap-2 font-semibold">
            <FileCheck2 class="h-4 w-4 text-emerald-500" />
            系统已生成
          </h3>
          <div class="space-y-3">
            <div v-for="item in matrix?.system_generated || []" :key="item.material_type" class="rounded-lg border p-3">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <p class="text-sm font-medium">{{ item.title }}</p>
                  <p class="mt-1 text-xs text-muted-foreground">{{ item.detail || item.material_type }}</p>
                </div>
                <Badge :class="materialStatusClass(item.status)">{{ materialStatusLabel(item.status) }}</Badge>
              </div>
            </div>
          </div>
        </section>

        <section class="rounded-lg border bg-card p-4">
          <h3 class="mb-3 flex items-center gap-2 font-semibold">
            <UploadCloud class="h-4 w-4 text-amber-500" />
            人工待补
          </h3>
          <div class="space-y-3">
            <div v-for="item in matrix?.user_required || []" :key="item.material_type" class="rounded-lg border p-3">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <p class="text-sm font-medium">{{ item.title }}</p>
                  <p class="mt-1 text-xs text-muted-foreground">{{ item.detail || '等待人工补充' }}</p>
                </div>
                <Badge :class="materialStatusClass(item.status)">{{ materialStatusLabel(item.status) }}</Badge>
              </div>
              <div class="mt-3 flex gap-2">
                <Input v-model="materialDraft[item.material_type]" class="h-9" placeholder="填写编号、摘要或存证说明" />
                <Button size="sm" @click="saveMaterial(item, 'user')">保存</Button>
              </div>
            </div>
          </div>
        </section>

        <section class="rounded-lg border bg-card p-4">
          <h3 class="mb-3 flex items-center gap-2 font-semibold">
            <Archive class="h-4 w-4 text-blue-500" />
            外部回填
          </h3>
          <div class="space-y-3">
            <div v-for="item in matrix?.external_required || []" :key="item.material_type" class="rounded-lg border p-3">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <p class="text-sm font-medium">{{ item.title }}</p>
                  <p class="mt-1 text-xs text-muted-foreground">{{ item.detail || '等待第三方回执' }}</p>
                </div>
                <Badge :class="materialStatusClass(item.status)">{{ materialStatusLabel(item.status) }}</Badge>
              </div>
              <div class="mt-3 flex gap-2">
                <Input v-model="materialDraft[item.material_type]" class="h-9" placeholder="填写回执号或备案号" />
                <Button size="sm" variant="outline" @click="saveMaterial(item, 'external')">回填</Button>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section class="rounded-lg border bg-card p-4">
          <h3 class="mb-3 font-semibold">AI 创作过程说明</h3>
          <pre class="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/40 p-4 text-xs leading-6">{{ aiStatement }}</pre>
        </section>

        <section class="rounded-lg border bg-card p-4">
          <h3 class="mb-3 font-semibold">正式资产包</h3>
          <div class="grid grid-cols-2 gap-2">
            <button
              v-for="item in packageTypes"
              :key="item.value"
              class="rounded-lg border px-3 py-2 text-sm transition-colors"
              :class="selectedPackageType === item.value ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted'"
              @click="selectedPackageType = item.value"
            >
              {{ item.label }}
            </button>
          </div>
          <Button class="mt-4 w-full gap-1.5" :disabled="isGenerating || gate?.status === 'blocked'" @click="generatePackage">
            <Archive class="h-4 w-4" />
            {{ isGenerating ? '生成中...' : '生成法律资产包' }}
          </Button>
          <div v-if="generatedPackage" class="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-300">
            <div class="flex items-center gap-2 font-medium">
              <CheckCircle2 class="h-4 w-4" />
              已生成
            </div>
            <p class="mt-2 break-all text-xs">Manifest Hash：{{ generatedPackage.manifest_hash }}</p>
            <p class="mt-1 break-all text-xs">{{ generatedPackage.package_path }}</p>
          </div>
        </section>
      </div>
    </div>
  </section>
</template>
