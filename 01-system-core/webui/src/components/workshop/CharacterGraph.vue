<script setup lang="ts">
// @ts-nocheck
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import * as d3 from 'd3'
import { ZoomIn, ZoomOut, Maximize, RotateCcw, Users, AlertCircle } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

interface Relationship {
  targetId: string
  targetName: string
  type: string
  strength: number
  description?: string
  episodes?: number[]
}

interface Character {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  relationships?: Relationship[]
  appearance?: string
  motivation?: string
}

const props = defineProps<{
  characters: Character[]
  roleColors: Record<string, string>
  mode?: 'static' | 'realtime'
  presentCharacterIds?: string[]   // 直接传入出场角色ID列表（用于剧本写作tab）
  activeRelationKeys?: string[]
  currentScene?: {
    episode: number
    scene: number
    content: string
    charactersPresent: string[]
  }
  scenes?: any[]
  scriptContent?: string  // 实时剧本内容，用于推断同场关系
}>()

const emit = defineEmits<{
  (e: 'select-character', id: string): void
}>()

const svgRef = ref<SVGSVGElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const selectedChar = ref<Character | null>(null)
const tooltipChar = ref<Character | null>(null)
const tooltipPos = ref({ x: 0, y: 0 })

let simulation: d3.Simulation<any, any> | null = null
let resizeObserver: ResizeObserver | null = null

// Role color palette (MiroFish inspired: bold, distinct colors per type)
const roleColorMap = computed(() => ({
  protagonist: props.roleColors?.protagonist || '#6366f1',   // indigo
  antagonist:  props.roleColors?.antagonist  || '#ef4444',   // red
  supporting:  props.roleColors?.supporting  || '#10b981',   // emerald
  minor:       props.roleColors?.minor       || '#94a3b8',   // slate
}))

const presentIds = computed(() => new Set(
  props.presentCharacterIds ?? props.currentScene?.charactersPresent ?? []
))
const activeRelationSet = computed(() => new Set(props.activeRelationKeys ?? []))

/**
 * 从剧本文本推断角色同场关系（共现关系）
 * 返回 { source, target, count, type: '同场' } 列表，已排除已有明确关系的对
 */
