<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, CreditCard, LogOut, Moon, PackageCheck, RefreshCw, ReceiptText, Sun, WalletCards } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import {
  userAccessApi,
  type PaymentOrderItem,
  type SubscriptionPlanItem,
  type UserAccessKeySession,
} from '@/api/client'
import { Button } from '@/components/ui/button'

const router = useRouter()
const auth = useAuthStore()
const themeStore = useThemeStore()

const loading = ref(false)
const loadError = ref('')
const orderLoadError = ref('')
const subscribingPlanId = ref('')
const subscriptionPlans = ref<SubscriptionPlanItem[]>([])
const subscriptionOrders = ref<PaymentOrderItem[]>([])
const hasUserSession = computed(() => !!auth.userSession?.session_token)
const isLowBalance = computed(() => (auth.userSession?.credit_balance ?? 0) < 1)

async function loadSettings() {
  loading.value = true
  loadError.value = ''
  orderLoadError.value = ''
  try {
    const plansRes = await userAccessApi.listSubscriptionPlans()
    subscriptionPlans.value = plansRes.data.items
  } catch {
    loadError.value = '套餐读取失败，请稍后重试'
  }

  if (!hasUserSession.value) {
    subscriptionOrders.value = []
    orderLoadError.value = '请使用前台用户账号登录后查看订单和订阅状态'
    loading.value = false
    return
  }

  try {
    await auth.refreshUserSession()
    const ordersRes = await userAccessApi.listSubscriptionOrders()
    subscriptionOrders.value = ordersRes.data.items
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    orderLoadError.value = detail || '订单读取失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function applySessionRefresh(order: PaymentOrderItem) {
  if (order.user_session) {
    auth.setUserSession(order.user_session)
    return
  }
  const patch: Partial<UserAccessKeySession> = {}
  if (typeof order.credit_balance === 'number') {
    patch.credit_balance = order.credit_balance
  }
  if (typeof order.advanced_generation_enabled === 'boolean') {
    patch.advanced_generation_enabled = order.advanced_generation_enabled
  }
  if (Object.keys(patch).length) {
    auth.patchUserSession(patch)
  }
}

async function subscribePlan(plan: SubscriptionPlanItem) {
  if (!hasUserSession.value) {
    loadError.value = '请先用前台用户账号登录后再订阅套餐'
    return
  }
  subscribingPlanId.value = plan.plan_id
  loadError.value = ''
  orderLoadError.value = ''
  try {
    const { data } = await userAccessApi.createSubscriptionOrder({ plan_id: plan.plan_id, checkout_mode: 'demo' })
    applySessionRefresh(data)
    await auth.refreshUserSession().catch(() => null)
    toast.success('模拟支付成功，订阅已生效')
    await loadSettings()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    loadError.value = detail || '订阅失败，请稍后重试'
  } finally {
    subscribingPlanId.value = ''
  }
}

function logout() {
  auth.logout()
  router.push('/login')
}

function formatOrderTime(order: PaymentOrderItem) {
  return (order.paid_at || order.created_at || '-').replace('T', ' ').slice(0, 16)
}

onMounted(() => { void loadSettings() })
</script>

<template>
  <div class="min-h-[calc(100vh-3.5rem)] bg-[#f8fbff] p-6 text-[#101828]">
    <div class="mx-auto max-w-5xl space-y-6">
      <header class="rounded-[24px] bg-white p-6 shadow-sm">
        <p class="text-sm text-[#667085]">我的账号</p>
        <h1 class="mt-2 text-2xl font-semibold">前台使用中心</h1>
        <p class="mt-2 text-sm leading-6 text-[#667085]">
          这里显示你的密钥状态、剩余额度、套餐订阅和订单记录。额度不足时可先在这里恢复可用额度，模型接口、系统密钥、充值管理统一放在后台。
        </p>
      </header>

      <div v-if="loadError || orderLoadError" class="flex items-center justify-between rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span>{{ loadError || orderLoadError }}</span>
        <Button size="sm" variant="outline" @click="loadSettings">
          <RefreshCw class="mr-2 h-4 w-4" />
          重试
        </Button>
      </div>

      <div v-if="hasUserSession && isLowBalance" class="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
        <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <div class="font-medium">当前额度偏低</div>
          <p class="mt-1 leading-6">继续生成前建议先订阅套餐或联系管理员充值，避免任务执行到扣费阶段后中断。</p>
        </div>
      </div>

      <section class="grid gap-4 md:grid-cols-3">
        <article class="rounded-[22px] bg-white p-5 shadow-sm">
          <div class="text-sm text-[#667085]">当前用户</div>
          <div class="mt-3 text-xl font-semibold">
            {{ auth.userSession?.owner_name || '未绑定用户' }}
          </div>
        </article>
        <article class="rounded-[22px] bg-white p-5 shadow-sm">
          <div class="flex items-center gap-2 text-sm text-[#667085]">
            <WalletCards class="h-4 w-4" />
            剩余额度
          </div>
          <div class="mt-3 text-xl font-semibold">
            {{ auth.userSession?.credit_balance ?? 0 }} 额度
          </div>
        </article>
        <article class="rounded-[22px] bg-white p-5 shadow-sm">
          <div class="text-sm text-[#667085]">科研生成权限</div>
          <div class="mt-3 text-xl font-semibold">
            {{ auth.advancedGenerationEnabled ? '已开启' : '未开启' }}
          </div>
        </article>
      </section>

      <section class="grid gap-4 lg:grid-cols-2">
        <article class="rounded-[24px] bg-white p-5 shadow-sm">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold">订阅套餐</h2>
            <PackageCheck class="h-5 w-5 text-[#2e8bd1]" />
          </div>
          <div class="space-y-3">
            <div
              v-for="plan in subscriptionPlans"
              :key="plan.plan_id"
              class="rounded-2xl border border-[#edf2f7] bg-[#f8fbff] p-4"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <div class="font-semibold">{{ plan.name }}</div>
                  <p class="mt-1 text-sm leading-6 text-[#667085]">{{ plan.description || '订阅后立即到账额度' }}</p>
                </div>
                <div class="text-right">
                  <div class="text-lg font-semibold">¥{{ plan.price_cny }}</div>
                  <div class="text-xs text-[#98a2b3]">{{ plan.validity_days }} 天</div>
                </div>
              </div>
              <div class="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
                <span class="rounded-full bg-white px-3 py-1 text-[#344054]">
                  {{ plan.credit_amount }} 额度 · {{ plan.advanced_generation_enabled ? '含科研生成' : '基础权限' }}
                </span>
                <Button
                  size="sm"
                  class="rounded-xl bg-[#2e8bd1] text-white hover:bg-[#247ac0]"
                  :disabled="!hasUserSession || subscribingPlanId === plan.plan_id || plan.status !== 'active'"
                  @click="subscribePlan(plan)"
                >
                  <CreditCard class="mr-2 h-4 w-4" />
                  {{ !hasUserSession ? '请先登录' : subscribingPlanId === plan.plan_id ? '模拟支付中...' : '模拟支付/订阅' }}
                </Button>
              </div>
            </div>
            <div v-if="!subscriptionPlans.length && !loading" class="rounded-2xl border border-dashed border-[#d0d5dd] p-5 text-sm text-[#667085]">
              暂无可订阅套餐。
            </div>
          </div>
        </article>
        <article class="rounded-[24px] bg-white p-5 shadow-sm">
          <h2 class="text-lg font-semibold">显示偏好</h2>
          <div class="mt-4 flex gap-3">
            <Button variant="outline" class="rounded-2xl" @click="themeStore.setTheme('light')">
              <Sun class="mr-2 h-4 w-4" />
              浅色
            </Button>
            <Button variant="outline" class="rounded-2xl" @click="themeStore.setTheme('dark')">
              <Moon class="mr-2 h-4 w-4" />
              深色
            </Button>
          </div>
        </article>
      </section>

      <section class="rounded-[24px] bg-white p-5 shadow-sm">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-lg font-semibold">用户订单列表</h2>
          <ReceiptText class="h-5 w-5 text-[#2e8bd1]" />
        </div>
        <div v-if="orderLoadError" class="mb-4 rounded-2xl border border-dashed border-[#d0d5dd] bg-[#f8fbff] px-4 py-3 text-sm text-[#667085]">
          {{ orderLoadError }}
        </div>
        <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
          <table class="w-full text-left text-sm">
            <thead class="bg-[#f8fbff] text-[#667085]">
              <tr>
                <th class="px-4 py-3">套餐</th>
                <th class="px-4 py-3">金额</th>
                <th class="px-4 py-3">额度</th>
                <th class="px-4 py-3">状态</th>
                <th class="px-4 py-3">时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="order in subscriptionOrders" :key="order.order_id" class="border-t border-[#edf2f7]">
                <td class="px-4 py-3">{{ order.plan_name || order.plan_id }}</td>
                <td class="px-4 py-3">¥{{ order.amount_cny }}</td>
                <td class="px-4 py-3">{{ order.credit_amount }}</td>
                <td class="px-4 py-3">{{ order.status }}</td>
                <td class="px-4 py-3">{{ formatOrderTime(order) }}</td>
              </tr>
              <tr v-if="!subscriptionOrders.length">
                <td colspan="5" class="px-4 py-6 text-center text-[#98a2b3]">暂无订阅订单</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <Button variant="outline" class="rounded-2xl" @click="logout">
        <LogOut class="mr-2 h-4 w-4" />
        退出登录
      </Button>
    </div>
  </div>
</template>
