<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import {
  ArrowLeft,
  Save,
  Wand2,
  Plus,
  Trash2,
  ChevronRight,
  Sparkles,
  Lightbulb,
  AlertCircle,
  CheckCircle2,
  Edit3,
  RefreshCw,
  FileText,
  Target,
  Users,
  BookOpen,
  Zap,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { projectsV2Api, taskApi } from '@/api/client'
import { formatUserFacingErrorMessage } from '@/api/http'

const route = useRoute()
const router = useRouter()

// 从路由参数获取项目信息
const projectId = ref(route.params.projectId as string)
const taskId = ref(route.query.task as string || '')
const mode = ref(route.query.mode as string || 'import')

// 项目信息
const projectName = ref('')
const projectType = ref('')

// 原始大纲内容
const rawOutline = ref('')
const isAnalyzing = ref(false)
let analysisTimers: ReturnType<typeof setTimeout>[] = []

onBeforeUnmount(() => {
  analysisTimers.forEach(t => clearTimeout(t))
  analysisTimers = []
})
const analysisProgress = ref(0)

// 分析结果
interface AnalysisResult {
  // 题材分析
  genre: {
    category: string
    subCategory: string
    target: string
    confidence: number
  }
  // 核心卖点
  sellingPoints: {
    logline?: string
    worldview?: string
    hook: string
    conflict: string
    uniqueness: string
    marketFit: number
    suggestions: string[]
  }
  // 人物设定
  characters: CharacterProfile[]
  // 结构分析
  structure: {
    pacing: 'slow' | 'medium' | 'fast'
    rhythm: string[]
    issues: string[]
    suggestions: string[]
  }
  // 分集详情
  episodes: EpisodeAnalysis[]
}

interface CharacterProfile {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'cameo'
  traits: string[]
  motivation: string
  arc: string
  voiceprint: string
  inner_need: string
  resource: string
  first_appearance_function: string
  relationship_tension: string
  secret: string
  conflicts: string[]
  suggestions: string[]
}

interface EpisodeAnalysis {
  id: string
  episodeNumber: number
  title: string
  summary: string
  conflict: string
  turning: string
  main_scene: string
  relationship_change: string
  info_revealed: string
  satisfaction_type: string
  stage: string
  // 开场钩子
  hook: {
    content: string
    type: string
    strength: number
    suggestions: string[]
  }
  // 核心情节点
  plotPoints: PlotPoint[]
  // 情绪曲线
  emotionArc: {
    stage: string
    level: number
    description: string
  }[]
  // 场景细分
  scenes: SceneAnalysis[]
  // 尾钩
  cliffhanger: {
    content: string
    type: string
    strength: number
    suggestions: string[]
  }
  // 整体评估
  evaluation: {
    pacing: number
    tension: number
    completeness: number
    issues: string[]
    suggestions: string[]
  }
}

interface PlotPoint {
  id: string
  type: 'setup' | 'inciting' | 'rising' | 'climax' | 'falling' | 'resolution'
  content: string
  purpose: string
  emotion: string
  suggestions: string[]
}

interface SceneAnalysis {
  id: string
  sceneNumber: number
  time: string
  location: string
  characters: string[]
  action: string
  emotion: string
  purpose: string
  duration: number
  suggestions: string[]
}

const plotPointTypes: PlotPoint['type'][] = ['setup', 'inciting', 'rising', 'climax', 'falling', 'resolution']

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' ? value as Record<string, any> : {}
}

function stringValue(value: unknown, fallback = '') {
  if (typeof value === 'string') return value
  if (value == null) return fallback
  return String(value)
}

function numberValue(value: unknown, fallback = 0) {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(item => stringValue(item).trim()).filter(Boolean)
  if (typeof value === 'string' && value.trim()) return [value.trim()]
  return []
}

function normalizeHook(value: unknown, fallbackContent = ''): EpisodeAnalysis['hook'] {
  const source = asRecord(value)
  const content = value && typeof value === 'object' ? source.content : value
  return {
    content: stringValue(content, fallbackContent),
    type: stringValue(source.type, 'standard'),
    strength: numberValue(source.strength, 0),
    suggestions: stringArray(source.suggestions),
  }
}

function normalizePlotPoint(value: unknown, pointIndex: number, episodeIndex: number): PlotPoint {
  const source = asRecord(value)
  const type = plotPointTypes.includes(source.type) ? source.type as PlotPoint['type'] : 'rising'
  const content = value && typeof value === 'object' ? source.content : value
  return {
    id: stringValue(source.id, `pp-${episodeIndex}-${pointIndex}`),
    type,
    content: stringValue(content),
    purpose: stringValue(source.purpose),
    emotion: stringValue(source.emotion),
    suggestions: stringArray(source.suggestions),
  }
}

function normalizeScene(value: unknown, sceneIndex: number, episodeIndex: number): SceneAnalysis {
  const source = asRecord(value)
  return {
    id: stringValue(source.id, `scene-${episodeIndex + 1}-${sceneIndex + 1}`),
    sceneNumber: numberValue(source.sceneNumber ?? source.scene_number, sceneIndex + 1),
    time: stringValue(source.time, '日'),
    location: stringValue(source.location ?? source.location_name),
    characters: stringArray(source.characters),
    action: stringValue(source.action ?? source.content),
    emotion: stringValue(source.emotion),
    purpose: stringValue(source.purpose),
    duration: numberValue(source.duration, 30),
    suggestions: stringArray(source.suggestions),
  }
}

function normalizeEmotionArc(value: unknown): EpisodeAnalysis['emotionArc'] {
  if (!Array.isArray(value)) return []
  return value.map((item, index) => {
    const source = asRecord(item)
    return {
      stage: stringValue(source.stage, `阶段${index + 1}`),
      level: numberValue(source.level, 0),
      description: stringValue(source.description),
    }
  })
}

function normalizeEvaluation(value: unknown): EpisodeAnalysis['evaluation'] {
  const source = asRecord(value)
  return {
    pacing: numberValue(source.pacing, 0),
    tension: numberValue(source.tension, 0),
    completeness: numberValue(source.completeness, 0),
    issues: stringArray(source.issues),
    suggestions: stringArray(source.suggestions),
  }
}

function normalizeEpisode(value: unknown, index: number): EpisodeAnalysis {
  const source = asRecord(value)
  const episodeNumber = numberValue(source.episodeNumber ?? source.episode_number, index + 1)
  const plotPoints = Array.isArray(source.plotPoints)
    ? source.plotPoints.map((point, pointIndex) => normalizePlotPoint(point, pointIndex, index))
    : []
  const scenes = Array.isArray(source.scenes)
    ? source.scenes.map((scene, sceneIndex) => normalizeScene(scene, sceneIndex, index))
    : []

  return {
    id: stringValue(source.id, String(episodeNumber)),
    episodeNumber,
    title: stringValue(source.title, `第${episodeNumber}集`),
    summary: stringValue(source.summary ?? source.main_event),
    conflict: stringValue(source.conflict ?? source.main_conflict ?? source.episode_conflict),
    turning: stringValue(source.turning ?? source.twist ?? source.climax),
    main_scene: stringValue(source.main_scene ?? source.mainScene),
    relationship_change: stringValue(source.relationship_change ?? source.relationshipChange),
    info_revealed: stringValue(source.info_revealed ?? source.infoRevealed),
    satisfaction_type: stringValue(source.satisfaction_type ?? source.satisfactionType),
    stage: stringValue(source.stage),
    hook: normalizeHook(source.hook),
    plotPoints,
    emotionArc: normalizeEmotionArc(source.emotionArc),
    scenes,
    cliffhanger: normalizeHook(source.cliffhanger),
    evaluation: normalizeEvaluation(source.evaluation),
  }
}