const inferredLinks = computed(() => {
  const script = props.scriptContent || ''
  if (!script.trim() || props.characters.length < 2) return []

  // 已有明确关系的对（双向）
  const definedPairs = new Set<string>()
  props.characters.forEach(src => {
    src.relationships?.forEach(rel => {
      definedPairs.add([src.id, rel.targetId].sort().join('__'))
    })
  })

  // 按场次分割（场景标题行：数字-数字 开头，或【场...】）
  const sceneBlocks = script.split(/\n(?=\d+-\d+|【场)/)

  // 每个角色名 → id
  const nameToId = new Map<string, string>()
  props.characters.forEach(c => { nameToId.set(c.name, c.id) })

  // 统计每对角色同场次数
  const coCount = new Map<string, number>()

  sceneBlocks.forEach(block => {
    const presentInScene = new Set<string>()
    block.split('\n').forEach(line => {
      // 对白行：角色名：台词  /  角色名OS：... /  角色名（情绪）OS：...
      const m = line.match(/^([^\s：:（(]{1,8})(?:（[^）]*）)?(?:OS)?[：:]/)
      if (m) {
        const name = m[1].trim()
        if (nameToId.has(name)) presentInScene.add(nameToId.get(name)!)
      }
    })
    // 对当前场次中所有角色对计数
    const arr = [...presentInScene]
    for (let i = 0; i < arr.length; i++) {
      for (let j = i + 1; j < arr.length; j++) {
        const key = [arr[i], arr[j]].sort().join('__')
        if (!definedPairs.has(key)) {
          coCount.set(key, (coCount.get(key) || 0) + 1)
        }
      }
    }
  })

  // 转成 links，只显示共现 ≥1 次的对
  const result: { source: string; target: string; count: number; type: string; inferred: true }[] = []
  coCount.forEach((count, key) => {
    const [a, b] = key.split('__')
    result.push({ source: a, target: b, count, type: '同场', inferred: true })
  })
  return result
})

function pairKey(a: string, b: string) {
  return [a, b].sort().join('__')
}

function linkKey(link: any) {
  const sourceId = typeof link?.source === 'object' ? String(link.source?.id || '') : String(link?.source || '')
  const targetId = typeof link?.target === 'object' ? String(link.target?.id || '') : String(link?.target || '')
  return pairKey(sourceId, targetId)
}

function getNodeColor(role: string) {
  return (roleColorMap.value as any)[role] || '#94a3b8'
}

function buildGraph() {
  if (!svgRef.value || !containerRef.value) return
  const container = containerRef.value
  const W = container.clientWidth  || 400
  const H = container.clientHeight || 400

  // ── Build nodes & links ──────────────────────────────────────────────────
  const nodes: any[] = props.characters.map(c => ({
    id: c.id,
    name: c.name,
    role: c.role,
    char: c,
    r: c.role === 'protagonist' ? 30 : c.role === 'antagonist' ? 26 : 20,
  }))

  const links: any[] = []
  props.characters.forEach(src => {
    src.relationships?.forEach(rel => {
      const tgt = props.characters.find(c => c.id === rel.targetId)
      if (tgt) {
        links.push({
          source: src.id,
          target: rel.targetId,
          type: rel.type,
          strength: rel.strength / 100,
          inferred: false,
        })
      }
    })
  })

  // 推断关系（同场共现）：作为辅助虚线边加入仿真，但分组绘制
  const inferredLinksCopy = inferredLinks.value
    .filter(il => nodes.find((n: any) => n.id === il.source) && nodes.find((n: any) => n.id === il.target))
    .map(il => ({ ...il, strength: Math.min(0.6, il.count * 0.15) }))

  // 所有 links（用于 forceLink，保证推断关系也参与力布局）
  const allLinks = [...links, ...inferredLinksCopy]

  // ── Clear SVG ────────────────────────────────────────────────────────────
  const svgEl = d3.select(svgRef.value)
  svgEl.selectAll('*').remove()
  svgEl.attr('width', W).attr('height', H)

  // ── Defs: arrow markers per role color + glow filter ────────────────────
  const defs = svgEl.append('defs')

  // Glow filter
  const filter = defs.append('filter').attr('id', 'glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%')
  filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur')
  const feMerge = filter.append('feMerge')
  feMerge.append('feMergeNode').attr('in', 'coloredBlur')
  feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

  // Arrow marker
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 28)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#94a3b8')
    .attr('opacity', 0.7)

  // ── Zoom & pan layer ─────────────────────────────────────────────────────
  const g = svgEl.append('g').attr('class', 'graph-root')

  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.3, 3])
    .on('zoom', (event) => g.attr('transform', event.transform))
  svgEl.call(zoom)

  // ── D3 force simulation (MiroFish style) ─────────────────────────────────
  if (simulation) simulation.stop()
  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(allLinks).id((d: any) => d.id).distance(120).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-350))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius((d: any) => d.r + 18))

  // ── Inferred edges (dashed, drawn BEHIND defined edges) ───────────────────
  const inferredGroup = g.append('g').attr('class', 'inferred-edges')
  const inferredPaths = inferredGroup.selectAll('.inferred-edge')
    .data(inferredLinksCopy)
    .enter()
    .append('path')
    .attr('class', 'inferred-edge')
    .attr('stroke', '#a5b4fc')          // indigo-300
    .attr('stroke-width', 1.5)
    .attr('stroke-dasharray', '5,4')
    .attr('fill', 'none')
    .attr('opacity', 0.6)

  // ── Defined Edges (curved paths like MiroFish) ─────────────────────────
  const edgeGroup = g.append('g').attr('class', 'edges')

  const edgePaths = edgeGroup.selectAll('.edge')
    .data(links)
    .enter()
    .append('g')
    .attr('class', 'edge')

  // Edge line
  const edgeLines = edgePaths.append('path')
    .attr('stroke', (d: any) => activeRelationSet.value.has(linkKey(d)) ? '#0f766e' : '#cbd5e1')
    .attr('stroke-width', (d: any) => activeRelationSet.value.has(linkKey(d)) ? Math.max(2.5, d.strength * 5) : Math.max(1.5, d.strength * 4))
    .attr('fill', 'none')
    .attr('opacity', (d: any) => activeRelationSet.value.has(linkKey(d)) ? 0.95 : 0.75)
    .attr('marker-end', 'url(#arrow)')
    .style('cursor', 'default')

  // Edge label background + text
  const edgeLabelGroup = edgePaths.append('g').attr('class', 'edge-label')

  edgeLabelGroup.append('rect')
    .attr('rx', 4)
    .attr('fill', 'white')
    .attr('opacity', 0.9)

  const edgeLabelText = edgeLabelGroup.append('text')
    .text((d: any) => d.type)
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .attr('font-size', 10)
    .attr('fill', (d: any) => activeRelationSet.value.has(linkKey(d)) ? '#0f766e' : '#475569')
    .attr('font-weight', '500')

  // Size the label rect ONCE after the browser has rendered the text.
  // requestAnimationFrame ensures the SVG is in the DOM before getBBox() is called.
  requestAnimationFrame(() => {
    edgeLabelGroup.each(function() {
      const grp = d3.select(this)
      const txt = grp.select('text')
      try {
        const bb = (txt.node() as SVGTextElement).getBBox()
        grp.select('rect')
          .attr('x', bb.x - 3).attr('y', bb.y - 2)
          .attr('width', bb.width + 6).attr('height', bb.height + 4)
      } catch {}
    })
  })

  // ── Node groups ──────────────────────────────────────────────────────────
  const nodeGroup = g.append('g').attr('class', 'nodes')

  const nodeGs = nodeGroup.selectAll('.node')
    .data(nodes)
    .enter()
    .append('g')
    .attr('class', 'node')
    .style('cursor', 'pointer')
    .call(
      d3.drag<any, any>()
        .on('start', (event, d) => {
          if (!event.active) simulation!.alphaTarget(0.3).restart()
          d.fx = d.x; d.fy = d.y
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
        .on('end', (event, d) => {
          if (!event.active) simulation!.alphaTarget(0)
          d.fx = null; d.fy = null
        })
    )
    .on('click', (_event, d: any) => {
      selectedChar.value = d.char
      emit('select-character', d.id)
    })
    .on('mouseenter', (event, d: any) => {
      tooltipChar.value = d.char
      const rect = containerRef.value!.getBoundingClientRect()
      tooltipPos.value = { x: event.clientX - rect.left + 12, y: event.clientY - rect.top - 8 }
      // highlight
      d3.select(event.currentTarget).select('.node-circle').attr('stroke-width', 4)
    })
    .on('mouseleave', (event) => {
      tooltipChar.value = null
      d3.select(event.currentTarget).select('.node-circle').attr('stroke-width', 2.5)
    })

  // Outer pulse ring for "present" characters
  nodeGs.append('circle')
    .attr('class', 'pulse-ring')
    .attr('r', (d: any) => d.r + 10)
    .attr('fill', 'none')
    .attr('stroke', (d: any) => presentIds.value.has(d.id) ? getNodeColor(d.role) : 'transparent')
    .attr('stroke-width', 2)
    .attr('opacity', 0.35)
    .attr('class', (d: any) => presentIds.value.has(d.id) ? 'pulse-ring animate-pulse' : 'pulse-ring')

  // Shadow circle (depth effect like MiroFish nodes)
  nodeGs.append('circle')
    .attr('class', 'node-shadow')
    .attr('r', (d: any) => d.r + 3)
    .attr('fill', (d: any) => getNodeColor(d.role))
    .attr('opacity', 0.2)

  // Main circle
  nodeGs.append('circle')
    .attr('class', 'node-circle')
    .attr('r', (d: any) => d.r)
    .attr('fill', (d: any) => getNodeColor(d.role))
    .attr('stroke', (d: any) => {
      if (d.id === selectedChar.value?.id) return '#f472b6'  // pink for selected
      if (presentIds.value.has(d.id)) return 'white'
      return 'white'
    })
    .attr('stroke-width', (d: any) => d.id === selectedChar.value?.id ? 4 : 2.5)

  // Name label inside circle
  nodeGs.append('text')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .attr('font-size', (d: any) => d.r > 25 ? 13 : 11)
    .attr('font-weight', '700')
    .attr('fill', 'white')
    .attr('pointer-events', 'none')
    .text((d: any) => d.name.slice(0, 3))

  // Role label below circle
  nodeGs.append('text')
    .attr('text-anchor', 'middle')
    .attr('y', (d: any) => d.r + 14)
    .attr('font-size', 9)
    .attr('fill', '#64748b')
    .attr('pointer-events', 'none')
    .text((d: any) => {
      const map: any = { protagonist: '主角', antagonist: '反派', supporting: '配角', minor: '龙套' }
      return map[d.role] || d.role
    })

  // ── Simulation tick ───────────────────────────────────────────────────────
  simulation.on('tick', () => {
    // Inferred dashed edges (straight lines, simpler)
    inferredPaths.attr('d', (d: any) => {
      if (!d.source || !d.target) return ''
      return `M${d.source.x},${d.source.y} L${d.target.x},${d.target.y}`
    })

    // Curved paths for defined edges
    edgeLines.attr('d', (d: any) => {
      const sx = d.source.x, sy = d.source.y
      const tx = d.target.x, ty = d.target.y
      const dx = tx - sx, dy = ty - sy
      const dr = Math.sqrt(dx * dx + dy * dy) * 1.2
      return `M${sx},${sy} A${dr},${dr} 0 0,1 ${tx},${ty}`
    })

    // Edge label positions at midpoint of arc
    edgeLabelGroup.attr('transform', (d: any) => {
      const mx = (d.source.x + d.target.x) / 2
      const my = (d.source.y + d.target.y) / 2 - 12
      return `translate(${mx},${my})`
    })

    // NOTE: label rect sizing is done once after graph build (see below).
    // Do NOT call getBBox() here — it forces a synchronous browser reflow on every tick (60fps).

    // Node positions
    nodeGs.attr('transform', (d: any) => `translate(${d.x},${d.y})`)

    // Re-color selected
    nodeGs.select('.node-circle')
      .attr('stroke', (d: any) => d.id === selectedChar.value?.id ? '#f472b6' : 'white')
      .attr('stroke-width', (d: any) => d.id === selectedChar.value?.id ? 4 : 2.5)
  })
}

// ── Resize observer ────────────────────────────────────────────────────────
let _resizeTimer: ReturnType<typeof setTimeout> | null = null
function setupResize() {
  if (!containerRef.value) return
  resizeObserver = new ResizeObserver(() => {
    // Debounce: skip rapid resize events while the user is dragging a panel splitter
    if (_resizeTimer) clearTimeout(_resizeTimer)
    _resizeTimer = setTimeout(() => { nextTick(buildGraph) }, 200)
  })
  resizeObserver.observe(containerRef.value)
}

onMounted(() => {
  nextTick(() => {
    buildGraph()
    setupResize()
  })
})

onUnmounted(() => {
  simulation?.stop()
  resizeObserver?.disconnect()
  if (_resizeTimer) clearTimeout(_resizeTimer)
  if (_fingerprintTimer) clearTimeout(_fingerprintTimer)
  if (_scriptWatchTimer) clearTimeout(_scriptWatchTimer)
})

let _fingerprintTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => [
    // Lightweight fingerprint — only rebuild when structurally meaningful data changes.
    // Avoids serialising full character objects on every keystroke.
    props.characters.map(c => `${c.id}:${c.name}:${c.role}:${(c.relationships ?? []).map(rel => `${rel.targetId}:${rel.type}:${rel.strength}:${rel.description || ''}`).join(',')}`).join('|'),
    (props.presentCharacterIds ?? []).join(','),
    (props.activeRelationKeys ?? []).join(','),
    props.currentScene,
  ],
  () => {
    if (_fingerprintTimer) clearTimeout(_fingerprintTimer)
    _fingerprintTimer = setTimeout(() => nextTick(buildGraph), 300)
  },
)

