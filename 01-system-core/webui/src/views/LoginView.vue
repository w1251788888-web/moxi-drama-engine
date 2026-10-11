<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { CheckCircle2, Copy, Eye, EyeOff, KeyRound, LockKeyhole, UserPlus, UserRound } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { clipboardCopy } from '@/lib/clipboard'
import { toChineseErrorDetail } from '@/api/http'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'accessKey' | 'account' | 'register'>('accessKey')
const accessKey = ref('')
const accountUsername = ref('')
const accountPassword = ref('')
const registerName = ref('')
const registerPassword = ref('')
const inviteCode = ref('')
const registerContact = ref('')
const issuedAccessKey = ref('')
const loading = ref(false)
const error = ref('')
const accountPasswordVisible = ref(false)
const registerPasswordVisible = ref(false)
const copyFeedback = ref('')

function resetFeedback() {
  error.value = ''
  copyFeedback.value = ''
}

function extractErrorMessage(e: unknown, fallback: string) {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  const message = (e as { message?: string })?.message
  return toChineseErrorDetail(detail || message, fallback)
}

function validateRegisterForm() {
  const username = registerName.value.trim()
  const password = registerPassword.value
  const code = inviteCode.value.trim()
  const contact = registerContact.value.trim()

  if (!username) return '请填写用户名'
  if (username.length < 2) return '用户名至少 2 个字符'
  if (!password) return '请填写密码'
  if (password.length < 6) return '密码至少 6 位'
  if (!code) return '请填写邀请码'
  if (contact && contact.includes('@') && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact)) {
    return '邮箱格式不正确'
  }
  if (contact && !contact.includes('@') && !/^[0-9+\-\s()]{6,}$/.test(contact)) {
    return '手机号格式不正确'
  }
  return ''
}

async function handleAccessKeyLogin() {
  if (!accessKey.value.trim()) {
    error.value = '请输入后台发给你的使用密钥'
    return
  }
  loading.value = true
  resetFeedback()
  try {
    await auth.loginWithAccessKey(accessKey.value.trim())
    router.push('/projects')
  } catch (e: unknown) {
    error.value = extractErrorMessage(e, '密钥无效或已停用，请联系管理员')
  } finally {
    loading.value = false
  }
}

async function handleAccountLogin() {
  if (!accountUsername.value.trim() || !accountPassword.value) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  resetFeedback()
  try {
    await auth.loginWithAccount(accountUsername.value.trim(), accountPassword.value)
    router.push('/projects')
  } catch (e: unknown) {
    error.value = extractErrorMessage(e, '账号或密码不正确，请检查后重试')
  } finally {
    loading.value = false
  }
}

async function handleInviteRegister() {
  const validationError = validateRegisterForm()
  if (validationError) {
    error.value = validationError
    return
  }
  loading.value = true
  resetFeedback()
  issuedAccessKey.value = ''
  try {
    const contact = registerContact.value.trim()
    const session = await auth.registerWithInvite({
      username: registerName.value.trim(),
      password: registerPassword.value,
      invite_code: inviteCode.value.trim(),
      email: contact.includes('@') ? contact : '',
      phone: contact && !contact.includes('@') ? contact : '',
    })
    issuedAccessKey.value = session.plain_key || ''
  } catch (e: unknown) {
    error.value = extractErrorMessage(e, '注册失败，请检查邀请码是否有效或是否已被使用')
  } finally {
    loading.value = false
  }
}

async function copyIssuedAccessKey() {
  if (!issuedAccessKey.value) return
  try {
    await clipboardCopy(issuedAccessKey.value)
    copyFeedback.value = '使用密钥已复制'
  } catch {
    copyFeedback.value = '复制失败，请手动选中密钥复制'
  }
}
</script>

