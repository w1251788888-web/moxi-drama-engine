import type { Ref } from 'vue'
import { toast } from 'vue-sonner'
import { projectsV2Api, type EpisodeV2, type ProjectV2, type SceneV2 } from '@/api/client'

export const exportFormats = [
  { id: 'txt', label: '纯文本 (.txt)', desc: '通用格式，适合各种阅读器', icon: '📄' },
  { id: 'docx', label: 'Word文档 (.doc)', desc: '标准剧本格式，兼容 Word/WPS 直接投稿', icon: '📝' },
  { id: 'pdf', label: 'PDF文档 (.pdf)', desc: '通过浏览器打印另存为 PDF，固定排版', icon: '📋' },
  { id: 'json', label: 'JSON数据 (.json)', desc: '结构化数据，适合二次开发', icon: '🗂️' },
]

type ProjectRules = {
  total_episodes: number
  episode_seconds: number
  word_count_per_episode: string
  scene_header_style: string
}

type ExportEpisodeScript = {
  ep: number
  title: string
  scenes: SceneV2[]
}

export function useProjectExport({
  project,
  projectRules,
  outlineData,
  characters,
  sceneContent,
  selectedEpisode,
  selectedScene,
  storyboardEpisode,
  storyboardContent,
  markTabComplete,
}: {
  project: Ref<ProjectV2 | null>
  projectRules: Ref<ProjectRules>
  outlineData: Ref<any>
  characters: Ref<any[]>
  sceneContent: Ref<string>
  selectedEpisode: Ref<number>
  selectedScene: Ref<number>
  storyboardEpisode: Ref<number>
  storyboardContent: Ref<string>
  markTabComplete: (tab: 'export') => void
}) {
  async function exportProject(format: string) {
    let scriptEpisodes: ExportEpisodeScript[] = []
    try {
      scriptEpisodes = await loadProjectScriptEpisodes()
    } catch (e) {
      console.error('load export scenes failed', e)
      toast.error('导出失败：没有读到完整剧本正文，请稍后重试')
      return
    }
    if (!assertExportHasScriptContent(scriptEpisodes)) return

    if (format === 'txt') {
      const lines: string[] = []
      const title = project.value?.name || '剧本'
      lines.push(`【${title}】`)
      lines.push(`导出时间：${new Date().toLocaleString('zh-CN')}`)
      lines.push(`项目规则：${projectRules.value.total_episodes}集 / 单集${projectRules.value.episode_seconds}秒 / 净字${projectRules.value.word_count_per_episode} / 场标${projectRules.value.scene_header_style}`)
      lines.push('')
      if (outlineData.value.logline) {
        lines.push('═══ 一句话梗概 ═══')
        lines.push(outlineData.value.logline)
        lines.push('')
      }
      if (outlineData.value.worldview) {
        lines.push('═══ 世界观设定 ═══')
        lines.push(outlineData.value.worldview)
        lines.push('')
      }
      if (outlineData.value.goldenFinger) {
        lines.push('═══ 金手指/特殊设定 ═══')
        lines.push(outlineData.value.goldenFinger)
        lines.push('')
      }
      if (outlineData.value.conflict) {
        lines.push('═══ 核心冲突与爽点 ═══')
        lines.push(outlineData.value.conflict)
        lines.push('')
      }
      const chars = characters.value as any[]
      if (chars.length > 0) {
        lines.push('═══ 角色设定 ═══')
        for (const c of chars) {
          const roleLabel = c.role === 'protagonist' ? '主角' : c.role === 'antagonist' ? '反派' : c.role === 'supporting' ? '配角' : '次要'
          lines.push(`▸ ${c.name}（${roleLabel}${c.age ? '，' + c.age + '岁' : ''}${c.occupation ? '，' + c.occupation : ''}）`)
          if (c.background) lines.push(`  背景：${c.background}`)
          if (c.motivation) lines.push(`  动机：${c.motivation}`)
          if (c.arc) lines.push(`  弧线：${c.arc}`)
          if (c.relationships?.length) {
            lines.push(`  关系：${(c.relationships as any[]).map((r: any) => `与${r.targetName}（${r.type}）`).join('、')}`)
          }
          lines.push('')
        }
      }
      if (outlineData.value.episodes.length > 0) {
        lines.push('═══ 分集框架 ═══')
        for (const ep of outlineData.value.episodes) {
          lines.push(`第${ep.ep}集 《${ep.title}》`)
          if (ep.summary) lines.push(`  情节：${ep.summary}`)
          if ((ep as any).conflict) lines.push(`  冲突：${(ep as any).conflict}`)
          if (ep.hook) lines.push(`  钩子：${ep.hook}`)
          lines.push('')
        }
      }
      if (scriptEpisodes.length > 0) {
        lines.push('═══ 剧本正文（全部已保存场景）═══')
        appendPlainScript(lines, scriptEpisodes)
        lines.push('')
      }
      if (storyboardContent.value) {
        lines.push(`═══ 分镜提示词（第${storyboardEpisode.value}集）═══`)
        lines.push(storyboardContent.value)
      }
      const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
      downloadBlob(blob, `${title}.txt`)
      toast.success('TXT 文件已下载')
      markTabComplete('export')
      return
    }

    if (format === 'docx' || format === 'pdf') {
      const titleStr = project.value?.name || '剧本'
      const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br/>')
      const chars = characters.value as any[]
      const style = format === 'pdf'
        ? `@page{size:A4;margin:20mm}body{font-family:"SimSun","Songti SC",serif;font-size:12pt;line-height:1.8;color:#1a1a1a}h1{font-size:20pt;text-align:center;color:#1a1a8c;margin-bottom:4pt}h2{font-size:14pt;color:#2a2a7a;border-bottom:1px solid #aab;padding-bottom:3pt;margin-top:16pt}h3{font-size:12pt;margin-top:8pt}.meta{color:#888;font-size:10pt;text-align:center;margin-bottom:16pt}.role-card{border-left:3px solid #5b6af0;padding-left:10pt;margin:6pt 0}.ep-row{background:#f5f5f8;padding:4pt 8pt;margin:3pt 0;border-radius:3pt}.script{font-family:monospace;font-size:10.5pt;white-space:pre-wrap;background:#f9f9f9;padding:8pt;border:1px solid #ddd;page-break-inside:avoid}`
        : `body{font-family:"SimSun",serif;font-size:12pt;line-height:1.8}h1{font-size:18pt;text-align:center}h2{font-size:14pt;margin-top:18pt;margin-bottom:6pt;border-bottom:1px solid #ccc;padding-bottom:3pt}h3{font-size:12pt;margin-top:12pt}p{margin:4pt 0}.meta{color:#666;font-size:10pt;text-align:center}.role-card{border-left:3px solid #5b6af0;padding-left:12pt;margin:8pt 0}.ep-row{background:#f8f8f8;padding:4pt 8pt;margin:4pt 0}.script{font-family:"Courier New",monospace;font-size:11pt;white-space:pre-wrap;background:#fafafa;padding:8pt;border:1px solid #eee}`
      let body = `<h1>《${esc(titleStr)}》</h1><div class="meta">导出时间：${new Date().toLocaleString('zh-CN')} | 受众：${outlineData.value.audience_axis || '未设定'} | 题材：${outlineData.value.genre_main || '未设定'} | 格式：${outlineData.value.format_type} | 单集：${projectRules.value.episode_seconds}秒 | 净字：${esc(projectRules.value.word_count_per_episode)}</div>`
      if (outlineData.value.logline) body += `<h2>一句话梗概</h2><p>${esc(outlineData.value.logline)}</p>`
      if (outlineData.value.worldview) body += `<h2>世界观设定</h2><p>${esc(outlineData.value.worldview)}</p>`
      if (outlineData.value.goldenFinger) body += `<h2>金手指 / 特殊设定</h2><p>${esc(outlineData.value.goldenFinger)}</p>`
      if (outlineData.value.conflict) body += `<h2>核心冲突与爽点</h2><p>${esc(outlineData.value.conflict)}</p>`
      if (chars.length > 0) {
        body += `<h2>角色设定</h2>`
        for (const c of chars) {
          const rl = c.role === 'protagonist' ? '主角' : c.role === 'antagonist' ? '反派' : c.role === 'supporting' ? '配角' : '次要'
          body += `<div class="role-card"><h3>${esc(c.name)}（${rl}${c.age ? '，' + c.age + '岁' : ''}）</h3>`
          if (c.background) body += `<p>背景：${esc(c.background)}</p>`
          if (c.motivation) body += `<p>动机：${esc(c.motivation)}</p>`
          if (c.arc) body += `<p>弧线：${esc(c.arc)}</p>`
          body += `</div>`
        }
      }
      if (outlineData.value.episodes.length > 0) {
        body += `<h2>分集框架</h2>`
        for (const ep of outlineData.value.episodes) {
          body += `<div class="ep-row"><strong>第${ep.ep}集 《${esc(ep.title)}》</strong>`
          if (ep.summary) body += `<br/>情节：${esc(ep.summary)}`
          if ((ep as any).conflict) body += `<br/>冲突：${esc((ep as any).conflict)}`
          if (ep.hook) body += `<br/>钩子：${esc(ep.hook)}`
          body += `</div>`
        }
      }
      if (scriptEpisodes.length > 0) {
        body += '<h2>剧本正文（全部已保存场景）</h2>'
        for (const episode of scriptEpisodes) {
          body += `<h3>第${episode.ep}集${episode.title ? ` 《${esc(episode.title)}》` : ''}</h3>`
          for (const scene of episode.scenes) {
            const content = (scene.content || '').trim()
            if (!content) continue
            body += `<div class="script"><strong>第${episode.ep}集 · 第${scene.scene_number}场</strong><br/>${esc(content)}</div>`
          }
        }
      }
      if (storyboardContent.value) body += `<h2>分镜提示词（第${storyboardEpisode.value}集）</h2><div class="script">${esc(storyboardContent.value)}</div>`
      const fullHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>${esc(titleStr)}</title><style>${style}</style></head><body>${body}</body></html>`
      if (format === 'pdf') {
        openPrintPreview(fullHtml)
      } else {
        downloadBlob(new Blob(['\ufeff' + fullHtml], { type: 'application/msword;charset=utf-8' }), `${titleStr}.doc`)
        toast.success('Word 文档已下载（.doc 格式，兼容 Word / WPS）')
        markTabComplete('export')
      }
      return
    }

    if (format === 'json') {
      const exportData = {
        project: project.value,
        project_rules: projectRules.value,
        outline: outlineData.value,
        characters: characters.value,
        script: {
          episodes: scriptEpisodes.map(episode => ({
            episode: episode.ep,
            title: episode.title,
            scenes: episode.scenes
              .filter(scene => (scene.content || '').trim())
              .map(scene => ({
                scene: scene.scene_number,
                time: scene.time,
                location_type: scene.location_type,
                location_name: scene.location_name,
                content: scene.content,
                word_count: scene.word_count,
              })),
          })),
          current_scene: { episode: selectedEpisode.value, scene: selectedScene.value },
        },
        storyboard: { episode: storyboardEpisode.value, content: storyboardContent.value },
        exported_at: new Date().toISOString(),
      }
      const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
      downloadBlob(blob, `${project.value?.name || '剧本'}_data.json`)
      toast.success('JSON 数据已下载')
      markTabComplete('export')
    }
  }

  async function loadProjectScriptEpisodes(): Promise<ExportEpisodeScript[]> {
    const projectId = project.value?.id
    if (!projectId) {
      const fallback = (sceneContent.value || '').trim()
      return fallback
        ? [{
            ep: selectedEpisode.value,
            title: '',
            scenes: [{
              id: 'current',
              scene_number: selectedScene.value,
              scene_code: `${selectedEpisode.value}-${selectedScene.value}`,
              time: '',
              location_type: '',
              location_name: '',
              content: fallback,
              content_preview: fallback.slice(0, 120),
              word_count: fallback.length,
              status: 'draft',
              primary_author: '',
              ai_generated: false,
              created_at: '',
              updated_at: '',
            }],
          }]
        : []
    }

    let episodeList: EpisodeV2[] = []
    try {
      const { data } = await projectsV2Api.listEpisodes(projectId)
      episodeList = Array.isArray(data) ? data : []
    } catch {
      episodeList = []
    }

    const outlineEpisodes = Array.isArray(outlineData.value?.episodes) ? outlineData.value.episodes : []
    const numbers = uniqueEpisodeNumbers([
      ...episodeList.map(episode => Number(episode.episode_number)),
      ...outlineEpisodes.map((episode: any, index: number) => Number(episode?.ep || episode?.episode || episode?.episode_number || index + 1)),
    ])

    if (numbers.length === 0) return []

    const { data } = await projectsV2Api.listScenesBatch(projectId, numbers)
    const titleByEpisode = new Map<number, string>()
    for (const episode of episodeList) {
      titleByEpisode.set(Number(episode.episode_number), episode.title || '')
    }
    for (const episode of outlineEpisodes) {
      const ep = Number(episode?.ep || episode?.episode || episode?.episode_number)
      if (Number.isFinite(ep) && !titleByEpisode.get(ep)) titleByEpisode.set(ep, episode?.title || '')
    }

    return numbers
      .map((ep) => {
        const rawScenes = data?.[String(ep)]
        const scenesForEpisode: SceneV2[] = Array.isArray(rawScenes) ? rawScenes : []
        return {
          ep,
          title: titleByEpisode.get(ep) || '',
          scenes: scenesForEpisode
            .filter((scene: SceneV2) => (scene.content || '').trim())
            .sort((a: SceneV2, b: SceneV2) => Number(a.scene_number) - Number(b.scene_number)),
        }
      })
      .filter(episode => episode.scenes.length > 0)
  }

  function assertExportHasScriptContent(scriptEpisodes: ExportEpisodeScript[]) {
    const savedSceneCount = scriptEpisodes.reduce((total, episode) => {
      return total + episode.scenes.filter(scene => String(scene.content || '').trim()).length
    }, 0)
    if (savedSceneCount <= 0) {
      toast.error('导出失败：还没有可导出的剧本正文。请先生成或手动保存至少一场正文。')
      return false
    }
    return true
  }

  function appendPlainScript(lines: string[], episodes: ExportEpisodeScript[]) {
    for (const episode of episodes) {
      lines.push(`第${episode.ep}集${episode.title ? ` 《${episode.title}》` : ''}`)
      for (const scene of episode.scenes) {
        const content = (scene.content || '').trim()
        if (!content) continue
        lines.push(`【第${episode.ep}集 · 第${scene.scene_number}场】`)
        lines.push(content)
        lines.push('')
      }
    }
  }

  function uniqueEpisodeNumbers(values: number[]) {
    return [...new Set(values)]
      .filter(value => Number.isFinite(value) && value > 0)
      .map(value => Math.trunc(value))
      .sort((a, b) => a - b)
  }

  function openPrintPreview(fullHtml: string) {
    const script = `<script>window.onload=function(){window.print();window.onafterprint=function(){window.close()}}<\/script>`
    const printHtml = fullHtml.replace('</body>', script + '</body>')
    const win = window.open('', '_blank')
    if (win) {
      win.document.write(printHtml)
      win.document.close()
      toast.success('打印预览已打开，请选择“另存为 PDF”')
      markTabComplete('export')
    } else {
      toast.error('请允许弹出窗口后重试')
    }
  }

  return { exportFormats, exportProject }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