function normalizeCharacter(value: unknown, index: number): CharacterProfile {
  const source = asRecord(value)
  const roles: CharacterProfile['role'][] = ['protagonist', 'antagonist', 'supporting', 'cameo']
  const role = roles.includes(source.role) ? source.role as CharacterProfile['role'] : 'supporting'
  return {
    id: stringValue(source.id, `char-${index + 1}`),
    name: stringValue(source.name),
    role,
    traits: stringArray(source.traits),
    motivation: stringValue(source.motivation),
    arc: stringValue(source.arc),
    voiceprint: stringValue(source.voiceprint ?? source.voicePrint),
    inner_need: stringValue(source.inner_need ?? source.innerNeed),
    resource: stringValue(source.resource),
    first_appearance_function: stringValue(source.first_appearance_function ?? source.firstAppearanceFunction),
    relationship_tension: stringValue(source.relationship_tension ?? source.relationshipTension),
    secret: stringValue(source.secret),
    conflicts: stringArray(source.conflicts),
    suggestions: stringArray(source.suggestions),
  }
}

function normalizeAnalysisResult(value: unknown): AnalysisResult {
  const source = asRecord(value)
  const genre = asRecord(source.genre)
  const sellingPoints = asRecord(source.sellingPoints)
  const structure = asRecord(source.structure)
  const pacing = structure.pacing === 'slow' || structure.pacing === 'fast' ? structure.pacing : 'medium'

  return {
    genre: {
      category: stringValue(genre.category),
      subCategory: stringValue(genre.subCategory),
      target: stringValue(genre.target),
      confidence: numberValue(genre.confidence, 0),
    },
    sellingPoints: {
      logline: stringValue(sellingPoints.logline),
      worldview: stringValue(sellingPoints.worldview),
      hook: stringValue(sellingPoints.hook),
      conflict: stringValue(sellingPoints.conflict),
      uniqueness: stringValue(sellingPoints.uniqueness),
      marketFit: numberValue(sellingPoints.marketFit, 0),
      suggestions: stringArray(sellingPoints.suggestions),
    },
    characters: Array.isArray(source.characters)
      ? source.characters.map((character, index) => normalizeCharacter(character, index))
      : [],
    structure: {
      pacing,
      rhythm: stringArray(structure.rhythm),
      issues: stringArray(structure.issues),
      suggestions: stringArray(structure.suggestions),
    },
    episodes: Array.isArray(source.episodes)
      ? source.episodes.map((episode, index) => normalizeEpisode(episode, index))
      : [],
  }
}

function clampEpisodeIndex(index: number, count: number) {
  if (count <= 0) return 0
  return Math.min(Math.max(Math.trunc(Number(index) || 0), 0), count - 1)
}

const analysisResult = ref<AnalysisResult | null>(null)
const activeTab = ref('overview')
const selectedEpisodeIndex = ref(0)
const selectedCharacterId = ref('')
const isSaving = ref(false)
const isGeneratingEps = ref(false)
const episodeGenStatus = ref('')

// AI 生成逐集集纲（后台任务 + 轮询进度），与工作台同一引擎：短大纲也能扩成 30-60 集
async function generateEpisodesViaJob() {
  if (!rawOutline.value.trim()) { toast.error('请先输入或粘贴大纲'); return }
  if (isGeneratingEps.value) return
  isGeneratingEps.value = true
  episodeGenStatus.value = '正在排队生成逐集集纲（后台任务，请稍候）...'
  try {
    const ar = analysisResult.value
    const seed = ar ? {
      sellingPoints: ar.sellingPoints,
      characters: (ar.characters || []).map(c => ({
        name: c.name,
        role: c.role,
        info: [c.motivation, c.arc, ...(c.traits || [])].filter(Boolean).join('，'),
        motivation: c.motivation,
        arc: c.arc,
        traits: c.traits,
        voiceprint: c.voiceprint,
        inner_need: c.inner_need,
        resource: c.resource,
        first_appearance_function: c.first_appearance_function,
        relationship_tension: c.relationship_tension,
        secret: c.secret,
      })),
    } : undefined
    const target = Math.max(30, ar?.episodes?.length || 0)
    const { data: startData } = await projectsV2Api.startEpisodeOutlinesJob({
      outline: rawOutline.value,
      target_episodes: target,
      temperature: 0.3,
      seed_analysis: seed,
    })
    const jobId = (startData as any)?.job_id
    if (!jobId) throw new Error('任务启动失败，请重试')
    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
    let final: any = null
    let pollErrors = 0
    for (let i = 0; i < 480; i++) {
      await sleep(2500)
      let st: any
      try {
        const { data } = await projectsV2Api.getEpisodeOutlinesJobStatus(jobId)
        st = data
      } catch (pollErr: any) {
        pollErrors += 1
        if (pollErrors > 5) throw pollErr
        continue
      }
      const done = st?.progress?.done ?? 0
      const total = st?.progress?.total ?? target
      if (st?.status === 'done') { final = st; break }
      if (st?.status === 'error') throw new Error(st?.error || '生成失败')
      episodeGenStatus.value = `逐集集纲生成中… ${done}/${total} 集（后台任务，可继续等待）`
    }
    if (!final) throw new Error('生成超时，请稍后重试')
    const eps = Array.isArray(final.episodes) ? final.episodes : []
    if (!eps.length) { toast.error('未返回集纲，请重试'); return }
    analysisResult.value = normalizeAnalysisResult({ ...(analysisResult.value || {}), episodes: eps })
    selectEpisode(0)
    episodeGenStatus.value = `已生成 ${analysisResult.value.episodes.length} 集集纲`
    toast.success(`已生成 ${analysisResult.value.episodes.length} 集集纲`)
  } catch (e: any) {
    toast.error(formatUserFacingErrorMessage(e, '生成失败'))
    episodeGenStatus.value = '生成集纲失败，请检查 AI 配置或稍后重试'
  } finally {
    isGeneratingEps.value = false
  }
}

// 当前选中的集
const currentEpisode = computed<EpisodeAnalysis | null>(() => {
  const episodes = analysisResult.value?.episodes
  if (!episodes?.length) return null
  return episodes[clampEpisodeIndex(selectedEpisodeIndex.value, episodes.length)] ?? null
})

const currentCharacter = computed(() =>
  analysisResult.value?.characters.find(c => c.id === selectedCharacterId.value)
)

function selectEpisode(index: number) {
  selectedEpisodeIndex.value = clampEpisodeIndex(index, analysisResult.value?.episodes.length ?? 0)
}

watch(
  [selectedEpisodeIndex, () => analysisResult.value?.episodes.length ?? 0],
  ([index, count]) => {
    const safeIndex = clampEpisodeIndex(index, count)
    if (safeIndex !== index) selectedEpisodeIndex.value = safeIndex
  },
  { immediate: true },
)

// 分析大纲（对接真实 AI 分析接口）
async function analyzeOutline() {
  if (!rawOutline.value.trim()) {
    toast.error('请输入大纲内容')
    return
  }

  isAnalyzing.value = true
  analysisProgress.value = 10

  // 进度动画（AI 调用是同步阻塞，用定时器给用户反馈）
  const progressSteps = [
    { label: '题材识别', value: 20, delay: 800 },
    { label: '卖点提炼', value: 40, delay: 1600 },
    { label: '人物分析', value: 60, delay: 2400 },
    { label: '结构拆解', value: 75, delay: 3200 },
    { label: '分集细化', value: 85, delay: 4000 },
  ]
  // 清掉上一次分析可能残留的定时器
  analysisTimers.forEach(t => clearTimeout(t))
  analysisTimers = []
  for (const step of progressSteps) {
    analysisTimers.push(setTimeout(() => { analysisProgress.value = step.value }, step.delay))
  }

  try {
    const { data } = await projectsV2Api.analyzeOutline(rawOutline.value)
    analysisTimers.forEach(t => clearTimeout(t))
    analysisTimers = []
    analysisProgress.value = 100
    analysisResult.value = normalizeAnalysisResult(data)
    selectEpisode(0)
    toast.success('大纲分析完成！')
    activeTab.value = 'overview'
  } catch (e: unknown) {
    analysisTimers.forEach(t => clearTimeout(t))
    analysisTimers = []
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    if (detail?.includes('未启用')) {
      toast.error('AI 服务未配置，请在设置中开启文本生成')
    } else {
      toast.error(formatUserFacingErrorMessage(e, '分析失败'))
    }
    console.error(e)
  } finally {
    isAnalyzing.value = false
  }
}