<template>
  <div class="min-h-screen overflow-x-hidden bg-[#eef7ff] text-[#121826]">
    <div class="mx-auto grid min-h-screen max-w-6xl grid-cols-1 items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:py-10">
      <section class="space-y-7">
        <div class="inline-flex items-center gap-2 rounded-full bg-white/80 px-4 py-2 text-sm text-[#3d6f9f] shadow-sm">
          <LockKeyhole class="h-4 w-4" />
          密钥制内测入口
        </div>
        <div>
          <h1 class="text-4xl font-semibold tracking-normal md:text-5xl">墨戏生花</h1>
          <p class="mt-4 max-w-xl text-base leading-7 text-[#536173]">
            前台用户只需要输入后台生成的使用密钥。模型配置、额度充值、生成日志和科研生成链路都由后台统一管理。
          </p>
        </div>
      </section>

      <section class="w-full min-w-0 rounded-3xl bg-white p-4 shadow-[0_30px_90px_rgba(61,111,159,0.18)] sm:p-6">
        <div class="grid gap-5">
          <div class="grid grid-cols-1 gap-1 rounded-2xl bg-[#edf6ff] p-1 text-sm font-medium text-[#4f647a] sm:grid-cols-3">
            <button
              type="button"
              class="rounded-xl px-3 py-2 transition sm:px-4"
              :class="mode === 'accessKey' ? 'bg-white text-[#172033] shadow-sm' : 'hover:text-[#172033]'"
              @click="mode = 'accessKey'; resetFeedback()"
            >
              密钥登录
            </button>
            <button
              type="button"
              class="rounded-xl px-3 py-2 transition sm:px-4"
              :class="mode === 'account' ? 'bg-white text-[#172033] shadow-sm' : 'hover:text-[#172033]'"
              @click="mode = 'account'; resetFeedback()"
            >
              账号登录
            </button>
            <button
              type="button"
              class="rounded-xl px-3 py-2 transition sm:px-4"
              :class="mode === 'register' ? 'bg-white text-[#172033] shadow-sm' : 'hover:text-[#172033]'"
              @click="mode = 'register'; resetFeedback()"
            >
              邀请码注册
            </button>
          </div>

          <div class="min-w-0 rounded-2xl bg-[#f8fbff] p-4 sm:p-5">
            <div class="flex items-start gap-3 sm:items-center">
              <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#6bb8ef] text-white">
                <KeyRound v-if="mode === 'accessKey'" class="h-5 w-5" />
                <UserRound v-else-if="mode === 'account'" class="h-5 w-5" />
                <UserPlus v-else class="h-5 w-5" />
              </div>
              <div class="min-w-0">
                <h2 class="text-xl font-semibold">
                  {{ mode === 'accessKey' ? '用户密钥登录' : mode === 'account' ? '账号登录' : '邀请码注册' }}
                </h2>
                <p class="text-sm text-[#667085]">
                  {{ mode === 'accessKey' ? '请输入管理员后台生成的密钥' : mode === 'account' ? '使用注册账号进入创作台' : '注册后自动生成使用密钥和登录会话' }}
                </p>
              </div>
            </div>

            <form v-if="mode === 'accessKey'" class="mt-5 space-y-4" @submit.prevent="handleAccessKeyLogin">
              <Input
                v-model="accessKey"
                class="h-12 rounded-2xl border-[#dbe7f3] bg-white"
                placeholder="MOXI-XXXX-XXXX-XXXX"
                :disabled="loading"
              />
              <p v-if="error" class="rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-600">
                {{ error }}
              </p>
              <Button class="h-12 w-full rounded-2xl bg-[#2e8bd1] text-white hover:bg-[#247ac0]" :disabled="loading">
                {{ loading ? '正在进入...' : '进入创作台' }}
              </Button>
            </form>

            <form v-else-if="mode === 'account'" class="mt-5 space-y-4" @submit.prevent="handleAccountLogin">
              <Input
                v-model="accountUsername"
                class="h-12 rounded-2xl border-[#dbe7f3] bg-white"
                placeholder="用户名"
                :disabled="loading"
              />
              <div class="relative">
                <Input
                  v-model="accountPassword"
                  class="h-12 rounded-2xl border-[#dbe7f3] bg-white pr-12"
                  placeholder="密码"
                  :type="accountPasswordVisible ? 'text' : 'password'"
                  autocomplete="current-password"
                  :disabled="loading"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-[#64748b] hover:bg-[#edf6ff] hover:text-[#172033]"
                  :aria-label="accountPasswordVisible ? '隐藏密码' : '显示密码'"
                  @click="accountPasswordVisible = !accountPasswordVisible"
                >
                  <EyeOff v-if="accountPasswordVisible" class="h-4 w-4" />
                  <Eye v-else class="h-4 w-4" />
                </button>
              </div>
              <p v-if="error" class="rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-600">
                {{ error }}
              </p>
              <Button class="h-12 w-full rounded-2xl bg-[#2e8bd1] text-white hover:bg-[#247ac0]" :disabled="loading">
                {{ loading ? '正在登录...' : '账号登录' }}
              </Button>
            </form>

            <form v-else class="mt-5 space-y-4" @submit.prevent="handleInviteRegister">
              <Input
                v-model="registerName"
                class="h-12 rounded-2xl border-[#dbe7f3] bg-white"
                placeholder="用户名"
                autocomplete="username"
                :disabled="loading"
              />
              <div class="relative">
                <Input
                  v-model="registerPassword"
                  class="h-12 rounded-2xl border-[#dbe7f3] bg-white pr-12"
                  placeholder="密码，至少 6 位"
                  :type="registerPasswordVisible ? 'text' : 'password'"
                  autocomplete="new-password"
                  :disabled="loading"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-[#64748b] hover:bg-[#edf6ff] hover:text-[#172033]"
                  :aria-label="registerPasswordVisible ? '隐藏密码' : '显示密码'"
                  @click="registerPasswordVisible = !registerPasswordVisible"
                >
                  <EyeOff v-if="registerPasswordVisible" class="h-4 w-4" />
                  <Eye v-else class="h-4 w-4" />
                </button>
              </div>
              <p class="text-xs leading-5 text-[#667085]">密码至少 6 位；手机号或邮箱可选，用于找回和管理员备注。</p>
              <Input
                v-model="registerContact"
                class="h-12 rounded-2xl border-[#dbe7f3] bg-white"
                placeholder="手机号或邮箱，可选"
                :disabled="loading"
              />
              <Input
                v-model="inviteCode"
                class="h-12 rounded-2xl border-[#dbe7f3] bg-white"
                placeholder="MOXI-INV-XXXX-XXXX-XXXX"
                :disabled="loading"
              />
              <p v-if="error" class="rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-600">
                {{ error }}
              </p>
              <div v-if="issuedAccessKey" class="space-y-3 rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-3 text-sm text-emerald-700">
                <div class="flex items-start gap-2">
                  <CheckCircle2 class="mt-0.5 h-4 w-4 shrink-0" />
                  <div class="min-w-0">
                    <div class="font-medium">注册成功，请保存使用密钥</div>
                    <div class="mt-1 break-all rounded-lg bg-white/70 px-3 py-2 font-mono text-xs text-emerald-900">
                      {{ issuedAccessKey }}
                    </div>
                  </div>
                </div>
                <div class="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-center">
                  <p class="text-xs text-emerald-700">
                    {{ copyFeedback || '一键复制后再进入创作台，避免刷新后看不到明文密钥。' }}
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    class="h-10 rounded-xl border-emerald-200 bg-white px-3 text-emerald-700 hover:bg-emerald-100"
                    data-testid="copy-issued-access-key"
                    @click="copyIssuedAccessKey"
                  >
                    <Copy class="mr-2 h-4 w-4" />
                    复制使用密钥
                  </Button>
                </div>
              </div>
              <Button
                v-if="issuedAccessKey"
                type="button"
                class="h-12 w-full rounded-2xl bg-[#2e8bd1] text-white hover:bg-[#247ac0]"
                @click="router.push('/projects')"
              >
                进入创作台
              </Button>
              <Button v-else class="h-12 w-full rounded-2xl bg-[#2e8bd1] text-white hover:bg-[#247ac0]" :disabled="loading">
                {{ loading ? '正在注册...' : '完成注册' }}
              </Button>
            </form>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-dashed border-[#c8d8ea] p-4">
              <div class="flex items-center gap-2 text-sm font-medium">
                <UserPlus class="h-4 w-4 text-[#2e8bd1]" />
                注册框架
              </div>
              <p class="mt-2 text-sm leading-6 text-[#667085]">
                手机号、邮箱、账号密码注册已接入邀请码池。
              </p>
            </div>
            <div class="rounded-2xl border border-dashed border-[#c8d8ea] p-4">
              <div class="text-sm font-medium">账号登录框架</div>
              <p class="mt-2 text-sm leading-6 text-[#667085]">
                已接入账号密码登录，登录后只保存安全会话。
              </p>
            </div>
          </div>

          <router-link
            v-if="mode === 'account'"
            class="text-center text-sm text-[#2e8bd1] hover:underline"
            to="/moxi-admin"
          >
            管理员入口
          </router-link>
        </div>
      </section>
    </div>
  </div>
</template>
