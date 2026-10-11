from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "webui" / "src"


def test_frontend_has_separate_moxi_admin_entry_and_user_key_login():
    router = (SRC / "router" / "index.ts").read_text(encoding="utf-8")
    login = (SRC / "views" / "LoginView.vue").read_text(encoding="utf-8")
    auth_store = (SRC / "stores" / "auth.ts").read_text(encoding="utf-8")
    saas_api = (SRC / "api" / "modules" / "saasAdmin.ts").read_text(encoding="utf-8")

    assert "/moxi-admin" in router
    assert "MoxiAdminView" in router
    assert "accessKey" in login
    assert "accountUsername" in login
    assert "handleAccountLogin" in login
    assert "账号登录" in login
    assert "inviteCode" in login
    assert "registerWithInvite" in login
    assert "邀请码注册" in login
    assert "loginWithAccount" in auth_store
    assert "refreshUserSession" in auth_store
    assert "clearUserSession" in auth_store
    assert "/user/account/login" in saas_api
    assert "/user/session" in saas_api
    assert "plain_key" in saas_api
    assert "allow_copy_export" in auth_store
    assert "copyExportAllowed" in auth_store
    assert "setCopyExportPermission" in saas_api
    assert "refreshProviderModels" in saas_api
    assert "/moxi-admin/llm-providers/${provider}/models/refresh" in saas_api
    assert "plain_key" not in auth_store
    assert "JSON.stringify(safeSession)" in auth_store
    assert "initialAdminToken && initialUserSession" in auth_store
    assert "isAdminEntry" in auth_store
    assert "localStorage.removeItem('admin_token')" in auth_store
    assert "localStorage.removeItem('user_access_session')" in auth_store
    assert "注册框架" in login
    assert "登录方式" not in login
    assert "额度单位" not in login
    assert "扣费规则" not in login
    assert "v-if=\"mode === 'account'\"" in login
    assert "API Key" not in login


def test_router_validates_saved_user_session_before_entering_protected_pages():
    router = (SRC / "router" / "index.ts").read_text(encoding="utf-8")
    auth_store = (SRC / "stores" / "auth.ts").read_text(encoding="utf-8")
    app = (SRC / "App.vue").read_text(encoding="utf-8")

    assert "ensureUserSessionValid" in auth_store
    assert "isUserSessionExpired" in auth_store
    assert "sessionValidationCheckedAt" in auth_store
    assert "options: { force?: boolean } = {}" in auth_store
    assert "!options.force && Date.now() - sessionValidationCheckedAt.value < USER_SESSION_VALIDATION_TTL_MS" in auth_store
    assert "await auth.ensureUserSessionValid()" in router
    assert "to.meta.requiresAuth !== false || to.name === 'login'" in router
    assert router.index("await auth.ensureUserSessionValid()") < router.index("if (to.meta.requiresAuth !== false && !auth.isAuthenticated)")
    assert "clearUserSession()" in auth_store
    assert "SESSION_MONITOR_INTERVAL_MS = 30_000" in app
    assert "auth.ensureUserSessionValid({ force: true })" in app
    assert "window.addEventListener('focus', handleWindowFocus)" in app
    assert "document.addEventListener('visibilitychange', handleVisibilityChange)" in app
    assert "window.setInterval" in app
    assert "window.clearInterval(sessionMonitorTimer)" in app
    assert "router.replace('/login')" in app


def test_saved_user_session_transient_validation_error_does_not_force_logout():
    auth_store = (SRC / "stores" / "auth.ts").read_text(encoding="utf-8")
    http = (SRC / "api" / "http.ts").read_text(encoding="utf-8")

    assert "isDefinitiveUserSessionFailure" in auth_store
    assert "isTransientUserSessionValidationError" in auth_store
    assert "clearUserSession()\n          return false" not in auth_store
    catch_body = auth_store.split(".catch((error) => {", 1)[1].split("})", 1)[0]
    assert "if (isDefinitiveUserSessionFailure(error))" in catch_body
    assert "clearUserSession()" in catch_body
    assert "return false" in catch_body
    assert "if (isTransientUserSessionValidationError(error))" in catch_body
    assert "sessionValidationCheckedAt.value = Date.now()" in catch_body
    assert "return true" in catch_body
    assert "isUserSessionFailure(detail)" in http
    assert "isUserSessionFailure(detail) && auth.userSession" in http