// AI细化建议
async function getAISuggestions(section: string, content: string) {
  toast.info(`正在生成${section}的改进建议...`)
  await new Promise(resolve => setTimeout(resolve, 1000))

  const suggestions: Record<string, string[]> = {
    '钩子': ['增加视觉冲击力', '让主角更早展现实力', '反派嘲讽要更毒'],
    '情节点': ['节奏可以再快', '增加反转', '情绪要有起伏'],
    '场景': ['时间地点要更具体', '增加细节描写', '人物动作要有特点'],
    '尾钩': ['悬念要更强', '增加倒计时', '让观众迫不及待']
  }

  return suggestions[section] || ['内容不错', '可以更丰富', '节奏需要调整']
}

// 保存大纲
async function saveOutline() {
  if (!analysisResult.value) return

  const normalizedResult = normalizeAnalysisResult(analysisResult.value)
  analysisResult.value = normalizedResult
  selectEpisode(selectedEpisodeIndex.value)
  isSaving.value = true
  try {
    let finalProjectName = projectName.value
    if (taskId.value && !finalProjectName) {
      try {
        const { data: taskData } = await taskApi.get(taskId.value)
        finalProjectName = taskData.name || `项目-${Date.now()}`
      } catch (e) {
        finalProjectName = `项目-${Date.now()}`
      }
    }

    if (!projectId.value) {
      const projectRes = await projectsV2Api.create({
        name: finalProjectName || `项目-${Date.now()}`,
        description: taskId.value ? `从任务#${taskId.value}导入的项目` : `从大纲导入的项目`,
        project_type: projectType.value || '真人短剧-男频',
      })
      projectId.value = projectRes.data.id
    }

    const writeFailures: string[] = []
    const { data: existingEpisodesRaw } = await projectsV2Api.listEpisodes(projectId.value)
    const existingEpisodeNumbers = new Set(
      (Array.isArray(existingEpisodesRaw) ? existingEpisodesRaw : [])
        .map((episode: any) => Number(episode?.episode_number))
        .filter(Number.isFinite),
    )

    for (const ep of normalizedResult.episodes) {
      try {
        const summary = ep.summary || `${ep.hook.content}\n\n${ep.plotPoints.map(p => p.content).join('\n')}\n\n${ep.cliffhanger.content}`
        if (!existingEpisodeNumbers.has(ep.episodeNumber)) {
          await projectsV2Api.createEpisode(projectId.value, {
            title: ep.title,
            summary,
            status: 'draft',
          }, ep.episodeNumber)
          existingEpisodeNumbers.add(ep.episodeNumber)
        }

        const { data: existingScenesRaw } = await projectsV2Api.listScenes(projectId.value, ep.episodeNumber)
        const existingScenes = Array.isArray(existingScenesRaw) ? existingScenesRaw : []
        const existingSceneNumbers = new Set(
          existingScenes.map((scene: any) => Number(scene?.scene_number)).filter(Number.isFinite),
        )

        for (let index = 0; index < ep.scenes.length; index += 1) {
          const scene = ep.scenes[index]
          if (!scene) continue
          const sceneNo = Number(scene.sceneNumber || scene.id || index + 1)
          if (existingSceneNumbers.has(sceneNo)) {
            await projectsV2Api.saveSceneContent(projectId.value, ep.episodeNumber, sceneNo, {
              content: scene.action || '',
              editor_type: 'human',
              change_note: '智能大纲分析器更新场景',
            })
          } else {
            await projectsV2Api.createScene(projectId.value, ep.episodeNumber, {
              time: scene.time,
              location_type: '内',
              location_name: scene.location,
              content: scene.action,
            })
            existingSceneNumbers.add(sceneNo)
          }
        }
      } catch (e) {
        console.error(`保存第${ep.episodeNumber}集失败:`, e)
        writeFailures.push(`第${ep.episodeNumber}集`)
      }
    }

    if (writeFailures.length > 0) {
      throw new Error(`${writeFailures.slice(0, 5).join('、')}没有保存成功，请重试`)
    }

    // 旧大纲分析器只导入候选草稿，不直接锁定新版主生成链路。
    // 用户必须回到新版工作台逐项确认后，才能进入角色设计和剧本生成。
    await projectsV2Api.saveWorkflowContext(projectId.value, {
      workflow_context: {
        outline_state: {
          outline_data: {
            logline: normalizedResult.sellingPoints?.logline || '',
            worldview: normalizedResult.sellingPoints?.worldview || '',
            goldenFinger: normalizedResult.sellingPoints?.uniqueness || '',
            conflict: normalizedResult.sellingPoints?.conflict || '',
            episodes: normalizedResult.episodes.map(ep => ({
              ep: ep.episodeNumber,
              title: ep.title,
              summary: ep.summary || [
                ep.hook?.content,
                ...(ep.plotPoints || []).map(p => p.content),
                ep.cliffhanger?.content,
              ].filter(Boolean).join('\n'),
              conflict: ep.conflict,
              turning: ep.turning,
              main_scene: ep.main_scene,
              relationship_change: ep.relationship_change,
              info_revealed: ep.info_revealed,
              satisfaction_type: ep.satisfaction_type,
              stage: ep.stage,
              hook: ep.cliffhanger?.content || '',
              callbacks: (ep as any).callbacks || [],
              seeds: (ep as any).seeds || [],
              subgoal_for_protagonist: (ep as any).subgoal_for_protagonist || '',
              subgoal_for_antagonist: (ep as any).subgoal_for_antagonist || '',
            })),
          },
          outline_characters: (normalizedResult.characters || []).map(c => ({
            name: c.name,
            role: c.role,
            info: [c.motivation, c.arc, ...(c.traits || [])].filter(Boolean).join('，'),
            motivation: c.motivation,
            arc: c.arc,
            traits: c.traits,
            voiceprint: c.voiceprint,
            inner_need: c.inner_need,
            resource: c.resource,
            first_appearance_function: c.first_appearance_function,
            relationship_tension: c.relationship_tension,
            secret: c.secret,
          })),
          candidate_source: 'legacy_import',
          needs_user_confirmation: true,
          main_chain_committed: false,
          main_chain_dirty: true,
          main_chain_committed_at: '',
          downstream_generation_allowed: false,
          updated_reason: 'legacy_outline_editor_imported',
        },
      },
      merge: true,
    })

    if (taskId.value) {
      try {
        await taskApi.update(taskId.value, {
          name: finalProjectName,
          description: `大纲已分析完成，项目ID: ${projectId.value}`,
        })
        toast.success('大纲保存成功！已关联到任务')
      } catch (e) {
        toast.warning('大纲已保存，但任务关联失败，请稍后重试')
      }
    } else {
      toast.success('大纲保存成功！')
    }

    router.push(`/outline-editor/${projectId.value}`)
  } catch (error) {
    toast.error('保存失败')
    console.error(error)
  } finally {
    isSaving.value = false
  }
}

