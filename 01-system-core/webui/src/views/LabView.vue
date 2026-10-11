<script setup lang="ts">
// @ts-nocheck
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search, TrendingUp, Lightbulb, BarChart3, Sparkles, RefreshCw,
  X, Star, BookOpen, Plus, Zap, Globe, Users, MapPin, Swords, Heart,
  GitCompare, Check, ChevronRight, BarChart2
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { marketApi, userAccessApi } from '@/api/client'
import { formatUserFacingErrorMessage } from '@/api/http'
import { toast } from 'vue-sonner'

const router = useRouter()

// ── 基础 ──────────────────────────────────────────────────────
const searchQuery = ref('')
const isLoading = ref(false)
const loadError = ref('')
const searchSummary = ref('')

// ── 热榜 ──────────────────────────────────────────────────────
const trendingTopics = ref([
  { id: 1, title: '重生逆袭', heat: 98, change: '+12%', category: 'male', tags: ['系统', '打脸', '权谋'],
    platforms: ['抖音', '快手'], vacancy: 42, trendHistory: [80, 82, 85, 86, 90, 93, 95, 98] },
  { id: 2, title: '甜宠虐恋', heat: 95, change: '+8%', category: 'female', tags: ['追妻', '契约', '误会'],
    platforms: ['抖音', '微信'], vacancy: 55, trendHistory: [85, 87, 88, 90, 91, 93, 94, 95] },
  { id: 3, title: '悬疑推理', heat: 92, change: '+15%', category: 'mixed', tags: ['反转', '破案', '密室'],
    platforms: ['抖音'], vacancy: 68, trendHistory: [70, 73, 76, 78, 82, 85, 89, 92] },
  { id: 4, title: '古装权谋', heat: 88, change: '+5%', category: 'male', tags: ['宫斗', '复仇', '智斗'],
    platforms: ['抖音', '快手'], vacancy: 35, trendHistory: [80, 82, 83, 84, 85, 86, 87, 88] },
  { id: 5, title: '都市情感', heat: 85, change: '-3%', category: 'female', tags: ['职场', '婚姻', '成长'],
    platforms: ['微信'], vacancy: 60, trendHistory: [90, 89, 88, 87, 87, 86, 85, 85] },
  { id: 6, title: '穿越种田', heat: 82, change: '+20%', category: 'female', tags: ['宅斗', '经商', '甜宠'],
    platforms: ['快手'], vacancy: 75, trendHistory: [60, 63, 67, 70, 72, 75, 79, 82] },
])
const hotWords = ref([
  { word: '逆袭', weight: 98 }, { word: '重生', weight: 92 }, { word: '总裁', weight: 90 },
  { word: '契约婚姻', weight: 88 }, { word: '系统', weight: 85 }, { word: '身份反转', weight: 82 },
  { word: '打脸', weight: 80 }, { word: '追妻', weight: 78 }, { word: '穿越', weight: 75 },
  { word: '仇敌', weight: 72 }, { word: '复仇', weight: 70 }, { word: '真香', weight: 68 },
  { word: '权谋', weight: 65 }, { word: '虐恋', weight: 62 },
])
const platformFilter = ref('all')
const timePeriod = ref('7d')
const PLATFORMS = [
  { key: 'all', label: '全平台' }, { key: 'douyin', label: '抖音' },
  { key: 'kuaishou', label: '快手' }, { key: 'wechat', label: '微信' },
]
const filteredTrending = computed(() => {
  if (platformFilter.value === 'all') return trendingTopics.value
  const platMap: Record<string, string> = { douyin: '抖音', kuaishou: '快手', wechat: '微信' }
  const currentPlatform = platMap[platformFilter.value] || ''
  return trendingTopics.value.filter(t =>
    (t.platforms || []).includes(currentPlatform)
  )
})

// ── 题材推荐 ──────────────────────────────────────────────────
const recommendedTopics = ref([
  { id: 1, title: '《重生后我成了死对头的心尖宠》', type: '甜宠', score: 96,
    reason: '融合重生+甜宠+反差萌，近期热度飙升', novelty: 88,
    competition: 32, marketGap: 75, platforms: { douyin: 65, kuaishou: 25, wechat: 10 } },
  { id: 2, title: '《离婚三年后，前夫跪求复婚》', type: '虐恋', score: 94,
    reason: '追妻火葬场经典套路，情绪张力强', novelty: 75,
    competition: 58, marketGap: 42, platforms: { douyin: 50, kuaishou: 30, wechat: 20 } },
  { id: 3, title: '《穿成反派的我只想摆烂》', type: '穿越', score: 92,
    reason: '反套路人设+轻松搞笑，差异化明显', novelty: 90,
    competition: 22, marketGap: 82, platforms: { douyin: 70, kuaishou: 20, wechat: 10 } },
  { id: 4, title: '《捡到的猫竟是帝国元帅》', type: '奇幻', score: 89,
    reason: '人外设定+身份反差，新颖吸睛', novelty: 95,
    competition: 15, marketGap: 88, platforms: { douyin: 75, kuaishou: 15, wechat: 10 } },
])
const savedTopics = ref<number[]>([])
const compareCandidates = ref<any[]>([])
const showCompare = ref(false)

