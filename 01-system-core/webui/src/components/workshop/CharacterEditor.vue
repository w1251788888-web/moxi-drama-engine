<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Plus, Trash2, Save, X, Users, Link } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'

interface Relationship {
  targetId: string
  targetName: string
  type: string
  earlyType?: string
  lateType?: string
  transitionEpisode?: number | null
  transitionTrigger?: string
  finalBoundary?: string
  candidateStatus?: string
  strength: number
  description: string
  episodes: number[]
}

interface Character {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  age: number
  occupation: string
  background: string
  motivation: string
  arc: string
  personality?: string
  voice_style?: string
  voiceprint?: string
  inner_need?: string
  resource?: string
  first_appearance_function?: string
  relationship_tension?: string
  traits?: string
  notes?: string
  relationships: Relationship[]
  appearance?: string
}

const props = defineProps<{
  characters: Character[]
  selectedId: string | null
  roleColors: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'add', character: Omit<Character, 'id'>): void
  (e: 'remove', id: string): void
  (e: 'update', id: string, updates: Partial<Character>): void
  (e: 'add-relationship', sourceId: string, relationship: Relationship): void
  (e: 'select', id: string): void
}>()

const showAddForm = ref(false)
const editingCharacter = ref<Character | null>(null)

// 新增角色表单
const newCharacter = ref({
  name: '',
  role: 'supporting' as const,
  age: 25,
  occupation: '',
  background: '',
  motivation: '',
  arc: '',
  voiceprint: '',
  inner_need: '',
  resource: '',
  first_appearance_function: '',
  relationship_tension: '',
  relationships: [],
})

// 关系表单
const newRelationship = ref({
  targetId: '',
  type: '',
  customRelationshipType: '',
  earlyType: '',
  lateType: '',
  transitionEpisode: null as number | null,
  transitionTrigger: '',
  finalBoundary: '',
  strength: 50,
  description: ''
})

const roleOptions = [
  { value: 'protagonist', label: '主角', color: props.roleColors.protagonist },
  { value: 'antagonist', label: '反派', color: props.roleColors.antagonist },
  { value: 'supporting', label: '配角', color: props.roleColors.supporting },
  { value: 'minor', label: '龙套', color: props.roleColors.minor }
]

const selectedCharacter = computed(() =>
  props.characters.find(c => c.id === props.selectedId)
)

const canAddRelationship = computed(() =>
  newRelationship.value.targetId &&
  (normalizeRelationshipType() || newRelationship.value.earlyType.trim()) &&
  editingCharacter.value
)

const submitNewCharacter = () => {
  if (!newCharacter.value.name) return
  emit('add', { ...newCharacter.value })
  showAddForm.value = false
  resetNewCharacter()
}

const resetNewCharacter = () => {
  newCharacter.value = {
    name: '',
    role: 'supporting',
    age: 25,
    occupation: '',
    background: '',
    motivation: '',
    arc: '',
    voiceprint: '',
    inner_need: '',
    resource: '',
    first_appearance_function: '',
    relationship_tension: '',
    relationships: [],
  }
}

const cloneCharacterForEdit = (character: Character): Character => ({
  ...character,
  relationships: Array.isArray(character.relationships)
    ? character.relationships.map(rel => ({
        ...rel,
        earlyType: rel.earlyType || rel.type,
        lateType: rel.lateType || rel.earlyType || rel.type,
        candidateStatus: rel.candidateStatus || 'confirmed',
        episodes: [...(rel.episodes || [])],
      }))
    : [],
})

const startEdit = (character: Character) => {
  emit('select', character.id)
  editingCharacter.value = cloneCharacterForEdit(character)
}

const saveEdit = () => {
  if (editingCharacter.value) {
    const { id, ...updates } = editingCharacter.value
    emit('update', id, updates)
    editingCharacter.value = null
  }
}

const cancelEdit = () => {
  editingCharacter.value = null
}

