from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "webui" / "src" / "api"
WEBUI_SRC_DIR = ROOT / "webui" / "src"


def read(relative: str) -> str:
    return (API_DIR / relative).read_text(encoding="utf-8")


def read_webui(relative: str) -> str:
    return (WEBUI_SRC_DIR / relative).read_text(encoding="utf-8")


def test_frontend_api_has_shared_http_clients_and_domain_modules():
    assert (API_DIR / "http.ts").exists()
    assert (API_DIR / "modules" / "collaboration.ts").exists()
    assert (API_DIR / "modules" / "cache.ts").exists()
    assert (API_DIR / "modules" / "legacy.ts").exists()
    assert (API_DIR / "modules" / "projects.ts").exists()
    assert (API_DIR / "modules" / "search.ts").exists()
    assert (API_DIR / "modules" / "settings.ts").exists()
    assert (API_DIR / "modules" / "skillWorkflows.ts").exists()
    assert (API_DIR / "modules" / "visual.ts").exists()


def test_legacy_client_reexports_split_domain_modules():
    client = read("client.ts")

    assert "export * from './modules/collaboration'" in client
    assert "export * from './modules/cache'" in client
    assert "export * from './modules/projects'" in client
    assert "export * from './modules/settings'" in client
    assert "export * from './modules/search'" in client
    assert "export * from './modules/skillWorkflows'" in client
    assert "export * from './modules/visual'" in client
    assert "export * from './modules/legacy'" in client
    assert len(client.splitlines()) <= 20
    assert "export const projectsV2Api" not in client
    assert "export const adminConfigApi" not in client
    assert "export const storyboardApi" not in client
    assert "export const phase2Api" not in client


def test_skill_workflow_module_exposes_admin_contract():
    skill_workflows = read("modules/skillWorkflows.ts")

    assert "skillWorkflowApi" in skill_workflows
    assert "SkillCatalogItem" in skill_workflows
    assert "SkillBindingItem" in skill_workflows
    assert "SkillInvocationItem" in skill_workflows
    assert "SkillArtifactItem" in skill_workflows
    assert "SkillQualityFeedbackItem" in skill_workflows
    assert "SkillQualityFeedbackSummaryResponse" in skill_workflows
    assert "SkillExternalRunnerResponse" in skill_workflows
    assert "SkillExternalRunnerExecutionResponse" in skill_workflows
    assert "'/admin/skill-workflows/catalog'" in skill_workflows
    assert "'/admin/skill-workflows/sync'" in skill_workflows
    assert "'/admin/skill-workflows/recommend'" in skill_workflows
    assert "'/admin/skill-workflows/worker/run'" in skill_workflows
    assert "'/admin/skill-workflows/runner/prepare'" in skill_workflows
    assert "'/admin/skill-workflows/runner/execute'" in skill_workflows
    assert "'/admin/skill-workflows/bindings'" in skill_workflows
    assert "'/admin/skill-workflows/invocations'" in skill_workflows
    assert "'/admin/skill-workflows/artifacts'" in skill_workflows
    assert "'/admin/skill-workflows/quality-feedback'" in skill_workflows
    assert "'/admin/skill-workflows/quality-feedback/summary'" in skill_workflows
    assert "createBinding" in skill_workflows
    assert "updateBinding" in skill_workflows
    assert "startInvocation" in skill_workflows
    assert "finishInvocation" in skill_workflows
    assert "createArtifact" in skill_workflows
    assert "createQualityFeedback" in skill_workflows
    assert "listQualityFeedback" in skill_workflows
    assert "qualityFeedbackSummary" in skill_workflows
    assert "runWorker" in skill_workflows
    assert "prepareRunner" in skill_workflows
    assert "executeRunner" in skill_workflows


def test_legacy_module_is_split_into_domain_files():
    """legacy.ts 已二次按域拆分为 shortDrama / admin / lab / learning。"""
    legacy = read("modules/legacy.ts")

    assert len(legacy.splitlines()) <= 15
    assert "export * from './shortDrama'" in legacy
    assert "export * from './admin'" in legacy
    assert "export * from './lab'" in legacy
    assert "export * from './learning'" in legacy

    for fname in ("shortDrama.ts", "admin.ts", "lab.ts", "learning.ts"):
        assert (API_DIR / "modules" / fname).exists(), f"missing {fname}"