// 返回
function goBack() {
  router.back()
}

// 加载已有项目数据
async function loadProjectData(id: string) {
  try {
    const { data: project } = await projectsV2Api.get(id)
    projectName.value = project.name
    projectType.value = project.project_type || '真人短剧-男频'

    // 加载集列表
    const { data: episodes } = await projectsV2Api.listEpisodes(id)
    const episodeList = Array.isArray(episodes) ? episodes : []

    if (episodeList.length > 0) {
      // 将项目数据重建为 analysisResult 格式
      analysisResult.value = normalizeAnalysisResult({
        genre: {
          category: project.genre_main || '',
          subCategory: project.genre_sub || '',
          target: project.audience_axis || '',
          confidence: 0
        },
        sellingPoints: {
          hook: '',
          conflict: '',
          uniqueness: '',
          marketFit: 0,
          suggestions: []
        },
        characters: [], // 从场景中提取角色需要更复杂的逻辑
        structure: {
          pacing: 'medium',
          rhythm: [],
          issues: [],
          suggestions: []
        },
        episodes: episodeList.map((ep: any, index: number) => ({
          id: ep.episode_number?.toString() || String(index + 1),
          episodeNumber: ep.episode_number || index + 1,
          title: ep.title || `第${index + 1}集`,
          hook: {
            content: ep.summary?.split('\n')[0] || '',
            type: 'standard',
            strength: 50,
            suggestions: []
          },
          plotPoints: ep.summary?.split('\n').slice(1, -1).map((content: string, i: number) => ({
            id: `pp-${index}-${i}`,
            type: 'rising' as const,
            content,
            purpose: '',
            emotion: '',
            suggestions: []
          })) || [],
          emotionArc: [],
          scenes: [], // 场景需要单独加载
          cliffhanger: {
            content: ep.summary?.split('\n').pop() || '',
            type: 'standard',
            strength: 50,
            suggestions: []
          },
          evaluation: {
            pacing: 50,
            tension: 50,
            completeness: 50,
            issues: [],
            suggestions: []
          }
        }))
      })
      selectEpisode(selectedEpisodeIndex.value)

      // 为每集加载场景
      for (let i = 0; i < episodeList.length; i++) {
        const episode = episodeList[i]
        if (!episode) continue
        try {
          const { data: scenes } = await projectsV2Api.listScenes(id, episode.episode_number)
          const sceneList = Array.isArray(scenes) ? scenes : []
          const targetEpisode = analysisResult.value?.episodes[i]
          if (targetEpisode) {
            targetEpisode.scenes = sceneList.map((scene: any, si: number) => ({
              id: scene.scene_number?.toString() || String(si + 1),
              sceneNumber: scene.scene_number || si + 1,
              time: scene.time || '日',
              location: scene.location_name || '',
              characters: [],
              action: scene.content || '',
              emotion: '',
              purpose: '',
              duration: 30,
              suggestions: []
            }))
          }
        } catch (e) {
          console.error(`加载第${episode.episode_number}集场景失败`, e)
        }
      }

      toast.success('已加载项目大纲')
    }
  } catch (e) {
    console.error('加载项目数据失败', e)
    toast.error('加载项目数据失败')
  }
}

// 添加情节点
function addPlotPoint(episodeIndex: number) {
  const ep = analysisResult.value?.episodes[episodeIndex]
  if (!ep) return
  ep.plotPoints.push({
    id: `pp-${episodeIndex}-${ep.plotPoints.length + 1}`,
    type: 'rising',
    content: '',
    purpose: '',
    emotion: '',
    suggestions: []
  })
}

// 删除情节点
function removePlotPoint(episodeIndex: number, pointIndex: number) {
  const ep = analysisResult.value?.episodes[episodeIndex]
  if (!ep) return
  ep.plotPoints.splice(pointIndex, 1)
}

// 添加场景
function addScene(episodeIndex: number) {
  const ep = analysisResult.value?.episodes[episodeIndex]
  if (!ep) return
  const newSceneNum = ep.scenes.length + 1
  ep.scenes.push({
    id: `scene-${episodeIndex + 1}-${newSceneNum}`,
    sceneNumber: newSceneNum,
    time: '日',
    location: '',
    characters: [],
    action: '',
    emotion: '',
    purpose: '',
    duration: 30,
    suggestions: []
  })
}

// 删除场景
function removeScene(episodeIndex: number, sceneIndex: number) {
  const ep = analysisResult.value?.episodes[episodeIndex]
  if (!ep) return
  ep.scenes.splice(sceneIndex, 1)
  ep.scenes.forEach((s, i) => {
    s.sceneNumber = i + 1
  })
}

// 添加人物
function addCharacter() {
  if (!analysisResult.value) return
  const newChar: CharacterProfile = {
    id: `char-${analysisResult.value.characters.length + 1}`,
    name: '',
    role: 'supporting',
    traits: [],
    motivation: '',
    arc: '',
    voiceprint: '',
    inner_need: '',
    resource: '',
    first_appearance_function: '',
    relationship_tension: '',
    secret: '',
    conflicts: [],
    suggestions: []
  }
  analysisResult.value.characters.push(newChar)
  selectedCharacterId.value = newChar.id
}

// 删除人物
function removeCharacter(charId: string) {
  if (!analysisResult.value) return
  const index = analysisResult.value.characters.findIndex(c => c.id === charId)
  if (index > -1) {
    analysisResult.value.characters.splice(index, 1)
    if (selectedCharacterId.value === charId) {
      selectedCharacterId.value = analysisResult.value.characters[0]?.id || ''
    }
  }
}

onMounted(async () => {
  if (route.query.outline) {
    rawOutline.value = decodeURIComponent(route.query.outline as string)
  } else {
    const prefillParts = [
      route.query.logline ? `一句话梗概：${String(route.query.logline)}` : '',
      route.query.type ? `题材类型：${String(route.query.type)}` : '',
      route.query.template ? `参考结构：${String(route.query.template)}` : '',
    ].filter(Boolean)
    if (prefillParts.length > 0) {
      rawOutline.value = prefillParts.join('\n\n')
    }
  }

  if (taskId.value && !projectId.value) {
    try {
      const { data: taskData } = await taskApi.get(taskId.value)
      projectName.value = taskData.name || ''
      projectType.value = taskData.type || '真人短剧-男频'
    } catch (e) {
      console.error('加载任务信息失败', e)
    }
  }

  // 如果存在 projectId，加载已有项目数据
  if (projectId.value) {
    await loadProjectData(projectId.value)
  }
})
</script>