// ── 爆款解析 ──────────────────────────────────────────────────
const caseStudies = ref([
  {
    id: 1, title: '《闪婚后，千亿老公狂宠我》', category: '甜宠', views: '2.3亿',
    hook: '契约婚姻+身份反转', structure: '强冲突开局→甜宠升级→误会危机→大团圆',
    nodes: [
      { label: '契约惊魂', desc: '被迫签婚契', type: 'hook' },
      { label: '暗中宠爱', desc: '身份隐藏', type: 'escalation' },
      { label: '误会危机', desc: '第三者介入', type: 'escalation' },
      { label: '身份揭露', desc: '全场打脸', type: 'climax' },
      { label: '白头偕老', desc: '真心相许', type: 'ending' },
    ],
    emotionCurve: [25, 60, 45, 70, 55, 80, 65, 90, 85, 75],
    highlights: ['第1集签契约时女主怼回去 ★★★★★', '第5集老公暗中保护被发现 ★★★★', '第8集身份揭露狠狠打脸 ★★★★★'],
  },
  {
    id: 2, title: '《重生之都市修仙》', category: '男频', views: '1.8亿',
    hook: '重生+修仙+打脸', structure: '惨开局→得传承→装逼打脸→建立势力',
    nodes: [
      { label: '车祸重生', desc: '死亡开局', type: 'hook' },
      { label: '获得传承', desc: '系统激活', type: 'escalation' },
      { label: '装逼打脸', desc: '碾压对手', type: 'climax' },
      { label: '建立势力', desc: '称霸全场', type: 'ending' },
    ],
    emotionCurve: [10, 30, 20, 55, 45, 75, 70, 90, 85, 95],
    highlights: ['第1集重生时发现自己有金手指 ★★★★★', '第4集当众打脸前世仇人 ★★★★★', '第7集以弱胜强逆天改命 ★★★★'],
  },
  {
    id: 3, title: '《离婚后我继承了亿万家产》', category: '女频', views: '1.5亿',
    hook: '离婚+逆袭+真香', structure: '隐忍离婚→身份揭露→前夫后悔→新恋情',
    nodes: [
      { label: '主动离婚', desc: '婚姻失败', type: 'hook' },
      { label: '身份揭露', desc: '女主真面目', type: 'escalation' },
      { label: '前夫后悔', desc: '求复婚失败', type: 'climax' },
      { label: '新的开始', desc: '真爱归来', type: 'ending' },
    ],
    emotionCurve: [30, 20, 40, 60, 50, 75, 80, 70, 85, 90],
    highlights: ['第1集离婚时女主笑着签字让人意外 ★★★★★', '第3集前夫发现女主是亿万继承人 ★★★★', '第6集前夫跪求复婚被当众拒绝 ★★★★★'],
  },
])
const selectedCase = ref<any>(null)
const showCaseDrawer = ref(false)
const caseAnalysis = ref<any>(null)
const isAnalyzing = ref(false)

// ── 灵感元素 ──────────────────────────────────────────────────
const inspirationCards = ref([
  { id: 1, quadrant: 'character', type: '人物', title: '隐藏身份总裁', desc: '表面普通员工，实为集团掌舵人', heat: 95, tags: ['反差', '隐藏'] },
  { id: 2, quadrant: 'character', type: '人物', title: '重生复仇女主', desc: '上辈子被害，带记忆重来', heat: 92, tags: ['重生', '复仇'] },
  { id: 3, quadrant: 'character', type: '人物', title: '天才医女', desc: '弃妇出走，独当一面', heat: 88, tags: ['逆袭', '医术'] },
  { id: 4, quadrant: 'character', type: '人物', title: '病娇反派', desc: '冷酷外表下是极致占有欲', heat: 85, tags: ['病娇', '反派'] },
  { id: 5, quadrant: 'setting', type: '场景', title: '豪门集团总部', desc: '权力角逐的核心战场', heat: 90, tags: ['都市', '豪门'] },
  { id: 6, quadrant: 'setting', type: '场景', title: '古代皇宫', desc: '阴谋与权术的漩涡中心', heat: 87, tags: ['古装', '宫廷'] },
  { id: 7, quadrant: 'setting', type: '场景', title: '修仙界', desc: '弱肉强食的境界体系', heat: 84, tags: ['修仙', '玄幻'] },
  { id: 8, quadrant: 'setting', type: '场景', title: '重生后的高中', desc: '改变命运的起点', heat: 80, tags: ['校园', '重生'] },
  { id: 9, quadrant: 'conflict', type: '冲突', title: '身份错位', desc: '女主以为男主是穷小子，其实是总裁', heat: 95, tags: ['身份', '误会'] },
  { id: 10, quadrant: 'conflict', type: '冲突', title: '追妻火葬场', desc: '前夫后悔求复婚，女主已成功', heat: 92, tags: ['追妻', '反转'] },
  { id: 11, quadrant: 'conflict', type: '冲突', title: '豪门婆媳战', desc: '婆婆打压，儿媳憋屈反击', heat: 88, tags: ['家庭', '对抗'] },
  { id: 12, quadrant: 'conflict', type: '冲突', title: '商战阴谋', desc: '被设计出丑后反杀', heat: 85, tags: ['商战', '反杀'] },
  { id: 13, quadrant: 'hook', type: '钩子', title: '死而复生', desc: '第一集结尾主角"死亡"，实为反转', heat: 98, tags: ['悬念', '反转'] },
  { id: 14, quadrant: 'hook', type: '钩子', title: '身份当场揭露', desc: '仇人面前撕下伪装，全场震惊', heat: 93, tags: ['反转', '爽点'] },
  { id: 15, quadrant: 'hook', type: '钩子', title: '绑定系统', desc: '第一集获得金手指，开启逆袭', heat: 90, tags: ['系统', '开挂'] },
  { id: 16, quadrant: 'hook', type: '钩子', title: '偷听秘密', desc: '意外获知改变命运的关键信息', heat: 86, tags: ['悬念', '命运'] },
])
const boardItems = ref<any[]>([])
const isGeneratingBoard = ref(false)