watch(
  () => props.selectedId,
  (id) => {
    if (!id) {
      editingCharacter.value = null
      return
    }
    if (editingCharacter.value?.id === id) return
    const character = props.characters.find(c => c.id === id)
    if (character) editingCharacter.value = cloneCharacterForEdit(character)
  },
  { immediate: true },
)

const addRelationship = () => {
  if (!canAddRelationship.value || !editingCharacter.value) return

  const target = props.characters.find(c => c.id === newRelationship.value.targetId)
  if (!target) return

  const earlyType = newRelationship.value.earlyType.trim() || normalizeRelationshipType()
  const lateType = newRelationship.value.lateType.trim() || earlyType
  const transitionEpisode = Number(newRelationship.value.transitionEpisode || 0)
  const relationship: Relationship = {
    targetId: newRelationship.value.targetId,
    targetName: target.name,
    type: earlyType,
    earlyType,
    lateType,
    transitionEpisode: Number.isFinite(transitionEpisode) && transitionEpisode > 0 ? transitionEpisode : null,
    transitionTrigger: newRelationship.value.transitionTrigger.trim(),
    finalBoundary: newRelationship.value.finalBoundary.trim(),
    candidateStatus: 'confirmed',
    strength: newRelationship.value.strength,
    description: newRelationship.value.description,
    episodes: []
  }

  editingCharacter.value.relationships = [
    ...(editingCharacter.value.relationships || []),
    relationship,
  ]
  syncEditingRelationships()

  // 重置关系表单
  newRelationship.value = {
    targetId: '',
    type: '',
    customRelationshipType: '',
    earlyType: '',
    lateType: '',
    transitionEpisode: null,
    transitionTrigger: '',
    finalBoundary: '',
    strength: 50,
    description: ''
  }
}

const relationshipTypes = [
  '父子', '父女', '母子', '母女', '亲子', '亲属',
  '兄弟', '姐妹', '恋人', '夫妻', '前任',
  '师徒', '上下级', '敌对', '竞争', '朋友', '仇敌', '暗恋', '单恋', '合作',
  '自定义关系',
]

const normalizeRelationshipType = () => {
  if (newRelationship.value.type === '自定义关系') {
    return newRelationship.value.customRelationshipType.trim()
  }
  return newRelationship.value.type.trim()
}

const getRoleBadgeClass = (role: string) => {
  const classes: Record<string, string> = {
    protagonist: 'bg-blue-100 text-blue-700 border-blue-200',
    antagonist: 'bg-red-100 text-red-700 border-red-200',
    supporting: 'bg-green-100 text-green-700 border-green-200',
    minor: 'bg-gray-100 text-gray-600 border-gray-200'
  }
  return classes[role] || 'bg-gray-100 text-gray-600'
}

const updateEditingAge = (value: string | number) => {
  if (!editingCharacter.value) return
  const next = Number(value)
  editingCharacter.value.age = Number.isFinite(next) ? next : 0
}

const updateRelationshipStrength = (value: string | number) => {
  const next = Number(value)
  newRelationship.value.strength = Number.isFinite(next) ? next : 0
}

const cloneRelationships = () => (
  editingCharacter.value?.relationships || []
).map(rel => ({ ...rel, episodes: [...(rel.episodes || [])] }))

const syncEditingRelationships = () => {
  if (!editingCharacter.value) return
  emit('update', editingCharacter.value.id, { relationships: cloneRelationships() })
}

const removeRelationship = (index: number) => {
  if (!editingCharacter.value?.relationships) return
  editingCharacter.value.relationships.splice(index, 1)
  syncEditingRelationships()
}
</script>