// Script content triggers graph rebuild — 1500ms debounce + 去重，防止每次按键都重建 D3
let _scriptWatchTimer: ReturnType<typeof setTimeout> | null = null
let _lastScriptSnapshot = ''
watch(
  () => props.scriptContent,
  (content) => {
    if (_scriptWatchTimer) clearTimeout(_scriptWatchTimer)
    _scriptWatchTimer = setTimeout(() => {
      const snap = content || ''
      if (snap === _lastScriptSnapshot) return
      _lastScriptSnapshot = snap
      nextTick(buildGraph)
    }, 1500)
  },
)

// ── Zoom controls ─────────────────────────────────────────────────────────
function zoomAction(scale: number) {
  if (!svgRef.value) return
  const svgEl = d3.select(svgRef.value)
  const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 3])
  if (scale === 0) {
    svgEl.transition().duration(400).call(zoom.transform, d3.zoomIdentity.translate(
      (containerRef.value?.clientWidth || 400) / 2,
      (containerRef.value?.clientHeight || 400) / 2
    ).scale(1).translate(
      -(containerRef.value?.clientWidth || 400) / 2,
      -(containerRef.value?.clientHeight || 400) / 2
    ))
  } else {
    svgEl.transition().duration(300).call(
      zoom.scaleBy, scale
    )
  }
}
</script>