def test_script_generation_user_status_hides_internal_retry_details():
    """用户端只看合并生成状态；内部失败、步骤和重试次数只能写后台日志。"""
    generation = read_webui("features/workspace/composables/useScriptDraftGeneration.ts")
    status_panel = read_webui("views/workspace/tabs/ScriptSceneStatusPanel.vue")
    workspace = read_webui("views/ProjectWorkspaceView.vue")

    assert "PUBLIC_PROGRESS_GENERATING = '正在生成本集，请稍候…'" in generation
    assert "PUBLIC_PROGRESS_RECOVERING = '正在整理正文，请稍候…'" in generation
    assert "SCRIPT_DRAFT_EPISODE_TARGET_MS = 300_000" in generation
    assert "SCRIPT_DRAFT_STREAM_TIMEOUT_MS = 600_000" in generation
    assert "SINGLE_EPISODE_WAIT_BUDGET" in generation
    assert "public_detail" in generation
    assert "public_suggestion" in generation
    assert "public_detail" in workspace
    assert "public_suggestion" in workspace
    assert "props.latestScriptGenerationFailureLog.public_detail || props.latestScriptGenerationFailureLog.detail" not in status_panel
    assert "props.latestScriptGenerationFailureLog.public_suggestion || props.latestScriptGenerationFailureLog.suggestion" not in status_panel
    assert "后台生成记录" not in status_panel
    assert "用户改稿接续记录" not in status_panel
    assert "生成失败记录" not in status_panel
    assert "模型链路记录" not in status_panel
    assert "formatProvider(item.provider)" not in status_panel
    assert "item.model || '未记录型号'" not in status_panel

    forbidden_user_status_fragments = [
        "第${attempt}次生成中",
        "第${attempt}次生成失败",
        "正在自动重试第${attempt + 1}次",
        "生成失败：${detail}",
        "生成失败：${info.display}",
        "AI 生成失败：${info.display}",
    ]
    for fragment in forbidden_user_status_fragments:
        assert fragment not in generation


def test_script_generation_accepts_review_required_candidate_without_auto_saving():
    generation = read_webui("features/workspace/composables/useScriptDraftGeneration.ts")
    step_panel = read_webui("views/workspace/tabs/ScriptStepConfirmationPanel.vue")
    workspace = read_webui("views/ProjectWorkspaceView.vue")

    assert "candidate_review_required" in generation
    assert "status.status === 'candidate_review_required'" in generation
    assert "recordCandidateSnapshot" in generation
    assert "candidate_needs_user_confirmation" in generation
    assert "候选内容尚未自动保存" in generation
    assert "workflow_steps" in generation
    assert "scriptWorkflowSteps" in generation
    assert "scriptWorkflowSteps" in workspace
    assert "isCurrentPendingModelCandidate" in workspace
    assert "pending_confirmation" in workspace
    assert "workflowSteps" in step_panel
    assert "AI候选待确认" in read_webui("views/workspace/tabs/ScriptEditorPanel.vue")
    assert "前提资料" in step_panel
    assert "本集导演蓝图" in step_panel
    assert "四段任务卡" in step_panel
    assert "正文候选" in step_panel
    assert "正文候选与保存" in step_panel
    assert "DeepSeek" not in step_panel
    assert "Kimi" not in step_panel
    assert "DeepSeek" not in workspace
    assert "Kimi" not in workspace


def test_outline_commit_uses_current_dirty_state_and_persists_characters():
    workspace = read_webui("views/ProjectWorkspaceView.vue")
    projects_api = read("modules/projects.ts")

    assert "function _outlineCurrentDraftDiffersFromMainChain" in workspace
    assert "if (_outlineCurrentDraftDiffersFromMainChain()) return true" in workspace
    assert "async function persistWorkspaceCharacters" in workspace
    commit_body = workspace.split("async function commitOutlineToMainChain", 1)[1].split("async function saveOutlineAndContinue", 1)[0]
    assert "const charactersPersisted = await persistWorkspaceCharacters" in commit_body
    assert "角色设计保存失败" in commit_body
    assert "lastWorkflowContextSyncError" in workspace
    assert "notifyApiError(toast.error, lastWorkflowContextSyncError.value" in workspace
    assert "saveWorkflowContext: (projectId: string, data:" in projects_api
    assert "config?: AxiosRequestConfig" in projects_api
    assert "timeout: 120000" in projects_api


def test_create_episodes_batch_refreshes_backend_state_and_tolerates_existing_episodes():
    workspace = read_webui("views/ProjectWorkspaceView.vue")
    body = workspace.split("async function createEpisodesBatch", 1)[1].split("async function saveEpisodeFromSidebar", 1)[0]

    assert body.index("await loadEpisodes()") < body.index("const existingNumbers = new Set")
    assert "if (!_isEpisodeAlreadyExistsError(e)) throw e" in body