def test_login_register_experience_has_copy_password_and_mobile_guards():
    login = (SRC / "views" / "LoginView.vue").read_text(encoding="utf-8")

    assert "copyIssuedAccessKey" in login
    assert "clipboardCopy" in login
    assert "data-testid=\"copy-issued-access-key\"" in login
    assert "复制使用密钥" in login
    assert "使用密钥已复制" in login
    assert "显示密码" in login
    assert "隐藏密码" in login
    assert "accountPasswordVisible" in login
    assert "registerPasswordVisible" in login
    assert "validateRegisterForm" in login
    assert "密码至少 6 位" in login
    assert "请填写邀请码" in login
    assert "邮箱格式不正确" in login
    assert "手机号格式不正确" in login
    assert "overflow-x-hidden" in login
    assert "break-all" in login


def test_global_toast_uses_bottom_center_overlay_and_project_name_guard():
    app = (SRC / "App.vue").read_text(encoding="utf-8")
    sonner = (SRC / "components" / "ui" / "sonner" / "Sonner.vue").read_text(encoding="utf-8")
    projects = (SRC / "views" / "ProjectsView.vue").read_text(encoding="utf-8")

    assert 'position="bottom-center"' in app
    assert ':duration="3000"' in app
    assert 'position="top-center"' not in app
    assert "z-index: 2147483647" in sonner
    assert "width: min(420px, calc(100vw - 32px))" in sonner
    assert "请先填写项目名称" in projects
    assert "`新项目 ${new Date().toLocaleDateString('zh-CN')}`" not in projects


def test_admin_console_has_llm_credit_logs_and_advanced_chain_sections():
    view_path = SRC / "views" / "MoxiAdminView.vue"
    assert view_path.exists()
    view = view_path.read_text(encoding="utf-8")

    assert "LLM接口配置" in view
    assert "用户密钥管理" in view
    assert "额度流水" in view
    assert "生成日志" in view
    assert "异常中心" in view
    assert "科研生成链路" in view
    assert "生成邀请码" in view
    assert "邀请码池" in view
    assert "注册用户管理" in view
    assert "创建注册用户" in view
    assert "生成默认用户" in view
    assert "注册用户列表" in view
    assert "实际成本 × 5" in view
    assert "activeSection" in view
    assert "生成密钥" in view
    assert "最近生成的密钥" in view
    assert "toggleAccessKeyStatus" in view
    assert "item.status === 'active' ? '禁用' : '启用'" in view
    assert "已登录用户会话会立即失效" in view
    assert "accessKeyDisplayValue" in view
    assert "完整密钥" in view
    assert "历史密钥无法还原完整值" in view
    assert "该密钥名下项目数据、独立用户库和已登录会话会一起清理" in view
    assert "密钥已禁用，已登录会话已失效" in view
    assert "密钥已删除，已登录会话已失效" in view
    assert "人话日志" in view
    assert "成本健康" in view
    assert "loadAdminData" in view
    assert "accessKeys" in view
    assert "llmProviders" in view
    assert "creditLedger" in view
    assert "generationLogs" in view
    assert "exceptionItems" in view
    assert "禁用" in view
    assert "保存配置" in view
    assert "createInviteCodes" in view
    assert "createFrontUser" in view
    assert "seedDefaultFrontUsers" in view
    assert "frontUsers" in view
    assert "filteredFrontUsers" in view
    assert "frontUserSearchKeyword" in view
    assert "frontUserStats" in view
    assert "statusBadgeClass" in view
    assert "adminDataFailures" in view
    assert "退出登录" in view
    assert "handleAdminLogout" in view
    assert "skillStatusLabel" in view
    assert "skillVerdictLabel" in view
    assert "skillBindingKeyLabel" in view
    assert "ledgerStatusLabel" in view
    assert "ledgerEventTypeLabel" in view
    assert "generationTypeLabel" in view
    assert "成功（已扣费/已入账）" in view
    assert "失败（未扣费）" in view
    assert "剧本片段生成" in view
    assert "格式错误" in view
    assert "待复核" in view
    assert "pending_review</option>" not in view
    assert "adminDataLastRefreshedAt" in view
    assert "capture('注册用户'" in view
    assert "切换后台板块" in view
    assert "套餐订阅框架" in view
    assert "保存/新增套餐" in view
    assert "套餐列表" in view
    assert "支付订单" in view
    assert "Skill封装" in view
    assert "允许复制/导出" in view
    assert "复制导出权限" in view
    assert "toggleCopyExportPermission" in view
    assert "Skill 数据库封装" in view
    assert "skillWorkflowApi" in view
    assert "loadSkillWorkflowData" in view
    assert "syncSkillCatalog" in view
    assert "createSkillBinding" in view
    assert "toggleSkillBinding" in view
    assert "archiveSkillBinding" in view
    assert "previewSkillRecommendation" in view
    assert "startSkillInvocation" in view
    assert "finishSkillInvocation" in view
    assert "createSkillArtifact" in view
    assert "runSkillWorker" in view
    assert "createSkillFeedback" in view
    assert "skillCatalog" in view
    assert "skillBindings" in view
    assert "skillInvocations" in view
    assert "skillArtifacts" in view
    assert "skillFeedback" in view
    assert "推荐预览" in view
    assert "内部编排 worker" in view
    assert "调用历史" in view
    assert "产物列表" in view
    assert "质量反馈列表" in view
    assert "capture('Skill封装'" in view
    assert "操作者审计" in view
    assert "operatorAuditLogs" in view
    assert "saveSubscriptionPlan" in view
    assert "listSubscriptionPlans" in view
    assert "seedDefaultSubscriptionPlans" in view
    assert "补齐默认套餐" in view
    assert "listPaymentOrders" in view
    assert "listOperatorAuditLogs" in view
    assert "input_cost_cny_per_1k" in view
    assert "output_cost_cny_per_1k" in view
    assert "billing_multiplier" in view
    assert "用户扣费 = 真实成本 × 扣费倍率" in view
    assert "refreshSelectedProviderModels" in view
    assert "selectedProviderModelOptions" in view
    assert "拉取模型" in view
    assert "每行一个模型；拉取失败时可手工补充" in view
    assert "isSelectedKimiProvider" not in view