<template>
  <div ref="containerRef" class="character-graph relative w-full h-full overflow-hidden rounded-xl bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">

    <!-- SVG canvas -->
    <svg ref="svgRef" class="w-full h-full" style="display:block" />

    <!-- Tooltip -->
    <Transition name="tooltip-fade">
      <div
        v-if="tooltipChar"
        class="pointer-events-none absolute z-30 bg-white dark:bg-slate-800 border shadow-xl rounded-xl p-3 w-52"
        :style="{ left: tooltipPos.x + 'px', top: tooltipPos.y + 'px' }"
      >
        <div class="font-semibold text-sm mb-1 flex items-center gap-2">
          <span
            class="w-2.5 h-2.5 rounded-full inline-block shrink-0"
            :style="{ background: getNodeColor(tooltipChar.role) }"
          />
          {{ tooltipChar.name }}
          <span class="text-xs text-muted-foreground ml-auto font-normal">
            {{ { protagonist:'主角', antagonist:'反派', supporting:'配角', minor:'龙套' }[tooltipChar.role] }}
          </span>
        </div>
        <p v-if="tooltipChar.motivation" class="text-xs text-muted-foreground leading-relaxed">
          {{ tooltipChar.motivation.slice(0, 60) }}{{ tooltipChar.motivation.length > 60 ? '...' : '' }}
        </p>
        <div v-if="tooltipChar.relationships?.length" class="mt-2 border-t pt-2">
          <p class="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">关系</p>
          <div v-for="rel in tooltipChar.relationships?.slice(0, 3)" :key="rel.targetId" class="text-xs flex items-center gap-1.5 text-slate-600">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-300 shrink-0" />
            {{ rel.targetName }}
            <span class="text-slate-400 ml-auto">{{ rel.type }}</span>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Selected node panel -->
    <Transition name="panel-fade">
      <div
        v-if="selectedChar"
        class="absolute top-3 left-3 z-20 bg-white dark:bg-slate-800 border shadow-lg rounded-xl p-3 w-48"
      >
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full" :style="{ background: getNodeColor(selectedChar.role) }" />
            <span class="font-semibold text-sm">{{ selectedChar.name }}</span>
          </div>
          <button class="text-muted-foreground hover:text-foreground text-xs" @click="selectedChar = null">✕</button>
        </div>
        <p class="text-xs text-muted-foreground mb-2">
          {{ { protagonist:'主角', antagonist:'反派', supporting:'配角', minor:'龙套' }[selectedChar.role] }}
          <span v-if="presentIds.has(selectedChar.id)" class="ml-1.5 text-blue-500">● 出场中</span>
        </p>
        <div v-if="selectedChar.relationships?.length" class="space-y-1">
          <div v-for="rel in selectedChar.relationships" :key="rel.targetId" class="flex items-center justify-between text-xs text-muted-foreground">
            <span>→ {{ rel.targetName }}</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-muted">{{ rel.type }}</span>
          </div>
        </div>
        <button
          class="mt-2 w-full text-xs py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
          @click="$emit('select-character', selectedChar.id)"
        >
          编辑角色 →
        </button>
      </div>
    </Transition>

    <!-- Controls -->
    <div class="absolute bottom-3 right-3 z-20 flex gap-1.5">
      <button
        class="w-8 h-8 rounded-lg bg-white dark:bg-slate-700 border shadow flex items-center justify-center hover:bg-muted transition-colors"
        title="放大"
        @click="zoomAction(1.3)"
      >
        <ZoomIn class="h-3.5 w-3.5" />
      </button>
      <button
        class="w-8 h-8 rounded-lg bg-white dark:bg-slate-700 border shadow flex items-center justify-center hover:bg-muted transition-colors"
        title="缩小"
        @click="zoomAction(0.77)"
      >
        <ZoomOut class="h-3.5 w-3.5" />
      </button>
      <button
        class="w-8 h-8 rounded-lg bg-white dark:bg-slate-700 border shadow flex items-center justify-center hover:bg-muted transition-colors"
        title="重新布局"
        @click="buildGraph"
      >
        <RotateCcw class="h-3.5 w-3.5" />
      </button>
    </div>

    <!-- Legend -->
    <div class="absolute bottom-3 left-3 z-20 bg-white dark:bg-slate-800 border rounded-xl px-3 py-2 shadow text-[11px]">
      <div class="flex flex-col gap-1.5">
        <div v-for="(color, role) in roleColorMap" :key="role" class="flex items-center gap-1.5">
          <span class="w-2.5 h-2.5 rounded-full" :style="{ background: color }" />
          <span class="text-muted-foreground">{{ { protagonist:'主角', antagonist:'反派', supporting:'配角', minor:'龙套' }[role as string] }}</span>
        </div>
        <div v-if="mode === 'realtime' && presentIds.size > 0" class="flex items-center gap-1.5 border-t pt-1.5 mt-0.5">
          <span class="w-2.5 h-2.5 rounded-full border-2 border-white ring-2 ring-indigo-400 bg-indigo-400" />
          <span class="text-muted-foreground">当前出场</span>
        </div>
        <div v-if="inferredLinks.length > 0" class="flex items-center gap-1.5 border-t pt-1.5 mt-0.5">
          <svg width="16" height="8" viewBox="0 0 16 8">
            <line x1="0" y1="4" x2="16" y2="4" stroke="#a5b4fc" stroke-width="1.5" stroke-dasharray="4,3" />
          </svg>
          <span class="text-muted-foreground">同场推断</span>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="characters.length === 0" class="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
      <Users class="h-10 w-10 opacity-20 mb-2" />
      <p class="text-sm">暂无角色，请先添加</p>
    </div>
  </div>
</template>

<style scoped>
.character-graph {
  user-select: none;
}

.animate-pulse {
  animation: ring-pulse 2.5s ease-in-out infinite;
}

@keyframes ring-pulse {
  0%, 100% { opacity: 0.3; r: 0; }
  50% { opacity: 0.6; }
}

/* Tooltip fade */
.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
  transform: scale(0.95) translateY(4px);
}

/* Panel fade */
.panel-fade-enter-active,
.panel-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.panel-fade-enter-from,
.panel-fade-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}
</style>