def test_legacy_split_domain_modules_keep_their_apis():
    """守住每个新模块各自负责的 API 名称。"""
    short_drama = read("modules/shortDrama.ts")
    advanced_generation = read("modules/advancedGeneration.ts")
    collaboration = read("modules/collaboration.ts")
    cache = read("modules/cache.ts")
    admin = read("modules/admin.ts")
    settings = read("modules/settings.ts")
    lab = read("modules/lab.ts")
    learning = read("modules/learning.ts")

    assert "shortDramaStudioApi" in short_drama
    assert "advancedGenerationApi" in short_drama
    assert "getPlan" in advanced_generation
    assert "getOrchestrationStatus" in advanced_generation
    assert "getOrchestrationPlan" in advanced_generation
    assert "AdvancedGenerationOrchestrationPlanResponse" in advanced_generation
    assert "collaborationApi" in collaboration
    assert "yjsStatus" in collaboration
    assert "'/collaboration/yjs/status'" in collaboration
    assert "yjsPlan" in collaboration
    assert "'/collaboration/yjs/plan'" in collaboration
    assert "cacheApi" in cache
    assert "status" in cache
    assert "clear" in cache
    assert "CacheStatusResponse" in cache
    assert "backend: string" in cache
    assert "redis_configured: boolean" in cache
    assert "redis_available: boolean" in cache
    assert "redis_error: string" in cache
    assert "memory_keys: number" in cache
    assert "degraded: boolean" in cache
    assert "dashboard_ttl_seconds: number" in cache
    assert "'/admin/cache/status'" in cache
    assert "'/admin/cache/clear'" in cache
    assert "advanced_generation_mode?: boolean" in settings
    assert "stepVersionApi" in short_drama
    assert "episodeSegmentApi" in short_drama

    assert "adminApi" in admin
    assert "adminAgentApi" in admin
    assert "adminTaskApi" in admin
    assert "adminDashboardApi" in admin
    assert "adminScoreApi" in admin
    assert "adminReviewApi" in admin
    assert "adminLogApi" in admin
    assert "AdminPageResponse" in admin

    assert "feedApi" in lab
    assert "marketApi" in lab
    assert "promptsApi" in lab
    assert "setupApi" in lab

    assert "autoFixApi" in learning
    assert "projectLearningApi" in learning
    assert "lightweightLearningApi" in learning


def test_legacy_split_modules_do_not_cross_pollute():
    """避免 API 既出现在 admin 又出现在 lab 这种重复 export。"""
    admin = read("modules/admin.ts")
    lab = read("modules/lab.ts")
    learning = read("modules/learning.ts")
    short_drama = read("modules/shortDrama.ts")

    assert "shortDramaStudioApi" not in admin
    assert "marketApi" not in admin
    assert "autoFixApi" not in admin
    assert "adminScoreApi" not in lab
    assert "adminScoreApi" not in learning
    assert "adminScoreApi" not in short_drama


def test_search_module_exposes_semantic_search_contract():
    search = read("modules/search.ts")

    assert "semantic_degraded?: boolean" in search
    assert "semantic_error?: string" in search
    assert "semanticSearch" in search
    assert "'/search/semantic'" in search
    assert "semanticStatus" in search
    assert "'/search/semantic/status'" in search
    assert "rebuildSemantic" in search
    assert "'/search/semantic/rebuild'" in search


