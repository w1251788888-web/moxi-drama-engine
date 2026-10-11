<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Save, Zap, Image as ImageIcon, Video, Cpu } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { toast } from 'vue-sonner'
import { renderConfigApi, type RenderProviderConfig } from '@/api/client'

const items = ref<RenderProviderConfig[]>([])
const loading = ref(false)
const testingName = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await renderConfigApi.list()
    items.value = data.items || []
  } finally {
    loading.value = false
  }
}

async function save(item: RenderProviderConfig) {
  // api_key 是脱敏字符串则不上传（只在用户重新输入时上传）
  const apiKey = item.api_key.startsWith('****') ? '' : item.api_key
  try {
    await renderConfigApi.upsert({
      name: item.name,
      provider_kind: item.provider_kind,
      api_key: apiKey,
      endpoint: item.endpoint,
      enabled: item.enabled,
      extra: item.extra,
    })
    toast.success(`已保存 ${item.name}`)
    await load()
  } catch (e: any) {
    toast.error('保存失败')
  }
}

async function testConn(item: RenderProviderConfig) {
  testingName.value = item.name
  try {
    const { data } = await renderConfigApi.test(item.name)
    if (data.ok) {
      toast.success(`${item.name}: 连通 (${data.latency_ms}ms)`)
    } else {
      toast.error(`${item.name}: ${data.msg}`)
    }
    await load()
  } catch (e: any) {
    toast.error('连通测试失败')
  } finally {
    testingName.value = ''
  }
}

function iconFor(kind: string) {
  if (kind === 'video') return Video
  if (kind === 'local') return Cpu
  return ImageIcon
}

function kindLabel(kind: string) {
  return ({ image: '图片', video: '视频', local: '本地模型' } as any)[kind] || kind
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="font-semibold text-lg">渲染服务商配置</h2>
        <div class="text-xs text-muted-foreground mt-1">
          一期：仅保存配置 + 连通测试，<b>不真实渲染</b>。提示词复制后请手动喂给对应平台。
          二期：直接调用 API 自动生成。
        </div>
      </div>
      <Button size="sm" variant="outline" :disabled="loading" @click="load">刷新</Button>
    </div>

    <div class="grid gap-3">
      <div v-for="item in items" :key="item.name"
           class="rounded-lg border bg-card p-4 space-y-3">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <component :is="iconFor(item.provider_kind)" class="h-4 w-4 text-muted-foreground" />
            <span class="font-mono text-sm font-medium">{{ item.name }}</span>
            <Badge variant="outline" class="text-xs">{{ kindLabel(item.provider_kind) }}</Badge>
            <Badge v-if="item.enabled" class="bg-emerald-500 text-white text-xs">已启用</Badge>
            <Badge v-else variant="outline" class="text-xs">未启用</Badge>
            <Badge v-if="item.last_test_ok" class="bg-blue-500 text-white text-xs">连通正常</Badge>
            <Badge v-else-if="item.last_test_msg" variant="destructive" class="text-xs">
              {{ item.last_test_msg.slice(0, 30) }}
            </Badge>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-xs text-muted-foreground">启用</span>
            <Switch v-model:checked="item.enabled" />
          </div>
        </div>

        <div v-if="item.doc_hint" class="text-xs text-muted-foreground">
          {{ item.doc_hint }}
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div class="space-y-1">
            <label class="text-xs text-muted-foreground">Endpoint</label>
            <Input v-model="item.endpoint" :placeholder="item.default_endpoint" />
          </div>
          <div class="space-y-1">
            <label class="text-xs text-muted-foreground">API Key</label>
            <Input v-model="item.api_key" type="password" placeholder="填入新 Key 后保存" />
          </div>
        </div>

        <div class="flex items-center justify-end gap-2">
          <Button size="sm" variant="outline"
                  :disabled="testingName === item.name"
                  @click="testConn(item)">
            <Zap class="h-3.5 w-3.5 mr-1" />
            {{ testingName === item.name ? '测试中...' : '连通测试' }}
          </Button>
          <Button size="sm" @click="save(item)">
            <Save class="h-3.5 w-3.5 mr-1" /> 保存
          </Button>
        </div>
      </div>
    </div>

    <div class="p-3 rounded-md bg-muted/50 text-xs text-muted-foreground space-y-1">
      <div class="font-medium text-foreground">二期接入计划</div>
      <div>• <b>jimeng_image / jimeng_video</b>：火山引擎 visual API</div>
      <div>• <b>kling_image / kling_video</b>：可灵开放平台</div>
      <div>• <b>hailuo_video</b>：MiniMax 海螺平台</div>
      <div>• <b>sora_video</b>：OpenAI Sora（待开放）</div>
      <div>• <b>wan_video</b>：阿里通义万相 Wan2.x</div>
      <div>• <b>storydiffusion_local / storymem_local</b>：本地推理服务（自部署）</div>
    </div>
  </div>
</template>