<template>
  <div class="h-[calc(100vh-3.5rem)] flex flex-col">
    <!-- 顶部工具栏 -->
    <header class="h-14 border-b bg-card px-4 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-3">
        <Button variant="ghost" size="icon" @click="goBack">
          <ArrowLeft class="h-4 w-4" />
        </Button>
        <h1 class="font-semibold">智能大纲分析器</h1>
        <Badge v-if="analysisResult" variant="secondary">
          {{ analysisResult.episodes.length }} 集
        </Badge>
        <Badge v-if="taskId" variant="outline" class="text-primary border-primary">关联任务</Badge>
      </div>
      <div class="flex items-center gap-2">
        <Button
          v-if="analysisResult"
          variant="outline"
          size="sm"
          @click="analysisResult = null"
        >
          <RefreshCw class="mr-1 h-4 w-4" />
          重新分析
        </Button>
        <Button
          v-if="analysisResult"
          size="sm"
          @click="saveOutline"
          :disabled="isSaving"
        >
          <Save class="mr-1 h-4 w-4" />
          {{ isSaving ? '保存中...' : '保存大纲' }}
        </Button>
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden">
      <!-- 左侧：输入区（未分析时显示） -->
      <div v-if="!analysisResult" class="flex-1 p-6 overflow-auto">
        <div class="max-w-3xl mx-auto">
          <Card>
            <CardHeader>
              <CardTitle class="flex items-center gap-2">
                <Sparkles class="h-5 w-5 text-primary" />
                {{ mode === 'import' ? '智能分析大纲' : 'AI生成大纲' }}
              </CardTitle>
              <CardDescription>
                {{ mode === 'import'
                  ? '粘贴你的剧本大纲，AI将结合短剧创作规则进行深度分析和结构化拆解'
                  : '描述你的创作需求，AI将结合市场热点生成完整的剧本大纲'
                }}
              </CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
              <div class="space-y-2">
                <Label>项目名称</Label>
                <Input v-model="projectName" placeholder="输入项目名称..." />
              </div>

              <div class="space-y-2">
                <Label>{{ mode === 'import' ? '原始大纲' : '创作需求' }}</Label>
                <Textarea
                  v-model="rawOutline"
                  :placeholder="mode === 'import'
                    ? '粘贴大纲内容...\n\nAI将分析：\n• 题材定位与市场匹配度\n• 核心卖点与差异化\n• 人物设定与成长弧线\n• 剧情结构与节奏把控\n• 每集的钩子、情节点、尾钩\n• 场景细分与情绪曲线\n• 给出详细的修改建议'
                    : '描述你想创作的剧本，例如：\n\n我想写一个男频逆袭爽剧，主角是个被退婚的废物女婿，突然获得上古传承，开始打脸各方势力...'"
                  class="min-h-[400px] font-mono text-sm"
                />
              </div>

              <!-- 分析进度 -->
              <div v-if="isAnalyzing" class="space-y-2">
                <div class="flex justify-between text-sm">
                  <span class="text-muted-foreground">AI分析中...</span>
                  <span class="text-primary font-medium">{{ analysisProgress }}%</span>
                </div>
                <div class="h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    class="h-full bg-primary rounded-full transition-all duration-300"
                    :style="{ width: `${analysisProgress}%` }"
                  />
                </div>
              </div>

              <Button
                class="w-full"
                @click="analyzeOutline"
                :disabled="isAnalyzing || !rawOutline.trim()"
              >
                <Wand2 class="mr-2 h-4 w-4" />
                {{ isAnalyzing ? '分析中...' : (mode === 'import' ? '开始智能分析' : '生成大纲') }}
              </Button>

              <!-- AI 生成逐集集纲（后台任务，可把短大纲扩成 30-60 集；与工作台同一引擎） -->
              <Button
                variant="outline"
                class="w-full"
                @click="generateEpisodesViaJob"
                :disabled="isGeneratingEps || !rawOutline.trim()"
              >
                <Wand2 class="mr-2 h-4 w-4" />
                {{ isGeneratingEps ? '生成集纲中...' : 'AI生成逐集集纲（后台任务，可扩成30-60集）' }}
              </Button>
              <p v-if="episodeGenStatus" class="text-xs text-muted-foreground text-center">{{ episodeGenStatus }}</p>

              <!-- 功能说明 -->
              <div class="bg-muted/50 rounded-lg p-4 space-y-2">
                <h4 class="text-sm font-medium flex items-center gap-2">
                  <Lightbulb class="h-4 w-4 text-amber-500" />
                  AI分析能力
                </h4>
                <div class="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <div class="flex items-center gap-1">
                    <CheckCircle2 class="h-3 w-3 text-emerald-500" />
                    题材识别与定位
                  </div>
                  <div class="flex items-center gap-1">
                    <CheckCircle2 class="h-3 w-3 text-emerald-500" />
                    核心卖点提炼
                  </div>
                  <div class="flex items-center gap-1">
                    <CheckCircle2 class="h-3 w-3 text-emerald-500" />
                    人物弧光分析
                  </div>
                  <div class="flex items-center gap-1">
                    <CheckCircle2 class="h-3 w-3 text-emerald-500" />
                    节奏结构拆解
                  </div>
                  <div class="flex items-center gap-1">
                    <CheckCircle2 class="h-3 w-3 text-emerald-500" />
                    情绪曲线优化
                  </div>
                  <div class="flex items-center gap-1">
                    <CheckCircle2 class="h-3 w-3 text-emerald-500" />
                    智能修改建议
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <!-- 分析结果展示 -->
      <template v-else>
        <!-- 左侧导航 -->
        <div class="w-64 border-r bg-muted/30 flex flex-col shrink-0">
          <Tabs v-model="activeTab" class="w-full" orientation="vertical">
            <TabsList class="flex-col w-full h-auto bg-transparent gap-1 p-2">
              <TabsTrigger value="overview" class="w-full justify-start gap-2">
                <Target class="h-4 w-4" />
                整体分析
              </TabsTrigger>
              <TabsTrigger value="genre" class="w-full justify-start gap-2">
                <BookOpen class="h-4 w-4" />
                题材定位
              </TabsTrigger>
              <TabsTrigger value="characters" class="w-full justify-start gap-2">
                <Users class="h-4 w-4" />
                人物设定
              </TabsTrigger>
              <TabsTrigger value="structure" class="w-full justify-start gap-2">
                <Zap class="h-4 w-4" />
                结构分析
              </TabsTrigger>
              <TabsTrigger value="episodes" class="w-full justify-start gap-2">
                <FileText class="h-4 w-4" />
                分集详情
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <!-- 分集快速导航 -->
          <div class="flex-1 border-t p-2 overflow-auto">
            <h3 class="text-xs font-medium text-muted-foreground mb-2 px-2">分集导航</h3>
            <div class="space-y-1">
              <button
                v-for="(ep, index) in analysisResult.episodes"
                :key="ep.id"
                class="w-full text-left p-2 rounded-lg transition-colors text-sm"
                :class="selectedEpisodeIndex === index
                  ? 'bg-primary text-primary-foreground'
                  : 'hover:bg-muted'"
                @click="activeTab = 'episodes'; selectEpisode(index)"
              >
                <div class="font-medium">第 {{ ep.episodeNumber }} 集</div>
                <div class="text-xs truncate opacity-80">{{ ep.title }}</div>
                <div class="flex items-center gap-2 mt-1 text-xs opacity-60">
                  <span>钩{{ ep.hook?.strength ?? 0 }}</span>
                  <span>尾{{ ep.cliffhanger?.strength ?? 0 }}</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        <!-- 右侧内容区 -->
        <div class="flex-1 overflow-auto p-6">
          <!-- 整体分析 -->
          <TabsContent value="overview" class="mt-0 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle class="flex items-center gap-2">
                  <Target class="h-5 w-5 text-primary" />
                  项目概览
                </CardTitle>
              </CardHeader>
              <CardContent class="space-y-6">
                <!-- 题材定位 -->
                <div class="grid grid-cols-3 gap-4">
                  <div class="bg-muted/50 rounded-lg p-4">
                    <div class="text-sm text-muted-foreground mb-1">题材分类</div>
                    <div class="text-lg font-semibold">{{ analysisResult.genre.category }}</div>
                    <div class="text-xs text-muted-foreground">{{ analysisResult.genre.subCategory }}</div>
                  </div>
                  <div class="bg-muted/50 rounded-lg p-4">
                    <div class="text-sm text-muted-foreground mb-1">目标受众</div>
                    <div class="text-lg font-semibold">{{ analysisResult.genre.target }}</div>
                    <div class="text-xs text-muted-foreground">匹配度 {{ (analysisResult.genre.confidence * 100).toFixed(0) }}%</div>
                  </div>
                  <div class="bg-muted/50 rounded-lg p-4">
                    <div class="text-sm text-muted-foreground mb-1">市场契合度</div>
                    <div class="text-lg font-semibold">{{ analysisResult.sellingPoints.marketFit }}/10</div>
                    <div class="text-xs text-muted-foreground">基于当前热榜</div>
                  </div>
                </div>

                <!-- 核心卖点 -->
                <div class="space-y-3">
                  <h3 class="font-medium flex items-center gap-2">
                    <Sparkles class="h-4 w-4 text-amber-500" />
                    核心卖点
                  </h3>
                  <div class="grid grid-cols-3 gap-4">
                    <div class="border rounded-lg p-3">
                      <div class="text-xs text-muted-foreground mb-1">钩子设定</div>
                      <div class="text-sm">{{ analysisResult.sellingPoints.hook }}</div>
                    </div>
                    <div class="border rounded-lg p-3">
                      <div class="text-xs text-muted-foreground mb-1">核心冲突</div>
                      <div class="text-sm">{{ analysisResult.sellingPoints.conflict }}</div>
                    </div>
                    <div class="border rounded-lg p-3">
                      <div class="text-xs text-muted-foreground mb-1">差异化亮点</div>
                      <div class="text-sm">{{ analysisResult.sellingPoints.uniqueness }}</div>
                    </div>
                  </div>
                </div>

                <!-- 改进建议 -->
                <div class="bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
                  <h3 class="font-medium flex items-center gap-2 text-amber-800 dark:text-amber-200 mb-2">
                    <Lightbulb class="h-4 w-4" />
                    优化建议
                  </h3>
                  <ul class="space-y-1">
                    <li
                      v-for="(suggestion, idx) in analysisResult.sellingPoints.suggestions"
                      :key="idx"
                      class="text-sm text-amber-700 dark:text-amber-300 flex items-start gap-2"
                    >
                      <ChevronRight class="h-4 w-4 shrink-0 mt-0.5" />
                      {{ suggestion }}
                    </li>
                  </ul>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <!-- 题材定位 -->
          <TabsContent value="genre" class="mt-0">
            <Card>
              <CardHeader>
                <CardTitle>题材定位分析</CardTitle>
                <CardDescription>基于内容特征的题材识别与市场匹配</CardDescription>
              </CardHeader>
              <CardContent>
                <!-- 可编辑的题材信息 -->
                <div class="space-y-4">
                  <div class="grid grid-cols-2 gap-4">
                    <div class="space-y-2">
                      <Label>题材分类</Label>
                      <Input v-model="analysisResult.genre.category" />
                    </div>
                    <div class="space-y-2">
                      <Label>细分类型</Label>
                      <Input v-model="analysisResult.genre.subCategory" />
                    </div>
                  </div>
                  <div class="space-y-2">
                    <Label>目标受众</Label>
                    <Input v-model="analysisResult.genre.target" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <!-- 人物设定 -->
          <TabsContent value="characters" class="mt-0 space-y-4">
            <div class="flex items-center justify-between">
              <h2 class="text-lg font-semibold">人物设定</h2>
              <Button size="sm" variant="outline" @click="addCharacter">
                <Plus class="h-4 w-4 mr-1" />
                添加人物
              </Button>
            </div>

            <div class="grid grid-cols-[240px,1fr] gap-4">
              <!-- 人物列表 -->
              <div class="space-y-2">
                <button
                  v-for="char in analysisResult.characters"
                  :key="char.id"
                  class="w-full text-left p-3 rounded-lg border transition-colors"
                  :class="selectedCharacterId === char.id
                    ? 'border-primary bg-primary/5'
                    : 'hover:bg-muted'"
                  @click="selectedCharacterId = char.id"
                >
                  <div class="font-medium">{{ char.name }}</div>
                  <div class="text-xs text-muted-foreground">
                    {{ char.role === 'protagonist' ? '主角' :
                       char.role === 'antagonist' ? '反派' :
                       char.role === 'supporting' ? '配角' : '客串' }}
                  </div>
                </button>
              </div>

              <!-- 人物详情编辑 -->
              <Card v-if="currentCharacter">
                <CardHeader class="flex flex-row items-center justify-between">
                  <div>
                    <CardTitle class="text-base">人物详情</CardTitle>
                    <CardDescription>编辑人物设定与优化建议</CardDescription>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-destructive"
                    @click="removeCharacter(currentCharacter.id)"
                  >
                    <Trash2 class="h-4 w-4" />
                  </Button>
                </CardHeader>
                <CardContent class="space-y-4">
                  <div class="grid grid-cols-2 gap-4">
                    <div class="space-y-2">
                      <Label>人物名称</Label>
                      <Input v-model="currentCharacter.name" />
                    </div>
                    <div class="space-y-2">
                      <Label>角色定位</Label>
                      <select
                        v-model="currentCharacter.role"
                        class="w-full h-10 rounded-md border border-input bg-background px-3"
                      >
                        <option value="protagonist">主角</option>
                        <option value="antagonist">反派</option>
                        <option value="supporting">配角</option>
                        <option value="cameo">客串</option>
                      </select>
                    </div>
                  </div>

                  <div class="space-y-2">
                    <Label>性格特征（逗号分隔）</Label>
                    <Input
                      :value="currentCharacter.traits.join('，')"
                      @input="currentCharacter.traits = ($event.target as HTMLInputElement).value.split(/[,，]/).map(s => s.trim())"
                      placeholder="隐忍，霸气，护短..."
                    />
                  </div>

                  <div class="space-y-2">
                    <Label>人物动机</Label>
                    <Textarea v-model="currentCharacter.motivation" :rows="2" />
                  </div>

                  <div class="space-y-2">
                    <Label>人物弧线</Label>
                    <Textarea v-model="currentCharacter.arc" :rows="2" />
                  </div>

                  <div class="grid grid-cols-2 gap-4">
                    <div class="space-y-2">
                      <Label>声纹</Label>
                      <Textarea v-model="currentCharacter.voiceprint" :rows="2" />
                    </div>
                    <div class="space-y-2">
                      <Label>内在需求</Label>
                      <Textarea v-model="currentCharacter.inner_need" :rows="2" />
                    </div>
                    <div class="space-y-2">
                      <Label>资源/筹码</Label>
                      <Textarea v-model="currentCharacter.resource" :rows="2" />
                    </div>
                    <div class="space-y-2">
                      <Label>首次出场功能</Label>
                      <Textarea v-model="currentCharacter.first_appearance_function" :rows="2" />
                    </div>
                    <div class="space-y-2">
                      <Label>关系张力</Label>
                      <Textarea v-model="currentCharacter.relationship_tension" :rows="2" />
                    </div>
                    <div class="space-y-2">
                      <Label>底牌/秘密</Label>
                      <Textarea v-model="currentCharacter.secret" :rows="2" />
                    </div>
                  </div>

                  <!-- AI建议 -->
                  <div class="bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 rounded-lg p-3">
                    <div class="text-sm font-medium text-blue-800 dark:text-blue-200 mb-2 flex items-center gap-2">
                      <Sparkles class="h-4 w-4" />
                      AI优化建议
                    </div>
                    <ul class="space-y-1">
                      <li
                        v-for="(suggestion, idx) in currentCharacter.suggestions"
                        :key="idx"
                        class="text-sm text-blue-700 dark:text-blue-300 flex items-start gap-2"
                      >
                        <Edit3 class="h-3 w-3 shrink-0 mt-1" />
                        {{ suggestion }}
                      </li>
                    </ul>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <!-- 结构分析 -->
          <TabsContent value="structure" class="mt-0 space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>剧本结构分析</CardTitle>
              </CardHeader>
              <CardContent class="space-y-6">
                <!-- 节奏分析 -->
                <div class="space-y-3">
                  <h3 class="font-medium">整体节奏</h3>
                  <div class="flex items-center gap-4">
                    <Badge
                      :variant="analysisResult.structure.pacing === 'fast' ? 'default' : 'secondary'"
                      class="text-base px-4 py-2"
                    >
                      {{ analysisResult.structure.pacing === 'fast' ? '快' :
                         analysisResult.structure.pacing === 'medium' ? '中' : '慢' }}节奏
                    </Badge>
                    <div class="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        class="h-full bg-primary rounded-full"
                        :style="{
                          width: analysisResult.structure.pacing === 'fast' ? '90%' :
                                 analysisResult.structure.pacing === 'medium' ? '60%' : '30%'
                        }"
                      />
                    </div>
                  </div>
                </div>

                <!-- 情绪曲线 -->
                <div class="space-y-3">
                  <h3 class="font-medium">情绪节奏</h3>
                  <div class="flex items-end gap-2 h-24">
                    <div
                      v-for="(rhythm, idx) in analysisResult.structure.rhythm"
                      :key="idx"
                      class="flex-1 bg-primary/20 rounded-t-lg relative group cursor-pointer hover:bg-primary/30 transition-colors"
                      :style="{ height: `${(idx % 2 === 0 ? 30 : 80) + Math.random() * 20}%` }"
                    >
                      <div class="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 text-xs text-muted-foreground whitespace-nowrap">
                        {{ rhythm }}
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 问题与建议 -->
                <div class="grid grid-cols-2 gap-4">
                  <div class="bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
                    <h4 class="font-medium text-red-800 dark:text-red-200 mb-2 flex items-center gap-2">
                      <AlertCircle class="h-4 w-4" />
                      结构问题
                    </h4>
                    <ul class="space-y-1">
                      <li
                        v-for="(issue, idx) in analysisResult.structure.issues"
                        :key="idx"
                        class="text-sm text-red-700 dark:text-red-300"
                      >
                        {{ idx + 1 }}. {{ issue }}
                      </li>
                    </ul>
                  </div>
                  <div class="bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-4">
                    <h4 class="font-medium text-emerald-800 dark:text-emerald-200 mb-2 flex items-center gap-2">
                      <CheckCircle2 class="h-4 w-4" />
                      优化建议
                    </h4>
                    <ul class="space-y-1">
                      <li
                        v-for="(suggestion, idx) in analysisResult.structure.suggestions"
                        :key="idx"
                        class="text-sm text-emerald-700 dark:text-emerald-300"
                      >
                        {{ idx + 1 }}. {{ suggestion }}
                      </li>
                    </ul>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <!-- 分集详情 -->
          <TabsContent value="episodes" class="mt-0">
            <div v-if="currentEpisode" class="space-y-6">
              <!-- 集标题 -->
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-4">
                  <h2 class="text-xl font-bold">
                    第 {{ currentEpisode.episodeNumber }} 集：{{ currentEpisode.title }}
                  </h2>
                  <div class="flex gap-2">
                    <Badge variant="outline">节奏 {{ currentEpisode.evaluation.pacing }}</Badge>
                    <Badge variant="outline">张力 {{ currentEpisode.evaluation.tension }}</Badge>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    :disabled="selectedEpisodeIndex === 0"
                    @click="selectEpisode(selectedEpisodeIndex - 1)"
                  >
                    上一集
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    :disabled="selectedEpisodeIndex >= analysisResult.episodes.length - 1"
                    @click="selectEpisode(selectedEpisodeIndex + 1)"
                  >
                    下一集
                  </Button>
                </div>
              </div>

              <!-- 开场钩子 -->
              <Card>
                <CardHeader>
                  <CardTitle class="text-base flex items-center gap-2">
                    <Zap class="h-4 w-4 text-amber-500" />
                    开场钩子
                    <Badge variant="secondary">强度 {{ currentEpisode.hook.strength }}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent class="space-y-4">
                  <div class="space-y-2">
                    <Label>钩子内容</Label>
                    <Textarea v-model="currentEpisode.hook.content" :rows="3" />
                  </div>
                  <div class="grid grid-cols-2 gap-4">
                    <div class="space-y-2">
                      <Label>钩子类型</Label>
                      <Input v-model="currentEpisode.hook.type" />
                    </div>
                    <div class="space-y-2">
                      <Label>强度评分</Label>
                      <Input v-model.number="currentEpisode.hook.strength" type="number" min="0" max="10" />
                    </div>
                  </div>
                  <!-- AI建议 -->
                  <div class="bg-muted/50 rounded-lg p-3">
                    <div class="text-sm font-medium mb-2 flex items-center gap-2">
                      <Sparkles class="h-4 w-4 text-primary" />
                      优化建议
                    </div>
                    <ul class="space-y-1">
                      <li
                        v-for="(suggestion, idx) in currentEpisode.hook.suggestions"
                        :key="idx"
                        class="text-sm text-muted-foreground flex items-start gap-2"
                      >
                        <Edit3 class="h-3 w-3 shrink-0 mt-1" />
                        {{ suggestion }}
                      </li>
                    </ul>
                  </div>
                </CardContent>
              </Card>

              <!-- 情节点 -->
              <Card>
                <CardHeader class="flex flex-row items-center justify-between">
                  <CardTitle class="text-base flex items-center gap-2">
                    <Target class="h-4 w-4 text-blue-500" />
                    核心情节点
                  </CardTitle>
                  <Button size="sm" variant="ghost" @click="addPlotPoint(selectedEpisodeIndex)">
                    <Plus class="h-4 w-4 mr-1" />
                    添加
                  </Button>
                </CardHeader>
                <CardContent>
                  <Accordion type="multiple" class="w-full">
                    <AccordionItem
                      v-for="(point, idx) in currentEpisode.plotPoints"
                      :key="point.id"
                      :value="point.id"
                    >
                      <AccordionTrigger class="hover:no-underline">
                        <div class="flex items-center gap-3 text-left">
                          <Badge variant="outline">
                            {{ point.type === 'setup' ? '铺垫' :
                               point.type === 'inciting' ? '导火索' :
                               point.type === 'rising' ? '上升' :
                               point.type === 'climax' ? '高潮' :
                               point.type === 'falling' ? '下降' : '结局' }}
                          </Badge>
                          <span class="text-sm truncate max-w-md">{{ point.content || '未填写' }}</span>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div class="space-y-3 pt-2">
                          <div class="space-y-2">
                            <Label class="text-xs">内容</Label>
                            <Textarea v-model="point.content" :rows="2" />
                          </div>
                          <div class="grid grid-cols-2 gap-3">
                            <div class="space-y-2">
                              <Label class="text-xs">类型</Label>
                              <select
                                v-model="point.type"
                                class="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
                              >
                                <option value="setup">铺垫</option>
                                <option value="inciting">导火索</option>
                                <option value="rising">上升</option>
                                <option value="climax">高潮</option>
                                <option value="falling">下降</option>
                                <option value="resolution">结局</option>
                              </select>
                            </div>
                            <div class="space-y-2">
                              <Label class="text-xs">情绪</Label>
                              <Input v-model="point.emotion" placeholder="如：憋屈、爽、紧张" />
                            </div>
                          </div>
                          <div class="space-y-2">
                            <Label class="text-xs">作用</Label>
                            <Input v-model="point.purpose" placeholder="这个情节点的作用是什么？" />
                          </div>
                          <!-- AI建议 -->
                          <div v-if="point.suggestions.length" class="bg-blue-50 dark:bg-blue-950/20 rounded p-2">
                            <div class="text-xs text-blue-700 dark:text-blue-300 space-y-1">
                              <div v-for="(s, i) in point.suggestions" :key="i" class="flex items-start gap-1">
                                <Sparkles class="h-3 w-3 shrink-0 mt-0.5" />
                                {{ s }}
                              </div>
                            </div>
                          </div>
                          <div class="flex justify-end">
                            <Button
                              variant="ghost"
                              size="sm"
                              class="text-destructive"
                              @click="removePlotPoint(selectedEpisodeIndex, idx)"
                            >
                              <Trash2 class="h-3 w-3 mr-1" />
                              删除
                            </Button>
                          </div>
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  </Accordion>
                </CardContent>
              </Card>

              <!-- 情绪曲线 -->
              <Card>
                <CardHeader>
                  <CardTitle class="text-base">情绪曲线</CardTitle>
                </CardHeader>
                <CardContent>
                  <div class="flex items-end gap-2 h-32 pb-6">
                    <div
                      v-for="(emotion, idx) in currentEpisode.emotionArc"
                      :key="idx"
                      class="flex-1 bg-gradient-to-t from-primary/20 to-primary/60 rounded-t-lg relative group"
                      :style="{ height: `${emotion.level * 10}%` }"
                    >
                      <div class="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 text-xs text-muted-foreground whitespace-nowrap">
                        {{ emotion.stage }}
                      </div>
                      <div class="absolute top-2 left-1/2 -translate-x-1/2 text-xs text-white font-medium">
                        {{ emotion.level }}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <!-- 场景列表 -->
              <Card>
                <CardHeader class="flex flex-row items-center justify-between">
                  <CardTitle class="text-base flex items-center gap-2">
                    <FileText class="h-4 w-4 text-emerald-500" />
                    场景细分 ({{ currentEpisode.scenes.length }})
                  </CardTitle>
                  <Button size="sm" variant="ghost" @click="addScene(selectedEpisodeIndex)">
                    <Plus class="h-4 w-4 mr-1" />
                    添加场景
                  </Button>
                </CardHeader>
                <CardContent>
                  <Accordion type="multiple" class="w-full">
                    <AccordionItem
                      v-for="(scene, idx) in currentEpisode.scenes"
                      :key="scene.id"
                      :value="scene.id"
                    >
                      <AccordionTrigger class="hover:no-underline">
                        <div class="flex items-center gap-3 text-left">
                          <Badge variant="outline">场景 {{ scene.sceneNumber }}</Badge>
                          <span class="text-sm text-muted-foreground">{{ scene.time }} / {{ scene.location }}</span>
                          <span class="text-xs text-muted-foreground">{{ scene.duration }}秒</span>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div class="space-y-3 pt-2">
                          <div class="grid grid-cols-3 gap-3">
                            <div class="space-y-2">
                              <Label class="text-xs">时间</Label>
                              <select
                                v-model="scene.time"
                                class="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
                              >
                                <option value="日">日</option>
                                <option value="夜">夜</option>
                                <option value="晨">晨</option>
                                <option value="昏">昏</option>
                              </select>
                            </div>
                            <div class="space-y-2 col-span-2">
                              <Label class="text-xs">地点</Label>
                              <Input v-model="scene.location" placeholder="具体地点..." />
                            </div>
                          </div>
                          <div class="space-y-2">
                            <Label class="text-xs">动作/事件</Label>
                            <Textarea v-model="scene.action" :rows="2" />
                          </div>
                          <div class="grid grid-cols-2 gap-3">
                            <div class="space-y-2">
                              <Label class="text-xs">情绪</Label>
                              <Input v-model="scene.emotion" placeholder="如：紧张、喜悦" />
                            </div>
                            <div class="space-y-2">
                              <Label class="text-xs">作用</Label>
                              <Input v-model="scene.purpose" placeholder="推进剧情/塑造人物" />
                            </div>
                          </div>
                          <div class="space-y-2">
                            <Label class="text-xs">时长（秒）</Label>
                            <Input v-model.number="scene.duration" type="number" />
                          </div>
                          <div class="flex justify-between items-center">
                            <div v-if="scene.suggestions.length" class="text-xs text-muted-foreground">
                              💡 {{ scene.suggestions[0] }}
                            </div>
                            <Button
                              variant="ghost"
                              size="sm"
                              class="text-destructive ml-auto"
                              @click="removeScene(selectedEpisodeIndex, idx)"
                            >
                              <Trash2 class="h-3 w-3 mr-1" />
                              删除
                            </Button>
                          </div>
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  </Accordion>
                </CardContent>
              </Card>

              <!-- 尾钩 -->
              <Card>
                <CardHeader>
                  <CardTitle class="text-base flex items-center gap-2">
                    <Zap class="h-4 w-4 text-purple-500" />
                    尾钩 / 悬念
                    <Badge variant="secondary">强度 {{ currentEpisode.cliffhanger.strength }}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent class="space-y-4">
                  <div class="space-y-2">
                    <Label>尾钩内容</Label>
                    <Textarea v-model="currentEpisode.cliffhanger.content" :rows="3" />
                  </div>
                  <div class="grid grid-cols-2 gap-4">
                    <div class="space-y-2">
                      <Label>尾钩类型</Label>
                      <Input v-model="currentEpisode.cliffhanger.type" />
                    </div>
                    <div class="space-y-2">
                      <Label>强度评分</Label>
                      <Input v-model.number="currentEpisode.cliffhanger.strength" type="number" min="0" max="10" />
                    </div>
                  </div>
                  <!-- AI建议 -->
                  <div class="bg-purple-50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-800 rounded-lg p-3">
                    <div class="text-sm font-medium text-purple-800 dark:text-purple-200 mb-2 flex items-center gap-2">
                      <Sparkles class="h-4 w-4" />
                      尾钩优化建议
                    </div>
                    <ul class="space-y-1">
                      <li
                        v-for="(suggestion, idx) in currentEpisode.cliffhanger.suggestions"
                        :key="idx"
                        class="text-sm text-purple-700 dark:text-purple-300 flex items-start gap-2"
                      >
                        <Edit3 class="h-3 w-3 shrink-0 mt-1" />
                        {{ suggestion }}
                      </li>
                    </ul>
                  </div>
                </CardContent>
              </Card>

              <!-- 本集评估 -->
              <Card>
                <CardHeader>
                  <CardTitle class="text-base">本集评估</CardTitle>
                </CardHeader>
                <CardContent>
                  <div class="grid grid-cols-3 gap-4 mb-4">
                    <div class="text-center p-3 bg-muted/50 rounded-lg">
                      <div class="text-2xl font-bold">{{ currentEpisode.evaluation.pacing }}</div>
                      <div class="text-xs text-muted-foreground">节奏把控</div>
                    </div>
                    <div class="text-center p-3 bg-muted/50 rounded-lg">
                      <div class="text-2xl font-bold">{{ currentEpisode.evaluation.tension }}</div>
                      <div class="text-xs text-muted-foreground">张力指数</div>
                    </div>
                    <div class="text-center p-3 bg-muted/50 rounded-lg">
                      <div class="text-2xl font-bold">{{ currentEpisode.evaluation.completeness }}</div>
                      <div class="text-xs text-muted-foreground">完整度</div>
                    </div>
                  </div>
                  <div class="space-y-2">
                    <div v-if="currentEpisode.evaluation.issues.length" class="text-sm">
                      <span class="text-destructive font-medium">问题：</span>
                      {{ currentEpisode.evaluation.issues.join('；') }}
                    </div>
                    <div v-if="currentEpisode.evaluation.suggestions.length" class="text-sm">
                      <span class="text-primary font-medium">建议：</span>
                      {{ currentEpisode.evaluation.suggestions.join('；') }}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
            <div v-else class="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              暂无可编辑分集
            </div>
          </TabsContent>
        </div>
      </template>
    </div>
  </div>
</template>