def test_workspace_has_tabs_and_ai_assistant_composables():
    workspace_dir = ROOT / "webui" / "src" / "features" / "workspace" / "composables"
    view = (ROOT / "webui" / "src" / "views" / "ProjectWorkspaceView.vue").read_text(encoding="utf-8")

    assert (workspace_dir / "useWorkspaceTabs.ts").exists()
    assert (workspace_dir / "useAiAssistant.ts").exists()
    assert (workspace_dir / "useStorySimulation.ts").exists()
    assert (workspace_dir / "useOutlineGate.ts").exists()
    assert (workspace_dir / "useOutlineWorkflow.ts").exists()
    assert (workspace_dir / "useProjectExport.ts").exists()
    assert (workspace_dir / "useSegmentedWriting.ts").exists()
    assert (workspace_dir / "useRuleBackedScriptStream.ts").exists()
    assert (workspace_dir / "useScriptDraftGeneration.ts").exists()
    segmented = (workspace_dir / "useSegmentedWriting.ts").read_text(encoding="utf-8")
    stream = (workspace_dir / "useRuleBackedScriptStream.ts").read_text(encoding="utf-8")
    draft = (workspace_dir / "useScriptDraftGeneration.ts").read_text(encoding="utf-8")
    status_panel = (ROOT / "webui" / "src" / "views" / "workspace" / "tabs" / "ScriptSceneStatusPanel.vue").read_text(encoding="utf-8")
    assert "useWorkspaceTabs" in view
    assert "useAiAssistant" in view
    assert "useOutlineWorkflow" in view
    assert "useOutlineGate" in view
    assert "useProjectExport" in view
    assert "useSegmentedWriting" in view
    assert "streamRuleBackedScript" in stream
    assert "streamRuleBackedScript" not in view
    assert "async function _runRuleBackedScriptJob" in view
    assert "adminConfigApi.startRuleBackedScriptJob(requestPayload)" in view
    assert "adminConfigApi.getRuleBackedScriptJobStatus(jobId)" in view
    assert "useScriptDraftGeneration" in view
    assert "generateScript" in draft
    assert "stopGeneratingScript" in draft
    assert "SCRIPT_DRAFT_STREAM_TIMEOUT_MS" in draft
    assert "streamScript:" not in draft
    assert "streamScript:" not in view
    assert "startScriptJob" in draft
    assert "getScriptJobStatus" in draft
    assert "pollScriptJobUntilReady" in draft
    assert "script-scene/jobs/start" in (ROOT / "webui" / "src" / "api" / "modules" / "settings.ts").read_text(encoding="utf-8")
    assert "script-scene/jobs/status" in (ROOT / "webui" / "src" / "api" / "modules" / "settings.ts").read_text(encoding="utf-8")
    assert "script-scene/jobs/latest" in (ROOT / "webui" / "src" / "api" / "modules" / "settings.ts").read_text(encoding="utf-8")
    assert "生成超过10分钟仍未返回正文" in draft
    assert "生成超过4分钟仍未返回正文" not in draft
    assert "EMPTY_SCRIPT_DRAFT" in draft
    assert "模型生成链路结束但没有返回可保存正文" in draft
    assert "recordGenerationFailure" in draft
    assert "display: info.display" in draft
    assert "public_detail: PUBLIC_BLOCKED_DETAIL" in draft
    assert "PUBLIC_CANDIDATE_DETAIL" in draft
    assert "候选内容尚未自动保存" in draft
    assert "script_generation_failure_log" in view
    assert "latestScriptGenerationFailureLog" in view
    assert "isScriptStreamFailure" in status_panel
    assert "生成失败记录" not in status_panel
    assert "latestScriptGenerationFailureLog" not in status_panel
    assert "whitespace-pre-line" in status_panel
    assert "border-red-200" in status_panel
    assert "scriptStreamStatus.value = ''" in draft
    assert "signal?: AbortSignal" in stream
    assert "activeController.abort()" in draft
    assert "current_job_id: jobId" in draft
    assert "overflow_content?: string" in draft
    assert "适合顺延到下一集" in draft
    assert "overflow_content: string" in stream
    assert "overflow_content: overflowContent" in stream
    assert "@stop-generating-script=\"stopGeneratingScript\"" in view
    assert "onBeforeRouteLeave" in view
    assert "beforeunload" in view
    assert "hasUnsavedSceneChanges" in view
    assert "changeNote: '切换页面前自动保存'" in view
    assert "changeNote: '切场前自动保存'" in view
    assert "async function selectScriptScene" in view
    assert '@select-scene="selectScriptScene"' in view
    assert "void _autoSaveCurrentScene(); selectedScene" not in view
    assert "changeNote: '切集前自动保存',\n    editorType: 'human'" in view
    assert "changeNote: '进入下一集前保存',\n      editorType: 'human'" in view
    assert "const snapshotPersisted = await _persistOutlineSnapshot" in view
    assert "大纲主链同步失败" in view
    assert "confirmedSegmentContent" in segmented
    assert "resetSegmentsFrom" in segmented
    assert "desc: '第2场推进'" not in segmented
    assert "desc: '承接推进'" in segmented
    assert "segmentSwitchVersion" in segmented
    assert "segmentEnterEdit" in segmented
    assert "segmentExitEdit" in segmented

    assert "applyAiReplacement" in segmented
    assert "replaceStepWithRevisedContent" in segmented
    assert "segmentApplyPatch" in segmented
    assert "buildSegmentRepairInstruction" in segmented
    assert "generateOneSegment" in segmented
    assert "showSegmentPanel.value = true" in segmented
    assert "Promise.allSettled" not in segmented, "分段精写默认只生成 A 版，B 版必须用户按需触发"
    assert "segmentGenerateVariant" in segmented
    assert "variant_instruction" in segmented
    assert "composeSegmentDraftContent" in segmented
    assert "showSegmentPanel.value = false" in segmented
    assert "setTimeout(() => { showSegmentPanel.value = false }" not in segmented
    assert "attemptLocalizedSegmentRepair" in segmented
    assert "handleSegmentApprovalFailure" in segmented
    assert "segmentConfirm" in segmented
    assert "serializeSegmentProgress" in segmented
    assert "hydrateSegmentProgress" in segmented
    assert "onSegmentDraftReady" in segmented
    assert "if (shouldDeepAudit)" in segmented
    assert "await options.approveFullScript(true)" in segmented
    assert "await options.approveFullScript(shouldDeepAudit)" not in segmented, "未完成整集时不应整体验收，否则会把第二段后的半成品打回第一段"
    assert "整集深审仍有风险，已保留你确认的分段并保存为待复核稿，不自动覆盖重写。" in segmented
    assert "if (!scriptApproved) {\n        await handleSegmentApprovalFailure(idx)" not in segmented
    assert "markSegmentConfirmedForNextRequest" in segmented
    assert "hasUnconfirmedPriorSegment(idx)" in segmented
    assert "上一段还未确认，不能生成下一段" in segmented
    assert segmented.index("markSegmentConfirmedForNextRequest(idx)") < segmented.index("await options.afterSegmentConfirmed?.(shouldDeepAudit)")
    assert segmented.index("markSegmentConfirmedForNextRequest(idx)") < segmented.index("await generateOneSegment(idx + 1)")
    assert "allowAutomaticSegmentPatch?: boolean" in segmented
    assert "if (repairScope === 'patchable' && options?.allowAutomaticSegmentPatch)" in segmented
    assert "const maxAutomaticRepairAttempts = 2" in segmented
    assert "if (step.repairAttempts >= maxAutomaticRepairAttempts)" in segmented
    assert "const failedRepairAttempts = step.repairAttempts + 1" in segmented
    assert "regeneratedStep.repairAttempts = failedRepairAttempts" in segmented
    assert "generateSegmented" in segmented
    assert "segmentRetry" in segmented
    assert "resumeSegmentedProgress" in segmented
    assert "正在等待确认，确认后会继续下一段" in segmented
    assert "hasSegmentProgress()" in segmented
    assert "ensureOutlineGatePassed" in view
    assert "const outlineData = ref" not in view
    assert "const projectRules = ref" not in view
    assert "const SEGMENT_DEFS =" not in view
    assert "async function _streamRuleBackedScript" not in view
    assert "async function _generateOneSegment" not in view
    assert "async function _attemptLocalizedSegmentRepair" not in view
    assert "async function _handleSegmentApprovalFailure" not in view
    assert "async function segmentConfirm" not in view
    assert "async function segmentRetry" not in view
    assert "async function generateSegmented" not in view
    assert "async function generateScript" not in view
    assert "function segmentSwitchVersion" not in view
    assert "function segmentEnterEdit" not in view
    assert "function segmentExitEdit" not in view
    assert "async function segmentApplyPatch" not in view
    assert "async function exportProject" not in view
    assert "async function generateStoryboard" not in view
    assert "async function copyStoryboardContent" not in view
    assert "const tabs = [" not in view
    assert "const quickPrompts = computed" not in view