<template>
  <div class="character-editor flex flex-row bg-background rounded-lg border overflow-hidden h-full" style="min-height: 560px;">
    <!-- 左侧：角色列表 -->
    <div class="character-list w-72 shrink-0 border-r flex flex-col overflow-hidden">
      <div class="list-header flex items-center justify-between p-4 border-b">
        <h3 class="font-medium text-sm">角色列表 ({{ characters.length }})</h3>
        <Button size="sm" @click="showAddForm = true">
          <Plus class="h-4 w-4 mr-1" />
          添加
        </Button>
      </div>

      <div class="characters-grid flex-1 overflow-y-auto p-3 space-y-2">
        <div
          v-for="char in characters"
          :key="char.id"
          class="character-card flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all border"
          :class="[
            selectedId === char.id ? 'bg-muted border-primary' : 'hover:bg-muted/50 border-transparent',
            char.relationships?.length ? 'has-relationships' : ''
          ]"
          @click="startEdit(char)"
        >
          <div class="char-avatar w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold text-sm"
               :style="{ background: roleColors[char.role] }">
            {{ char.name[0] }}
          </div>
          <div class="char-info flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="char-name font-medium text-sm truncate">{{ char.name }}</span>
            </div>
            <div class="flex items-center gap-2 mt-0.5">
              <Badge variant="outline" class="text-[10px] px-1.5 py-0 h-4" :class="getRoleBadgeClass(char.role)">
                {{ roleOptions.find(r => r.value === char.role)?.label }}
              </Badge>
              <span v-if="char.relationships?.length" class="text-[10px] text-muted-foreground flex items-center gap-1">
                <Link class="h-3 w-3" />
                {{ char.relationships.length }}
              </span>
            </div>
          </div>
        </div>

        <div v-if="characters.length === 0" class="text-center py-8 text-muted-foreground text-sm">
          <Users class="h-8 w-8 mx-auto mb-2 opacity-40" />
          <p>暂无角色</p>
          <Button size="sm" variant="ghost" class="mt-2" @click="showAddForm = true">
            添加第一个角色
          </Button>
        </div>
      </div>

      <!-- 添加角色表单 -->
      <div v-if="showAddForm" class="add-form p-4 border-t bg-muted/30">
        <h4 class="font-medium text-sm mb-3">添加新角色</h4>
        <div class="space-y-3">
          <Input v-model="newCharacter.name" placeholder="角色姓名" />
          <select v-model="newCharacter.role" class="w-full h-9 px-3 rounded-md border bg-background text-sm">
            <option v-for="role in roleOptions" :key="role.value" :value="role.value">
              {{ role.label }}
            </option>
          </select>
        </div>
        <div class="flex gap-2 mt-3">
          <Button variant="outline" size="sm" class="flex-1" @click="showAddForm = false">取消</Button>
          <Button size="sm" class="flex-1" @click="submitNewCharacter" :disabled="!newCharacter.name">
            确认
          </Button>
        </div>
      </div>
    </div>

    <!-- 右侧：编辑区 -->
    <div class="edit-area flex-1 p-4 lg:p-6 overflow-y-auto">
      <div v-if="editingCharacter" class="edit-form max-w-2xl mx-auto space-y-6">
        <div class="edit-header flex items-center justify-between">
          <h3 class="text-lg font-semibold">编辑角色</h3>
          <div class="flex items-center gap-2">
            <Button variant="ghost" size="sm" @click="cancelEdit">
              <X class="h-4 w-4 mr-1" />
              取消
            </Button>
            <Button size="sm" @click="saveEdit">
              <Save class="h-4 w-4 mr-1" />
              保存角色
            </Button>
          </div>
        </div>

        <!-- 基础信息 -->
        <div class="form-section bg-muted/30 rounded-lg p-4 space-y-4">
          <h4 class="font-medium text-sm">基础信息</h4>
          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">姓名</label>
              <Input v-model="editingCharacter.name" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">角色</label>
              <select v-model="editingCharacter.role" class="w-full h-9 px-3 rounded-md border bg-background text-sm">
                <option v-for="role in roleOptions" :key="role.value" :value="role.value">
                  {{ role.label }}
                </option>
              </select>
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">年龄</label>
              <Input
                :model-value="String(editingCharacter.age ?? '')"
                type="number"
                @update:model-value="updateEditingAge"
              />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">职业</label>
              <Input v-model="editingCharacter.occupation" placeholder="角色职业..." />
            </div>
          </div>
        </div>

        <!-- 背景故事 -->
        <div class="form-section bg-muted/30 rounded-lg p-4 space-y-4">
          <h4 class="font-medium text-sm">背景故事</h4>
          <div class="space-y-3">
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">身份背景</label>
              <Textarea v-model="editingCharacter.background" :rows="3" placeholder="角色的出身、成长经历..." />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">核心动机</label>
              <Textarea v-model="editingCharacter.motivation" :rows="2" placeholder="驱动角色行动的根本原因..." />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">人物弧线</label>
              <Textarea v-model="editingCharacter.arc" :rows="2" placeholder="角色在整个故事中的成长或变化..." />
            </div>
          </div>
        </div>

        <!-- 工业化小传 -->
        <div class="form-section bg-muted/30 rounded-lg p-4 space-y-4">
          <h4 class="font-medium text-sm">工业化小传</h4>
          <div class="space-y-3">
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">说话方式 / 声纹</label>
              <Textarea v-model="editingCharacter.voiceprint" :rows="2" placeholder="角色常用语气、句式、说话节奏..." />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">内在需求</label>
              <Textarea v-model="editingCharacter.inner_need" :rows="2" placeholder="角色真正想证明、守住或夺回什么..." />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">资源 / 筹码</label>
              <Textarea v-model="editingCharacter.resource" :rows="2" placeholder="角色能推动剧情的证据、身份、关系或能力..." />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">首次出场功能</label>
              <Textarea v-model="editingCharacter.first_appearance_function" :rows="2" placeholder="第一次出现时必须制造什么信息、冲突或选择..." />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-muted-foreground">关系张力</label>
              <Textarea v-model="editingCharacter.relationship_tension" :rows="2" placeholder="这个角色和谁天然冲突、互相需要或互相制约..." />
            </div>
          </div>
        </div>

        <!-- 关系网络 -->
        <div class="form-section bg-muted/30 rounded-lg p-4 space-y-4">
          <h4 class="font-medium text-sm">关系网络</h4>
          <div v-if="editingCharacter.relationships?.length" class="relationships-list space-y-2">
            <div
              v-for="(rel, index) in editingCharacter.relationships"
              :key="index"
              class="relationship-item flex items-center justify-between p-3 bg-background rounded-lg border"
            >
              <div class="flex items-center gap-3">
                <Badge variant="secondary" class="text-xs">{{ rel.earlyType || rel.type }}</Badge>
                <div class="min-w-0">
                  <span class="font-medium text-sm">{{ rel.targetName }}</span>
                  <div class="text-[11px] text-muted-foreground truncate">
                    早期关系：{{ rel.earlyType || rel.type || '未设定' }}
                    <span v-if="rel.lateType"> → 后期关系：{{ rel.lateType }}</span>
                  </div>
                  <div v-if="rel.transitionEpisode || rel.transitionTrigger || rel.finalBoundary" class="text-[11px] text-muted-foreground truncate">
                    <span v-if="rel.transitionEpisode">转折集：第{{ rel.transitionEpisode }}集</span>
                    <span v-if="rel.transitionTrigger">；转折条件：{{ rel.transitionTrigger }}</span>
                    <span v-if="rel.finalBoundary">；禁止提前写出：{{ rel.finalBoundary }}</span>
                  </div>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <div class="w-24 h-2 bg-muted rounded-full overflow-hidden">
                  <div class="h-full bg-primary rounded-full transition-all"
                       :style="{ width: `${rel.strength}%` }" />
                </div>
                <span class="text-xs text-muted-foreground w-8">{{ rel.strength }}%</span>
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-7 w-7 text-muted-foreground hover:text-destructive"
                  title="删除关系"
                  @click.stop="removeRelationship(index)"
                >
                  <X class="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </div>
          <div v-else class="text-center py-6 text-muted-foreground text-sm bg-background rounded-lg border border-dashed">
            暂无关系，请在下方添加
          </div>

          <!-- 添加关系表单 -->
          <div class="add-relationship-form bg-background rounded-lg p-4 border space-y-3">
            <h5 class="font-medium text-xs">添加关系</h5>
            <div class="grid grid-cols-2 gap-3">
              <select v-model="newRelationship.targetId" class="h-9 px-3 rounded-md border bg-background text-sm">
                <option value="">选择角色</option>
                <option
                  v-for="char in characters.filter(c => c.id !== editingCharacter?.id)"
                  :key="char.id"
                  :value="char.id"
                >
                  {{ char.name }}
                </option>
              </select>
              <select v-model="newRelationship.type" class="h-9 px-3 rounded-md border bg-background text-sm">
                <option value="">关系类型</option>
                <option v-for="type in relationshipTypes" :key="type" :value="type">
                  {{ type }}
                </option>
              </select>
            </div>
            <Input
              v-if="newRelationship.type === '自定义关系'"
              v-model.trim="newRelationship.customRelationshipType"
              placeholder="自定义关系，例如：债主与欠款人、前期监护后期同盟..."
            />
            <div class="grid grid-cols-2 gap-3">
              <Input
                v-model.trim="newRelationship.earlyType"
                placeholder="早期关系，例如：误会、敌对、债主"
              />
              <Input
                v-model.trim="newRelationship.lateType"
                placeholder="后期关系，例如：同盟、恋人、亲人"
              />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <Input
                :model-value="String(newRelationship.transitionEpisode ?? '')"
                type="number"
                min="1"
                placeholder="转折集，例如：8"
                @update:model-value="(value) => { const next = Number(value); newRelationship.transitionEpisode = Number.isFinite(next) && next > 0 ? next : null }"
              />
              <Input
                v-model.trim="newRelationship.transitionTrigger"
                placeholder="转折条件，例如：救下孩子后才转为同盟"
              />
            </div>
            <Input
              v-model.trim="newRelationship.finalBoundary"
              placeholder="禁止提前写出，例如：第8集前不能互相信任"
            />
            <div class="space-y-1.5">
              <div class="flex justify-between text-xs">
                <span class="text-muted-foreground">关系强度</span>
                <span>{{ newRelationship.strength }}%</span>
              </div>
              <input
                :value="newRelationship.strength"
                type="range"
                min="0"
                max="100"
                class="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                @input="updateRelationshipStrength(($event.target as HTMLInputElement).value)"
              />
            </div>
            <Textarea
              v-model="newRelationship.description"
              :rows="2"
              placeholder="关系描述（可选）..."
            />
            <Button size="sm" :disabled="!canAddRelationship" @click="addRelationship" class="w-full">
              <Link class="h-4 w-4 mr-1" />
              添加关系
            </Button>
          </div>
        </div>

        <!-- 删除按钮 -->
        <div class="pt-4 border-t">
          <Button variant="destructive" size="sm" class="w-full" @click="$emit('remove', editingCharacter.id)">
            <Trash2 class="h-4 w-4 mr-1" />
            删除角色
          </Button>
        </div>
      </div>

      <div v-else class="empty-state flex flex-col items-center justify-center h-full text-muted-foreground">
        <Users class="h-12 w-12 mb-3 opacity-30" />
        <p>选择左侧角色进行编辑</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.character-card {
  transition: all 0.2s;
}

.character-card:hover {
  transform: translateX(2px);
}

.character-card.has-relationships {
  border-left: 3px solid transparent;
}

.character-card.has-relationships:hover {
  border-left-color: var(--primary);
}

input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  outline: none;
}

</style>