const QUADRANTS = [
  { key: 'character', label: '人物类型', icon: Users,  color: 'blue' },
  { key: 'setting',   label: '场景设定', icon: MapPin,  color: 'green' },
  { key: 'conflict',  label: '矛盾冲突', icon: Swords,  color: 'red' },
  { key: 'hook',      label: '情绪钩子', icon: Heart,   color: 'purple' },
]
const QUADRANT_STYLES: Record<string, { card: string; badge: string }> = {
  blue:   { card: 'border-blue-200 bg-blue-50/60 dark:border-blue-800 dark:bg-blue-950/30', badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300' },
  green:  { card: 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-800 dark:bg-emerald-950/30', badge: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300' },
  red:    { card: 'border-red-200 bg-red-50/60 dark:border-red-800 dark:bg-red-950/30', badge: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300' },
  purple: { card: 'border-purple-200 bg-purple-50/60 dark:border-purple-800 dark:bg-purple-950/30', badge: 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300' },
}
type QuadrantColor = keyof typeof QUADRANT_STYLES
function quadrantStyleFor(color: string) {
  return QUADRANT_STYLES[color as QuadrantColor] || QUADRANT_STYLES.blue
}

// ── Chart / SVG helpers ───────────────────────────────────────
const NODE_COLORS: Record<string, string> = {
  hook: '#f59e0b', escalation: '#3b82f6', climax: '#ef4444', ending: '#10b981',
}
const LINE_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

function nodeLabel(type: string): string {
  return ({ hook: '开局', escalation: '升级', climax: '高潮', ending: '结尾' } as Record<string, string>)[type] || type
}

function emotionCurvePath(points: number[]): string {
  if (!points?.length) return ''
  return points.map((y, i) => {
    const x = Math.round((i / (points.length - 1)) * 400)
    const py = Math.round(72 - (y / 100) * 72)
    return `${i === 0 ? 'M' : 'L'} ${x} ${py}`
  }).join(' ')
}
function emotionAreaPath(points: number[]): string {
  if (!points?.length) return ''
  const line = points.map((y, i) => {
    const x = Math.round((i / (points.length - 1)) * 400)
    const py = Math.round(72 - (y / 100) * 72)
    return `${i === 0 ? 'M' : 'L'} ${x} ${py}`
  }).join(' ')
  return `${line} L 400 72 L 0 72 Z`
}
function trendSparkPath(history: number[]): string {
  if (!history?.length) return ''
  const maxV = Math.max(...history, 1)
  return history.map((y, i) => {
    const x = Math.round((i / (history.length - 1)) * 100)
    const py = Math.round(28 - (y / maxV) * 24)
    return `${i === 0 ? 'M' : 'L'} ${x} ${py}`
  }).join(' ')
}
// 预算所有 topic 的 multi-trend 路径：一次 reduce 完成，避免模板 v-for 里对每个 idx 重复 flatMap
const multiTrendPathsCache = computed<string[]>(() => {
  const list = filteredTrending.value
  if (!list.length) return []
  let maxV = 1
  for (const t of list) {
    const h = t.trendHistory || []
    for (const v of h) if (v > maxV) maxV = v
  }
  return list.map(topic => {
    const hist = topic.trendHistory || []
    if (!hist.length) return ''
    return hist.map((y: number, i: number) => {
      const x = Math.round((i / (hist.length - 1)) * 600)
      const py = Math.round(120 - (y / maxV) * 110)
      return `${i === 0 ? 'M' : 'L'} ${x} ${py}`
    }).join(' ')
  })
})
function multiTrendPath(idx: number): string {
  return multiTrendPathsCache.value[idx] || ''
}

// ── Functions ─────────────────────────────────────────────────
async function loadAITopics(keyword?: string) {
  isLoading.value = true
  loadError.value = ''
  searchSummary.value = ''
  try {
    const { data } = await marketApi.aiTopics({ keyword, count: 6 })
    if (data.trending?.length) {
      trendingTopics.value = data.trending.map((t: any, i: number) => ({
        platforms: ['抖音'], vacancy: 50,
        trendHistory: [t.heat - 20, t.heat - 15, t.heat - 10, t.heat - 8, t.heat - 5, t.heat - 3, t.heat - 1, t.heat],
        ...t, id: i + 1,
      }))
    }
    if (data.recommended?.length) {
      recommendedTopics.value = data.recommended.map((t: any, i: number) => ({
        competition: 35, marketGap: 60, platforms: { douyin: 60, kuaishou: 25, wechat: 15 },
        ...t, id: i + 1,
      }))
    }
    if (data.cases?.length) {
      caseStudies.value = data.cases.map((t: any, i: number) => ({ ...t, id: i + 1 }))
    }
    if (data.inspirations?.length) {
      inspirationCards.value = data.inspirations.map((t: any, i: number) => ({
        tags: [],
        quadrant: t.quadrant || (['character', 'setting', 'conflict', 'hook'][i % 4]),
        ...t, id: i + 1,
      }))
    }
    if (data.hotWords?.length) hotWords.value = data.hotWords
    if (data.searchSummary) searchSummary.value = data.searchSummary
    else if (keyword) searchSummary.value = `「${keyword}」方向：AI 已完成市场分析，数据基于主流短剧平台趋势研判。`
    toast.success('AI 数据已更新')
  } catch (e: any) {
    loadError.value = formatUserFacingErrorMessage(e, '加载失败')
    // 失败时保留默认数据，让页面仍然可见
  } finally {
    isLoading.value = false
  }
}

function handleSearch() { loadAITopics(searchQuery.value.trim() || undefined) }

// 进入灵感实验室时自动拉取一次 AI 热榜数据
onMounted(() => loadAITopics())

function useTopic(topic: any) {
  const prompt = `我想创作一部关于"${topic.title}"的短剧，帮我生成选题和大纲。`
  router.push({ path: '/create', query: { prompt } })
}
function generateOutline(topic: any) {
  router.push({ path: '/outline-editor', query: { logline: topic.title, type: topic.type } })
}
function toggleSave(id: number) {
  const idx = savedTopics.value.indexOf(id)
  if (idx >= 0) savedTopics.value.splice(idx, 1)
  else savedTopics.value.push(id)
}
function toggleCompare(topic: any) {
  const idx = compareCandidates.value.findIndex(c => c.id === topic.id)
  if (idx >= 0) { compareCandidates.value.splice(idx, 1) }
  else if (compareCandidates.value.length < 2) { compareCandidates.value.push(topic) }
  else { toast.error('最多对比 2 个题材，请先取消一个') }
}

async function openCaseAnalysis(caseItem: any) {
  selectedCase.value = caseItem
  caseAnalysis.value = caseItem.nodes?.length ? caseItem : null
  showCaseDrawer.value = true
  if (caseItem.nodes?.length) return
  isAnalyzing.value = true
  try {
    const prompt = `请对这部短剧爆款进行深度解析，严格以 JSON 格式返回，不含代码块标记：

作品：${caseItem.title}，类型：${caseItem.category}，播放量：${caseItem.views}
已知结构：${caseItem.structure}

返回 JSON（nodes 4-5个，emotionCurve 10个整数，highlights 3-4条）：
{"nodes":[{"label":"2-4字","desc":"8字内","type":"hook|escalation|climax|ending"}],"emotionCurve":[10个0-100整数],"highlights":["爽点+星级"],"formula":"一句话成功公式","advice":"仿写注意3点（换行分隔）"}`
    const { data } = await userAccessApi.aiChat({
      messages: [{ role: 'user', content: prompt }],
      context: 'chat', max_tokens: 700,
    })
    const m = data.content.match(/\{[\s\S]*\}/)
    if (m) caseAnalysis.value = { ...caseItem, ...JSON.parse(m[0]) }
    else caseAnalysis.value = caseItem
  } catch { caseAnalysis.value = caseItem; toast.error('解析生成失败') }
  finally { isAnalyzing.value = false }
}
function generateOutlineFromCase() {
  if (!selectedCase.value) return
  router.push({ path: '/outline-editor', query: { template: selectedCase.value.structure } })
}

function cardsForQuadrant(quadrant: string) {
  return inspirationCards.value.filter(c => c.quadrant === quadrant)
}
function boardHas(id: number) { return boardItems.value.some(b => b.id === id) }
function addToBoard(card: any) {
  if (!boardHas(card.id)) { boardItems.value.push(card); toast.success(`已加入：${card.title}`) }
}
function removeFromBoard(id: number) { boardItems.value = boardItems.value.filter(b => b.id !== id) }
function randomizeBoard() {
  boardItems.value = []
  QUADRANTS.forEach(q => {
    const cards = cardsForQuadrant(q.key)
    if (cards.length) boardItems.value.push(cards[Math.floor(Math.random() * cards.length)])
  })
  toast.success('已随机选取4个灵感元素')
}
async function generateFromBoard() {
  if (boardItems.value.length < 2) { toast.error('至少加入 2 个灵感元素'); return }
  isGeneratingBoard.value = true
  try {
    const desc = boardItems.value.map(b => `${b.type}：${b.title}（${b.desc}）`).join('\n')
    const prompt = `根据以下灵感元素组合，生成短剧大纲设想（一句话梗概+主要冲突+三幕结构），约150字：\n\n${desc}`
    const { data } = await userAccessApi.aiChat({
      messages: [{ role: 'user', content: prompt }],
      context: 'outline', max_tokens: 400,
    })
    router.push({ path: '/outline-editor', query: { logline: data.content.slice(0, 80) } })
  } catch { toast.error('AI 生成失败') }
  finally { isGeneratingBoard.value = false }
}
</script>

<template>
  <div class="lab-view h-[calc(100vh-3.5rem)] overflow-auto">
    <div class="max-w-7xl mx-auto px-6 py-8">

      <!-- 标题 -->
      <div class="text-center mb-8">
        <h1 class="text-3xl font-bold mb-2 flex items-center justify-center gap-2">
          <Lightbulb class="h-8 w-8 text-amber-500" />剧本灵感实验室
        </h1>
        <p class="text-muted-foreground">AI 市场分析 · 热榜洞察 · 爆款解析 · 灵感组合</p>
      </div>

      <!-- 加载错误提示，点击重试不重刷整页 -->
      <div v-if="loadError" class="max-w-2xl mx-auto mb-6 rounded-xl border border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300 px-4 py-3 text-sm flex items-center justify-between gap-3">
        <span>{{ loadError }}</span>
        <Button size="sm" variant="outline" @click="loadAITopics()">重试</Button>
      </div>

      <!-- 搜索栏 -->
      <div class="max-w-2xl mx-auto mb-10">
        <div class="relative">
          <Input v-model="searchQuery" placeholder="搜索题材关键词，AI 将围绕关键词生成市场分析..."
            class="h-12 pl-12 pr-36 text-base" @keyup.enter="handleSearch" />
          <Search class="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
          <Button class="absolute right-1.5 top-1/2 -translate-y-1/2 h-9" @click="handleSearch" :disabled="isLoading">
            <Globe class="h-3.5 w-3.5 mr-1.5" />AI 全网搜索
          </Button>
        </div>
        <Transition name="fade">
          <div v-if="searchSummary" class="mt-3 text-sm bg-primary/5 border border-primary/20 rounded-xl px-4 py-3 flex items-start gap-2">
            <Sparkles class="h-4 w-4 text-primary shrink-0 mt-0.5" />
            <span class="text-muted-foreground">{{ searchSummary }}</span>
          </div>
        </Transition>
        <div class="flex gap-3 mt-2.5 text-xs text-muted-foreground justify-center">
          <span>热搜：</span>
          <button v-for="kw in ['重生逆袭','甜宠虐恋','悬疑推理','系统流','古装权谋']" :key="kw"
            class="hover:text-primary transition-colors" @click="searchQuery = kw; handleSearch()">{{ kw }}</button>
        </div>
      </div>

      <!-- Tabs -->
      <Tabs default-value="trending" class="w-full">
        <div class="flex items-center justify-between mb-5">
          <TabsList>
            <TabsTrigger value="trending" class="gap-1.5"><TrendingUp class="h-4 w-4" />热榜洞察</TabsTrigger>
            <TabsTrigger value="recommend" class="gap-1.5"><Sparkles class="h-4 w-4" />题材推荐</TabsTrigger>
            <TabsTrigger value="cases" class="gap-1.5"><BarChart3 class="h-4 w-4" />爆款解析</TabsTrigger>
            <TabsTrigger value="inspiration" class="gap-1.5"><Lightbulb class="h-4 w-4" />灵感元素</TabsTrigger>
          </TabsList>
          <Button variant="outline" size="sm" :disabled="isLoading" @click="loadAITopics()">
            <RefreshCw class="h-4 w-4 mr-1.5" :class="{ 'animate-spin': isLoading }" />
            {{ isLoading ? 'AI 分析中...' : 'AI 刷新数据' }}
          </Button>
        </div>

        <!-- ══ 热榜洞察 ══ -->
        <TabsContent value="trending" class="space-y-6">
          <!-- 筛选栏 -->
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex gap-1.5">
              <button v-for="p in PLATFORMS" :key="p.key"
                class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border"
                :class="platformFilter === p.key
                  ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                  : 'bg-card border-border hover:border-primary/50 text-muted-foreground hover:text-foreground'"
                @click="platformFilter = p.key">{{ p.label }}</button>
            </div>
            <div class="flex gap-1.5">
              <button v-for="tp in [{ key: '7d', label: '近 7 天' }, { key: '30d', label: '近 30 天' }]" :key="tp.key"
                class="px-3 py-1.5 rounded-lg text-sm transition-colors border"
                :class="timePeriod === tp.key
                  ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                  : 'bg-card border-border hover:border-primary/50 text-muted-foreground'"
                @click="timePeriod = tp.key">{{ tp.label }}</button>
            </div>
          </div>

          <!-- 折线趋势图 -->
          <div class="bg-card border rounded-xl p-5">
            <div class="flex items-center justify-between mb-4">
              <h3 class="font-semibold flex items-center gap-2">
                <BarChart2 class="h-4 w-4 text-primary" />热度趋势折线图
              </h3>
              <span class="text-xs text-muted-foreground">{{ timePeriod === '7d' ? '近 7 天' : '近 30 天' }}真实比例</span>
            </div>
            <svg viewBox="0 0 600 130" class="w-full" style="height:120px">
              <line v-for="y in [0, 40, 80, 120]" :key="y" x1="0" :y1="y" x2="600" :y2="y" stroke="currentColor" stroke-opacity="0.06" />
              <path v-for="(topic, i) in filteredTrending" :key="topic.id"
                :d="multiTrendPath(i)"
                :stroke="LINE_COLORS[i % LINE_COLORS.length]"
                stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <div class="flex flex-wrap gap-4 mt-3">
              <div v-for="(topic, i) in filteredTrending" :key="topic.id" class="flex items-center gap-1.5 text-xs">
                <div class="w-6 h-0.5 rounded-full" :style="{ background: LINE_COLORS[i % LINE_COLORS.length] }"></div>
                <span class="text-muted-foreground">{{ topic.title }}</span>
              </div>
            </div>
          </div>

          <!-- 题材卡片 -->
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div v-for="topic in filteredTrending" :key="topic.id"
              class="bg-card border rounded-xl p-4 hover:shadow-md transition-all group cursor-pointer"
              @click="useTopic(topic)">
              <div class="flex items-start justify-between mb-2">
                <div>
                  <h3 class="font-semibold group-hover:text-primary transition-colors">{{ topic.title }}</h3>
                  <div class="flex items-center gap-2 mt-1">
                    <Badge variant="secondary" class="text-xs">
                      {{ topic.category === 'male' ? '男频' : topic.category === 'female' ? '女频' : '混合' }}
                    </Badge>
                    <span class="text-xs font-medium" :class="topic.change.startsWith('+') ? 'text-emerald-500' : 'text-rose-500'">
                      {{ topic.change }}
                    </span>
                  </div>
                </div>
                <div class="text-right shrink-0">
                  <div class="text-2xl font-bold text-orange-500">{{ topic.heat }}</div>
                  <div class="text-xs text-muted-foreground">热度</div>
                </div>
              </div>
              <!-- 迷你趋势折线 -->
              <svg viewBox="0 0 100 32" class="w-full h-7 my-1">
                <path :d="trendSparkPath(topic.trendHistory || [])"
                  :stroke="topic.change.startsWith('+') ? '#10b981' : '#f43f5e'"
                  stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <div class="flex flex-wrap gap-1.5 mb-2">
                <Badge v-for="tag in topic.tags" :key="tag" variant="outline" class="text-xs">{{ tag }}</Badge>
              </div>
              <div class="flex items-center justify-between text-xs text-muted-foreground">
                <span>空白度：<span :class="topic.vacancy > 60 ? 'text-emerald-500 font-medium' : topic.vacancy > 40 ? 'text-amber-500 font-medium' : 'text-rose-500 font-medium'">{{ topic.vacancy }}%</span></span>
                <div class="flex gap-1">
                  <span v-for="p in (topic.platforms || [])" :key="p"
                    class="px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[10px]">{{ p }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 热词云 -->
          <div class="bg-card border rounded-xl p-5">
            <h3 class="font-semibold mb-4 flex items-center gap-2">
              <Zap class="h-4 w-4 text-amber-500" />当前热词云
              <span class="text-xs text-muted-foreground font-normal ml-1">点击词语快速搜索</span>
            </h3>
            <div class="flex flex-wrap gap-2 items-center justify-center min-h-[80px] py-2">
              <button v-for="word in hotWords" :key="word.word"
                class="rounded-full border px-3 py-1 hover:border-primary hover:text-primary transition-colors"
                :style="{
                  fontSize: `${10 + Math.round((word.weight / 100) * 8)}px`,
                  opacity: 0.45 + (word.weight / 100) * 0.55,
                }"
                @click="searchQuery = word.word; handleSearch()">{{ word.word }}</button>
            </div>
          </div>
        </TabsContent>

        <!-- ══ 题材推荐 ══ -->
        <TabsContent value="recommend" class="space-y-5">
          <!-- 对比条 -->
          <Transition name="fade">
            <div v-if="compareCandidates.length > 0"
              class="bg-primary/5 border border-primary/20 rounded-xl px-4 py-3 flex items-center justify-between">
              <div class="flex items-center gap-2 text-sm flex-wrap">
                <GitCompare class="h-4 w-4 text-primary shrink-0" />
                <span class="font-medium">对比中：</span>
                <template v-for="(c, i) in compareCandidates" :key="c.id">
                  <div class="flex items-center gap-1">
                    <Badge class="text-xs max-w-36 truncate">{{ c.title }}</Badge>
                    <button @click="toggleCompare(c)" class="text-muted-foreground hover:text-foreground text-sm">×</button>
                  </div>
                  <span v-if="i < compareCandidates.length - 1" class="text-muted-foreground font-bold">VS</span>
                </template>
              </div>
              <Button size="sm" :disabled="compareCandidates.length < 2" @click="showCompare = true">
                查看对比 →
              </Button>
            </div>
          </Transition>

          <!-- 题材卡片 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div v-for="topic in recommendedTopics" :key="topic.id"
              class="bg-card border rounded-xl p-5 hover:shadow-md transition-all group">
              <div class="flex items-start justify-between mb-2">
                <Badge class="text-xs">{{ topic.type }}</Badge>
                <div class="flex items-center gap-2">
                  <button @click.stop="toggleSave(topic.id)" class="transition-colors">
                    <Star class="h-4 w-4 transition-all"
                      :class="savedTopics.includes(topic.id) ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground hover:text-amber-400'" />
                  </button>
                  <button @click.stop="toggleCompare(topic)"
                    class="text-xs px-2 py-0.5 rounded border transition-all"
                    :class="compareCandidates.find(c => c.id === topic.id)
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border hover:border-primary text-muted-foreground hover:text-primary'">
                    对比
                  </button>
                </div>
              </div>
              <h3 class="font-semibold text-base mb-1.5 group-hover:text-primary transition-colors">{{ topic.title }}</h3>
              <p class="text-sm text-muted-foreground mb-4">{{ topic.reason }}</p>

              <!-- 三维指标 -->
              <div class="grid grid-cols-3 gap-2 mb-4">
                <div class="text-center bg-muted/40 rounded-lg py-2.5">
                  <div class="text-xl font-bold text-primary">{{ topic.score }}</div>
                  <div class="text-[10px] text-muted-foreground mt-0.5">综合评分</div>
                </div>
                <div class="text-center bg-muted/40 rounded-lg py-2.5">
                  <div class="text-xl font-bold"
                    :class="topic.marketGap > 70 ? 'text-emerald-500' : topic.marketGap > 50 ? 'text-amber-500' : 'text-rose-500'">
                    {{ topic.marketGap }}
                  </div>
                  <div class="text-[10px] text-muted-foreground mt-0.5">市场空白度</div>
                </div>
                <div class="text-center bg-muted/40 rounded-lg py-2.5">
                  <div class="text-xl font-bold"
                    :class="topic.competition < 30 ? 'text-emerald-500' : topic.competition < 60 ? 'text-amber-500' : 'text-rose-500'">
                    {{ topic.competition }}
                  </div>
                  <div class="text-[10px] text-muted-foreground mt-0.5">竞品指数</div>
                </div>
              </div>

              <!-- 平台分布小条 -->
              <div class="space-y-1.5 mb-4">
                <div class="text-xs text-muted-foreground">平台分布</div>
                <div v-for="(val, key) in topic.platforms" :key="key" class="flex items-center gap-2 text-xs">
                  <span class="w-8 text-right text-muted-foreground">{{ { douyin: '抖音', kuaishou: '快手', wechat: '微信' }[key as string] || key }}</span>
                  <div class="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div class="h-1.5 rounded-full bg-primary/70 transition-all" :style="{ width: `${val}%` }"></div>
                  </div>
                  <span class="text-muted-foreground w-8">{{ val }}%</span>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="flex gap-2">
                <Button size="sm" class="flex-1 text-xs h-8" @click="generateOutline(topic)">
                  <BookOpen class="h-3 w-3 mr-1" />一键生成大纲
                </Button>
                <Button size="sm" variant="outline" class="text-xs h-8 px-3" @click="useTopic(topic)">
                  <ChevronRight class="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </TabsContent>

        <!-- ══ 爆款解析 ══ -->
        <TabsContent value="cases" class="space-y-4">
          <p class="text-sm text-muted-foreground">点击「查看解析」获取 AI 结构深度分析：节点图 · 情绪曲线 · 爽点标注 · 仿写建议</p>
          <div v-for="caseItem in caseStudies" :key="caseItem.id"
            class="bg-card border rounded-xl p-5 hover:shadow-md transition-shadow">
            <div class="flex items-start justify-between mb-3">
              <div>
                <div class="flex items-center gap-2 mb-1">
                  <Badge>{{ caseItem.category }}</Badge>
                  <h3 class="font-semibold text-lg">{{ caseItem.title }}</h3>
                </div>
                <div class="text-sm text-muted-foreground">播放量 {{ caseItem.views }} · 钩子：{{ caseItem.hook }}</div>
              </div>
              <Button size="sm" class="shrink-0 gap-1.5" @click="openCaseAnalysis(caseItem)">
                <BarChart3 class="h-3.5 w-3.5" />查看解析
              </Button>
            </div>
            <div class="bg-muted/50 rounded-lg p-3 mb-3">
              <div class="text-xs text-muted-foreground mb-1">结构分析</div>
              <div class="text-sm">{{ caseItem.structure }}</div>
            </div>
            <!-- 节点预览 -->
            <div v-if="(caseItem as any).nodes?.length" class="flex items-center gap-1.5 flex-wrap">
              <template v-for="(node, i) in (caseItem as any).nodes" :key="i">
                <div class="text-xs px-2.5 py-1 rounded-full border font-medium"
                  :style="{ borderColor: NODE_COLORS[(node as any).type], color: NODE_COLORS[(node as any).type], background: NODE_COLORS[(node as any).type] + '18' }">
                  {{ (node as any).label }}
                </div>
                <ChevronRight v-if="Number(i) < (((caseItem as any).nodes || []).length - 1)" class="h-3 w-3 text-muted-foreground/30 shrink-0" />
              </template>
            </div>
          </div>
        </TabsContent>

        <!-- ══ 灵感元素 ══ -->
        <TabsContent value="inspiration">
          <div class="flex gap-5 items-start">
            <!-- 左侧：四象限卡片墙 -->
            <div class="flex-1 min-w-0">
              <div class="grid grid-cols-2 gap-4">
                <div v-for="q in QUADRANTS" :key="q.key"
                  class="rounded-xl border p-4"
                  :class="quadrantStyleFor((q as any).color).card">
                  <div class="flex items-center justify-between mb-3">
                    <h3 class="font-semibold text-sm flex items-center gap-1.5">
                      <component :is="q.icon" class="h-4 w-4" />{{ q.label }}
                    </h3>
                    <Badge variant="outline" class="text-[10px]">{{ cardsForQuadrant(q.key).length }}个</Badge>
                  </div>
                  <div class="space-y-2">
                    <div v-for="card in cardsForQuadrant(q.key)" :key="card.id"
                      class="bg-white/70 dark:bg-black/20 rounded-lg p-2.5 hover:bg-white/90 dark:hover:bg-black/30 transition-colors">
                      <div class="flex items-start justify-between gap-2 mb-1">
                        <span class="font-semibold text-sm leading-tight">{{ card.title }}</span>
                        <button
                          class="shrink-0 w-5 h-5 rounded-full flex items-center justify-center transition-colors"
                          :class="boardHas(card.id) ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-900/50' : 'bg-muted text-muted-foreground hover:bg-primary/10 hover:text-primary'"
                          @click="boardHas(card.id) ? removeFromBoard(card.id) : addToBoard(card)">
                          <component :is="boardHas(card.id) ? Check : Plus" class="h-3 w-3" />
                        </button>
                      </div>
                      <p class="text-xs text-muted-foreground leading-relaxed mb-1.5">{{ card.desc }}</p>
                      <div class="flex items-center justify-between">
                        <div class="flex gap-1 flex-wrap">
                          <span v-for="tag in (card.tags || []).slice(0, 2)" :key="tag"
                            class="px-1.5 py-0.5 rounded text-[10px] font-medium"
                            :class="quadrantStyleFor((q as any).color).badge">{{ tag }}</span>
                        </div>
                        <span class="text-orange-500 text-[10px] shrink-0">热 {{ card.heat }}</span>
                      </div>
                    </div>
                    <div v-if="cardsForQuadrant(q.key).length === 0"
                      class="text-center py-5 text-xs text-muted-foreground/60">暂无数据，点击 AI 刷新</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 右侧：创作板 -->
            <div class="w-60 shrink-0 sticky top-4">
              <div class="bg-card border rounded-xl p-4">
                <h3 class="font-semibold text-sm mb-1 flex items-center gap-1.5">
                  <Sparkles class="h-4 w-4 text-primary" />创作板
                  <Badge variant="secondary" class="ml-auto text-xs">{{ boardItems.length }}</Badge>
                </h3>
                <p class="text-xs text-muted-foreground mb-3">点击 <Plus class="inline h-3 w-3" /> 将灵感加入</p>

                <div v-if="boardItems.length === 0" class="text-center py-6 text-xs text-muted-foreground border border-dashed rounded-lg">
                  从左侧四象限各选一个元素，组合成完整设定
                </div>
                <div v-else class="space-y-1.5 mb-4">
                  <div v-for="item in boardItems" :key="item.id"
                    class="flex items-center gap-2 rounded-lg bg-muted/50 px-2.5 py-2 text-xs group">
                    <div class="w-1.5 h-1.5 rounded-full shrink-0 bg-primary/60"></div>
                    <span class="flex-1 font-medium truncate">{{ item.title }}</span>
                    <button @click="removeFromBoard(item.id)"
                      class="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-rose-500 transition-all shrink-0">
                      <X class="h-3 w-3" />
                    </button>
                  </div>
                </div>

                <div v-if="boardItems.length >= 2" class="space-y-2 mb-3">
                  <p class="text-xs text-muted-foreground">已选 {{ boardItems.length }} 个元素，AI 将组合成完整设定并跳转大纲编辑</p>
                  <Button class="w-full text-xs h-9 bg-gradient-to-r from-primary to-purple-600 hover:opacity-90"
                    :disabled="isGeneratingBoard" @click="generateFromBoard">
                    <Zap class="h-3.5 w-3.5 mr-1.5" />
                    {{ isGeneratingBoard ? '生成中...' : '组合生成大纲' }}
                  </Button>
                </div>

                <div class="pt-3 border-t">
                  <Button variant="outline" size="sm" class="w-full text-xs" @click="randomizeBoard">
                    <RefreshCw class="h-3 w-3 mr-1.5" />随机一键选套
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>

    <!-- ══ 爆款解析抽屉 ══ -->
    <Transition name="drawer">
      <div v-if="showCaseDrawer"
        class="fixed inset-y-0 right-0 w-[480px] bg-card border-l shadow-2xl z-50 flex flex-col overflow-hidden">
        <!-- 头部 -->
        <div class="px-5 py-4 border-b flex items-center justify-between shrink-0 bg-card">
          <div class="flex items-center gap-2 min-w-0">
            <BarChart3 class="h-4 w-4 text-primary shrink-0" />
            <h2 class="font-semibold text-sm truncate">{{ selectedCase?.title }}</h2>
          </div>
          <button @click="showCaseDrawer = false" class="text-muted-foreground hover:text-foreground transition-colors shrink-0 ml-3">
            <X class="h-5 w-5" />
          </button>
        </div>

        <!-- 内容 -->
        <div class="flex-1 overflow-y-auto p-5 space-y-6">
          <!-- Loading -->
          <div v-if="isAnalyzing" class="flex flex-col items-center justify-center py-16 gap-4">
            <RefreshCw class="h-8 w-8 text-primary animate-spin" />
            <p class="text-sm text-muted-foreground">AI 正在分析爆款结构…</p>
          </div>

          <template v-else>
            <!-- Meta -->
            <div class="flex items-center gap-2 flex-wrap text-sm">
              <Badge>{{ selectedCase?.category }}</Badge>
              <span class="text-muted-foreground">播放 {{ selectedCase?.views }}</span>
              <span class="text-muted-foreground">· 钩子：{{ selectedCase?.hook }}</span>
            </div>

            <!-- 结构节点图 -->
            <div>
              <h3 class="text-sm font-semibold mb-3 flex items-center gap-1.5">
                <Zap class="h-4 w-4 text-amber-500" />结构节点图
              </h3>
              <div class="flex items-center gap-2 flex-wrap">
                <template v-for="(node, i) in ((caseAnalysis || selectedCase)?.nodes || [])" :key="i">
                  <div class="flex flex-col items-center shrink-0">
                    <div class="w-2 h-2 rounded-full mb-1" :style="{ background: NODE_COLORS[(node as any).type] }"></div>
                    <div class="rounded-xl px-3 py-2 text-center border"
                      :style="{ borderColor: NODE_COLORS[(node as any).type], color: NODE_COLORS[(node as any).type], background: NODE_COLORS[(node as any).type] + '15' }">
                      <div class="text-xs font-semibold">{{ (node as any).label }}</div>
                      <div class="text-[10px] opacity-70 mt-0.5 max-w-[60px] truncate" :title="(node as any).desc">{{ (node as any).desc }}</div>
                    </div>
                  </div>
                  <div v-if="Number(i) < (((caseAnalysis || selectedCase)?.nodes || []).length - 1)"
                    class="flex-1 h-px bg-border min-w-[8px]"></div>
                </template>
                <p v-if="!((caseAnalysis || selectedCase)?.nodes?.length)" class="text-xs text-muted-foreground">暂无节点数据</p>
              </div>
              <!-- 图例 -->
              <div class="flex gap-3 mt-3 flex-wrap">
                <div v-for="[type, color] in Object.entries(NODE_COLORS)" :key="type" class="flex items-center gap-1 text-xs">
                  <div class="w-2 h-2 rounded-full" :style="{ background: color }"></div>
                  <span class="text-muted-foreground">{{ nodeLabel(type) }}</span>
                </div>
              </div>
            </div>

            <!-- 情绪曲线 -->
            <div>
              <h3 class="text-sm font-semibold mb-3 flex items-center gap-1.5">
                <TrendingUp class="h-4 w-4 text-primary" />情绪曲线
              </h3>
              <div class="bg-muted/30 rounded-xl p-3">
                <svg viewBox="0 0 400 80" class="w-full" style="height:80px">
                  <defs>
                    <linearGradient id="eGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.25" />
                      <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.0" />
                    </linearGradient>
                  </defs>
                  <line v-for="y in [20, 40, 60]" :key="y" x1="0" :y1="y" x2="400" :y2="y" stroke="currentColor" stroke-opacity="0.08" />
                  <path :d="emotionAreaPath((caseAnalysis || selectedCase)?.emotionCurve || [])" fill="url(#eGrad)" />
                  <path :d="emotionCurvePath((caseAnalysis || selectedCase)?.emotionCurve || [])"
                    stroke="#3b82f6" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                <div class="flex justify-between text-[10px] text-muted-foreground mt-1 px-1">
                  <span>第1集</span><span>第5集</span><span>第10集</span>
                </div>
              </div>
            </div>

            <!-- 爽点标注 -->
            <div v-if="(caseAnalysis || selectedCase)?.highlights?.length">
              <h3 class="text-sm font-semibold mb-3 flex items-center gap-1.5">
                <Star class="h-4 w-4 text-amber-500" />爽点标注
              </h3>
              <div class="space-y-2">
                <div v-for="(h, i) in (caseAnalysis || selectedCase)?.highlights" :key="i"
                  class="bg-amber-50 dark:bg-amber-950/20 border border-amber-200/60 dark:border-amber-800/50 rounded-lg px-3 py-2.5 text-sm">
                  {{ h }}
                </div>
              </div>
            </div>

            <!-- 公式 + 建议 -->
            <div v-if="(caseAnalysis as any)?.formula || (caseAnalysis as any)?.advice" class="space-y-3">
              <div v-if="(caseAnalysis as any)?.formula" class="bg-primary/5 border border-primary/10 rounded-xl p-4">
                <div class="text-xs text-muted-foreground mb-1.5">爆款公式</div>
                <div class="text-sm font-medium">{{ (caseAnalysis as any).formula }}</div>
              </div>
              <div v-if="(caseAnalysis as any)?.advice" class="bg-muted/50 rounded-xl p-4">
                <div class="text-xs text-muted-foreground mb-1.5">仿写建议</div>
                <div class="text-sm whitespace-pre-line leading-relaxed">{{ (caseAnalysis as any).advice }}</div>
              </div>
            </div>
          </template>
        </div>

        <!-- 底部按钮 -->
        <div class="px-5 py-4 border-t shrink-0">
          <Button class="w-full bg-gradient-to-r from-primary to-purple-600 hover:opacity-90 gap-2"
            @click="generateOutlineFromCase">
            <BookOpen class="h-4 w-4" />一键仿写大纲
          </Button>
        </div>
      </div>
    </Transition>

    <!-- 抽屉遮罩 -->
    <Transition name="fade">
      <div v-if="showCaseDrawer" class="fixed inset-0 bg-black/40 z-40" @click="showCaseDrawer = false" />
    </Transition>

    <!-- ══ 题材对比 Modal ══ -->
    <Transition name="fade">
      <div v-if="showCompare && compareCandidates.length === 2"
        class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6">
        <div class="bg-card rounded-2xl w-full max-w-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
          <div class="px-6 py-4 border-b flex items-center justify-between shrink-0">
            <h2 class="font-semibold flex items-center gap-2"><GitCompare class="h-5 w-5 text-primary" />题材深度对比</h2>
            <button @click="showCompare = false"><X class="h-5 w-5 text-muted-foreground hover:text-foreground" /></button>
          </div>
          <div class="grid grid-cols-2 divide-x overflow-y-auto">
            <div v-for="topic in compareCandidates" :key="topic.id" class="p-5 space-y-4">
              <div>
                <Badge class="mb-2">{{ topic.type }}</Badge>
                <h3 class="font-semibold">{{ topic.title }}</h3>
                <p class="text-sm text-muted-foreground mt-1">{{ topic.reason }}</p>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div class="bg-muted/40 rounded-lg p-3 text-center">
                  <div class="text-xl font-bold text-primary">{{ topic.score }}</div>
                  <div class="text-[10px] text-muted-foreground">综合评分</div>
                </div>
                <div class="bg-muted/40 rounded-lg p-3 text-center">
                  <div class="text-xl font-bold"
                    :class="topic.marketGap > 70 ? 'text-emerald-500' : 'text-amber-500'">{{ topic.marketGap }}</div>
                  <div class="text-[10px] text-muted-foreground">市场空白</div>
                </div>
                <div class="bg-muted/40 rounded-lg p-3 text-center">
                  <div class="text-xl font-bold"
                    :class="topic.competition < 30 ? 'text-emerald-500' : 'text-rose-500'">{{ topic.competition }}</div>
                  <div class="text-[10px] text-muted-foreground">竞品指数</div>
                </div>
                <div class="bg-muted/40 rounded-lg p-3 text-center">
                  <div class="text-xl font-bold text-purple-500">{{ topic.novelty }}</div>
                  <div class="text-[10px] text-muted-foreground">新颖度</div>
                </div>
              </div>
              <!-- 平台分布 -->
              <div class="space-y-1.5">
                <div class="text-xs text-muted-foreground">平台分布</div>
                <div v-for="(val, key) in topic.platforms" :key="key" class="flex items-center gap-2 text-xs">
                  <span class="w-8 text-right text-muted-foreground">{{ { douyin: '抖音', kuaishou: '快手', wechat: '微信' }[key as string] }}</span>
                  <div class="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div class="h-1.5 rounded-full bg-primary/70" :style="{ width: `${val}%` }"></div>
                  </div>
                  <span class="text-muted-foreground">{{ val }}%</span>
                </div>
              </div>
              <Button class="w-full text-sm h-9" @click="generateOutline(topic); showCompare = false">
                <BookOpen class="h-4 w-4 mr-1.5" />选这个，一键生成大纲
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.drawer-enter-active, .drawer-leave-active { transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1); }
.drawer-enter-from, .drawer-leave-to { transform: translateX(100%); }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