def test_project_export_reads_all_saved_scenes():
    workspace_dir = ROOT / "webui" / "src" / "features" / "workspace" / "composables"
    export = (workspace_dir / "useProjectExport.ts").read_text(encoding="utf-8")

    assert "projectsV2Api.listEpisodes" in export
    assert "projectsV2Api.listScenesBatch" in export
    assert "剧本正文（全部已保存场景）" in export
    assert "current_scene" in export


def test_project_export_blocks_without_real_saved_script_content():
    workspace_dir = ROOT / "webui" / "src" / "features" / "workspace" / "composables"
    export = (workspace_dir / "useProjectExport.ts").read_text(encoding="utf-8")

    assert "function assertExportHasScriptContent" in export
    assert "导出失败：还没有可导出的剧本正文" in export
    export_body = export.split("async function exportProject", 1)[1].split("if (format === 'txt')", 1)[0]
    assert "if (!assertExportHasScriptContent(scriptEpisodes)) return" in export_body


def test_export_tab_completion_uses_readiness_items_not_completed_tabs():
    export_tab = read_webui("views/workspace/tabs/ExportTab.vue")

    assert "type ExportReadinessItem" in export_tab
    assert "readinessItems: ExportReadinessItem[]" in export_tab
    check_body = export_tab.split("完成度检查", 1)[1].split("grid grid-cols-2", 1)[0]
    assert "v-for=\"item in readinessItems\"" in check_body
    assert "completedTabs.has" not in check_body