def test_frontend_formats_user_access_errors():
    http = (SRC / "api" / "http.ts").read_text(encoding="utf-8")
    advanced_profiles = (
        SRC / "features" / "advanced-generation" / "composables" / "useAdvancedGenerationProfiles.ts"
    ).read_text(encoding="utf-8")

    assert "formatAccessErrorMessage" in http
    assert "status === 402" in http
    assert "额度不足" in http
    assert "isUserSessionFailure" in http
    assert "clearUserSession" in http
    assert "科研生成权限" in http
    assert "formatAccessErrorMessage(e)" in advanced_profiles


def test_user_side_keeps_single_visible_generation_entry_and_redirects_legacy_route():
    layout = (SRC / "views" / "AppLayout.vue").read_text(encoding="utf-8")
    router = (SRC / "router" / "index.ts").read_text(encoding="utf-8")
    lab_api = (SRC / "api" / "modules" / "lab.ts").read_text(encoding="utf-8")
    http = (SRC / "api" / "http.ts").read_text(encoding="utf-8")

    assert "advancedGenerationEnabled" not in layout
    assert "科研生成" not in layout
    assert "v-if=\"auth.advancedGenerationEnabled\"" not in layout
    assert "auth.isAdminAuthenticated" in layout
    assert "活动日志" in layout
    assert "requiresAdmin: true" in router
    assert "name: 'advanced-generation'" in router
    assert "redirect: '/projects',  // 前台只保留项目工作区正式科研生成链路" in router
    assert "to.meta.requiresAdmin" in router
    assert "to.meta.requiresAdvancedGeneration" in router
    assert "'/user/market/ai-topics'" in lab_api
    assert "'/admin/market/ai-topics'" not in lab_api
    assert "timeout: 30000" in http


def test_front_settings_no_longer_exposes_llm_api_configuration():
    settings = (SRC / "views" / "SettingsView.vue").read_text(encoding="utf-8")
    saas_api = (SRC / "api" / "modules" / "saasAdmin.ts").read_text(encoding="utf-8")

    assert "adminConfigApi" not in settings
    assert "aiProviders" not in settings
    assert "AI API 配置" not in settings
    assert "模型接口、系统密钥、充值管理统一放在后台" in settings
    assert "订阅套餐" in settings
    assert "模拟支付/订阅" in settings
    assert "用户订单列表" in settings
    assert "createSubscriptionOrder" in settings
    assert "listSubscriptionOrders" in settings
    assert "refreshUserSession" in settings
    assert "orderLoadError" in settings
    assert "checkout_mode: 'demo'" in settings
    assert "Promise.all([" not in settings
    assert "/user/subscription-plans" in saas_api
    assert "/user/subscription-orders" in saas_api
    assert "/moxi-admin/subscription-plans/seed-defaults" in saas_api
    assert "/moxi-admin/subscription-plans" in saas_api
    assert "/moxi-admin/payment-orders" in saas_api
    assert "/moxi-admin/operator-audit-logs" in saas_api
    assert "/moxi-admin/front-users" in saas_api
    assert "seedDefaultFrontUsers" in saas_api


def test_admin_launch_command_opens_admin_console():
    launch = ROOT.parent / "07-launch-tools" / "start-background.command"

    assert launch.exists()
    text = launch.read_text(encoding="utf-8")
    assert "/moxi-admin" in text
    assert "npm run build-only" in text
    assert "uvicorn app.main:app" in text
