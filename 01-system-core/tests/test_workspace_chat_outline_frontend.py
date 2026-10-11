from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_local_outline_parser_accepts_inline_character_lists():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()

    assert "function _extractLocalInlineCharacterListRows" in source
    assert "inlineCharacterRe" in source
    assert "_extractLocalInlineCharacterListRows(byName, scanText)" in source
    assert "'豪族'" in source


def _legacy_chat_brainstorm_generated_structured_outline_contract():
    source = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()
    chat_tab_source = (ROOT / "webui/src/views/workspace/tabs/ChatTab.vue").read_text()
    saas_api_source = (ROOT / "webui/src/api/modules/saasAdmin.ts").read_text()
    backend_source = (ROOT / "app/routers/admin_config.py").read_text()

    assert "userAccessApi.aiChat" in source
    assert "system_prompt" in source
    assert "STAGE_CONFIRMATION_PACKET_RULES" in source
    assert "当前“聊天脑暴”窗口的第一职责是帮助用户选题" in source
    assert "选题确认 → 一句话梗概 → 角色库 → 人物小传 → 总集数判断 → 范围集纲 → 分集集纲" in source
    assert "outline_structuring" in source
    assert "targetEpisodeCount" in source
    assert "_inferEpisodeTargetFromMessages" in source
    assert "_userExplicitEpisodeCount" in source
    assert "_complexityEpisodeTarget" not in source
    assert "_pickArrayValue" in source
    assert "_deriveEpisodesFromRanges" in source
    assert "_classifyOutlineInputForGeneration" in source
    assert "_buildFallbackStandardOutlinePacket(lastUserInput, targetEpisodeCount)" in source
    assert "outlineInputTier === 'S1'" in source
    assert "已保存候选资料包，请确认或补充关键内容" in source
    assert "TECHNICAL_TEST_INPUT_RE" in source
    assert "_isTechnicalTestOnlyInput" in source
    assert source.index("_isTechnicalTestOnlyInput(normalized)") < source.index("const hasEpisodeOutline")
    assert "你可以直接按这 5 点简单回答" not in source
    assert "请逐步确认标准大纲资料包" in source
    assert "_cleanOutlineText" in source
    assert "聊天脑暴原始记录（整理依据）" not in source
    assert "episodes 必须生成完整" not in source
    assert "不得只输出样例" not in source
    assert "完整大纲输入" in source
    assert "reverse_confirmation" in source
    assert "relationship_table" in source
    assert "_normalizeRelationshipDraft" in source
    assert "_attachRelationshipRowsToCharacters" in source
    assert "人物关系 / 关系设计" in source
    assert "CHAT_INSPIRATION_TOPICS" in source
    assert "短句灵感实验室的轻量趋势反馈" in source
    assert "_callUserAiChatWithRetry" in source
    assert "_isTransientAiChatError" in source
    assert "generation_failed" in source
    assert "外部 AI 暂时不可用，我先用短句灵感实验室本地反馈继续推进" not in source
    assert "不要加载完整剧本规则包" in source
    assert "_buildConfirmedBrainstormContext" in source
    assert "_buildCompletedStageContext" in source
    assert "不要让用户重复确认这些阶段" in source
    assert "_buildChatBrainstormSystemPrompt(msg)" in source
    assert "_isOpenTopicDiscoveryInput" in source
    assert "shouldResetExploratoryHistory" not in source
    assert "chatMessages.value.slice(-1)" not in source
    assert "不知道写什么" in source
    assert "短剧思路" in source
    assert "先问用户偏真人短剧还是漫剧" in source
    assert "_shouldAskFormatBeforeTopic" in source
    assert "_applyExplicitFormatChoice" in source
    assert "await sendChatMessage(prompt)" in source
    assert "normalizeChatBrainstormState" in source
    assert "mergeChatBrainstormState" in source
    assert "previous?.role === message.role && previous.content.trim() === message.content.trim()" not in source
    assert "_appendChatMessage" in source
    assert "chat_brainstorm" in source
    assert "hydrateChatBrainstormState" in source
    assert "outlineLoading" in source
    assert "const rawMessage = content" in source
    assert "const msg = rawMessage.trim()" in source
    assert "const currentUserMessage = _appendChatMessage({ role: 'user', content: rawMessage })" in source
    assert "buildCurrentChatRequestSnapshot(chatMessages.value, currentUserMessage)" in source
    assert "currentMessageId: currentUserMessage.id" in source
    assert "const currentMessage = chatMessages.value[chatMessages.value.length - 1]" not in source
    assert "当前已确认设定，最高优先级" in source
    assert "后加入的身份、人物关系、剧情细节优先级最高" in source
    assert "大纲逻辑框架规则" in source
    assert "CHAT_OUTLINE_FRAMEWORK_RULES" in source
    assert "总纲 → 范围集纲 → 单集集纲" in source
    assert "单集集纲只写本集具体事件" in source
    assert "尾钩、hook、cliffhanger 不作为大纲框架字段输出" in source
    assert "_chooseLoglineCandidate" in source
    assert "_loglineSpecificityScore" in source
    assert "不得退回早期没有人物身份的泛化梗概" in source
    assert "可选处理方案" in source
    assert "给你几组方案" in source
    assert "你想做**真人短剧**还是**漫剧**" in source
    assert "range_outlines" in source
    assert "episode_outlines" in source
    assert "分集集纲" in source
    assert "age、gender、role、identity、occupation" in source
    assert "start_state、episode_outline、end_state、next_hook" in source
    assert "只能收录会行动、会说话、会承担关系变化的人物" in source
    assert "用户确认总集数" in source
    assert "Dify 知识库大纲写作规则" in source
    assert "CHAT_OUTLINE_DELIVERY_RULES" in source
    assert "episode_count_reason" in source
    assert "用户明确写了集数时按用户集数归一到 30-60" not in source
    assert "不得输出 24、26" not in source
    assert "opts.outlineData.value.episode_count = targetEpisodeCount" not in source
    assert "modelPayloadToCandidatePacket" in source
    assert "mergeOutlineCandidatePackets" in source
    assert "standard_outline_packet" in source
    assert "createStandardOutlinePacket" in source
    assert "mergeStandardOutlinePacket" in source
    assert "renderAssistantMessage" in chat_tab_source
    assert "messageEnd" in chat_tab_source
    assert "props.outlineLoading" in chat_tab_source
    assert "帮我评估这个选题" in chat_tab_source
    assert "给我三个可做选题方向" in chat_tab_source
    assert "进入大纲资料包确认" in chat_tab_source
    assert "当前“聊天脑暴”窗口主要用于选题" in backend_source
    assert "选题反馈必须覆盖" in backend_source
    assert "给我一个短剧思路/剧本思路/故事想法" in backend_source
    assert "先问是真人短剧还是漫剧" in backend_source
    assert "只参考灵感实验室级别的题材、热词和灵感元素" in backend_source
    assert "禁止在选题阶段加载完整规则包" in backend_source
    assert "用户要求“最终版/定稿/改写一句话梗概/加入身份信息”" in backend_source
    assert "后加入的身份、人物关系和剧情细节优先级最高" in backend_source
    assert "【大纲逻辑框架规则】" in backend_source
    assert "_is_outline_framework_request" in backend_source
    assert "and _is_outline_framework_request(latest_user_text)" in backend_source
    assert "用户明确要做大纲框架创作时" in backend_source
    assert "总纲 → 范围集纲 → 单集集纲" in backend_source
    assert "角色必须从大纲派生" in backend_source
    assert "最多只问 1 个必要确认点" in backend_source
    assert '"max_tokens_cap": 900' in backend_source
    assert '"max_tokens_cap": 4096' in backend_source
    assert "chat_context_packet" in backend_source
    assert "buildChatContextPacket" in source
    assert ".slice(-80)" not in source
    assert "CHAT_CONTEXT_MAX_CHARS" in source
    assert "function buildOutlineCandidateSource" in source
    assert "buildBoundedConversationSource" in source
    assert "reconcileSavedChatBrainstormState" in source
    assert "shouldApplyReconciledChatState" in source
    assert """if (shouldApplyReconciledChatState(_currentChatBrainstormState(), reconciled, projectId)) {
        _applyChatBrainstormState(reconciled)
      }""" in source
    assert """watch(chatMessages, () => {
    if (_chatSyncTimer) clearTimeout(_chatSyncTimer)
    _chatSyncTimer = setTimeout(() => {
      void _saveChatBrainstormState(false)""" in source
    assert "createSequentialSaveCoordinator" in source
    assert "createChatSendLock" in source
    assert "const chatSendLock = createChatSendLock()" in source
    assert "if (!chatSendLock.tryAcquire()) return false" in source
    assert "return sendChatMessage(rawMessage, true).finally(() => chatSendLock.release())" in source
    assert "const conversation = chatMessages.value" not in source
    assert "_buildChatTranscriptText" not in source
    assert "countContextChars(prompt) > CHAT_CONTEXT_MAX_CHARS" in source
    assert "_chat_generation_budget" in backend_source
    assert '"timeout_seconds": 30' in backend_source
    assert "分集集纲也必须覆盖目标总集数" in backend_source
    assert "_CHAT_OUTLINE_DELIVERY_RULES" in backend_source
    assert "Dify 知识库大纲交付结构" in backend_source
    assert "集数预测必须尊重用户明确确认的总集数" in backend_source
    assert "如果用户已确认某个阶段" in backend_source
    assert "timeout: 90000" in saas_api_source
    assert "include_dialogue=context_key not in" in backend_source
    assert "不要一上来让用户先定" in backend_source
    assert "判断总集数和范围集纲" not in chat_tab_source
    assert "outlineCharacters" in source
    assert "opts.outlineData.value.episodes" not in source
    assert "onOutlineGenerated" in source
    assert "JSON.parse" in source
    assert "最后一条用户输入作 logline" not in source
    assert "你想先展开哪个方向" not in source
    assert "用户不是填写者，用户是决策者" in source
    assert "AI 先给建议方向" in source
    assert "标准大纲资料包" in chat_tab_source
    assert "用户只需要选择、修改、确认" in chat_tab_source


def test_workspace_chat_and_outline_are_project_persisted():
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    chat_source = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()
    storage_source = (ROOT / "webui/src/features/workspace/utils/workspaceStorage.ts").read_text()
    workflow_source = (ROOT / "webui/src/features/workspace/utils/workflowState.ts").read_text()
    backend_helpers = (ROOT / "app/routers/projects/_helpers.py").read_text()
    store_route = (ROOT / "app/routers/projects/routes_stores.py").read_text()

    assert "projectsV2Api.saveWorkflowContext" in chat_source
    assert "saveWorkspaceStorage('chatBrainstorm'" in chat_source
    assert "loadWorkspaceStorage('chatBrainstorm'" in chat_source
    assert "workspaceActorScope" in storage_source
    assert "user_access_session" in storage_source
    assert "admin_token" in storage_source
    assert "simpleHash(adminToken)" in storage_source
    assert "legacyWorkspaceStorageKey" in storage_source
    assert "workspace_${projectId}_completed" in storage_source
    assert "export function saveWorkspaceStorage(bucket: string, projectId: string, value: string): boolean" in storage_source
    assert "loadWorkspaceStorage('outline'" in workspace
    assert "saveWorkspaceStorage('outline'" in workspace
    assert "async ({ rawOutlineText: generatedRawOutlineText, standardOutlinePacket: generatedStandardOutlinePacket })" in workspace
    assert "standard_outline_packet" in workspace
    assert "await _persistOutlineDraft('chat_brainstorm_outline_draft'" in workspace
    assert "_markOutlineAiGenerated('episodes')" in workspace
    assert "hydrateChatBrainstormState(workflowStore.data.workflow_context?.chat_brainstorm)" in workspace
    assert "bootstrapQueryPromptFromRoute" in workspace
    assert "delete nextQuery.prompt" in workspace
    assert "await bootstrapQueryPromptFromRoute()" in workspace
    assert "promptFromQuery" not in workspace
    assert "_persistOutlineSnapshot" in workspace
    assert "_hydrateOutlineStateFromWorkflow" in workspace
    assert "_sanitizeLocalCharacterInfo" in workspace
    assert "_sanitizeOutlineCharacters" in workspace
    assert "_sanitizeWorkspaceCharacterRows" in workspace
    assert "旁观|被动|解释" in workspace
    assert "真正|目标" in workspace
    assert "OUTLINE_CHARACTER_INFO_STOP_RE" in workspace
    assert "_isOutlineScaffoldValue" in workspace
    assert "核心冲突(?:/爽点)?" in workspace
    assert "主场景|关系变化|信息揭露|爽点类型" in workspace
    assert "我已有大纲文件" in workspace
    assert "故事概括" in workspace
    assert "outline_state" in workflow_source
    assert "chat_brainstorm" in workflow_source
    assert "\"outline_state\": {}" in backend_helpers
    assert "\"chat_brainstorm\": {}" in backend_helpers
    assert "def _normalize_workflow_context_patch" in backend_helpers
    assert "_normalize_workflow_context_patch(req.workflow_context)" in store_route


def test_chat_tab_preserves_multiline_ime_input_and_context_visibility_contract():
    chat_tab_source = (ROOT / "webui/src/views/workspace/tabs/ChatTab.vue").read_text()
    chat_tab_template = chat_tab_source.split("<template>", 1)[1]
    workspace_source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    chat_source = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()

    assert "<textarea" in chat_tab_source
    assert "compositionstart" in chat_tab_source
    assert "compositionend" in chat_tab_source
    assert "event.isComposing" in chat_tab_source
    assert "event.shiftKey" in chat_tab_source
    assert "maxlength=" not in chat_tab_source
    assert "import { Input }" not in chat_tab_source
    assert "submitChat: (content: string) => Promise<boolean>" in chat_tab_source
    assert "const content = input.value" in chat_tab_source
    assert "if (!content.trim()) return" in chat_tab_source
    assert "const accepted = await submitChatOnce(content)" in chat_tab_source
    assert "if (!accepted) return" in chat_tab_source
    assert "if (input.value === content) input.value = ''" in chat_tab_source
    assert "const isSubmitting = ref(false)" in chat_tab_source
    assert "async function submitChatOnce(content: string): Promise<boolean>" in chat_tab_source
    assert "if (isSubmitting.value || props.loading || props.referenceLoading) return false" in chat_tab_source
    assert "isSubmitting.value = true" in chat_tab_source
    assert "isSubmitting.value = false" in chat_tab_source
    assert "return await props.submitChat(content)" in chat_tab_source
    assert ":disabled=\"props.loading || props.referenceLoading || isSubmitting || !input.trim()\"" in chat_tab_source
    assert "async function sendSuggestion(content: string) {\n  await submitChatOnce(content)" in chat_tab_source
    assert ":disabled=\"props.loading || props.referenceLoading || isSubmitting\"" in chat_tab_source
    assert "props.outlineLoading" not in chat_tab_source
    assert ":key=\"msg.id\"" in chat_tab_source
    assert "CHAT_VISIBLE_INITIAL_MESSAGES" in chat_tab_source
    assert "展开更早记录" in chat_tab_source
    assert "excludedMessageCount" in chat_tab_source
    assert "本轮尚未发送" in chat_tab_source
    assert "v-if=\"input.trim() || props.contextTrace || props.contextBlocked || props.saveStatus === 'unsaved'\"" not in chat_tab_source
    assert "<span v-else>本轮尚未发送。</span>" in chat_tab_source
    assert "v-else-if=\"isSubmitting\">本轮正在提交并保存。</span>" in chat_tab_source
    assert "v-else-if=\"props.contextTrace\">最近一次已发送。</span>" in chat_tab_source
    assert "Array.isArray(props.contextTrace?.included_message_ids)" in chat_tab_source
    assert "props.contextTrace.included_message_ids.length" not in chat_tab_template
    assert "props.contextTrace.omitted_message_ids.length" not in chat_tab_template
    assert "retrySave" in chat_tab_source
    assert "openOutlineForContext" in chat_tab_source
    assert "openOutlineForChatContext" in chat_source
    assert "openOutlineForChatContext," in chat_source
    assert "CHAT_MESSAGE_MAX_CHARS" in workspace_source
    assert ":submit-chat=\"sendChatMessage\"" in workspace_source
    assert ":open-outline-for-context=\"openOutlineForChatContext\"" in workspace_source
    assert ":retry-save=\"retryChatBrainstormSave\"" in workspace_source


def test_workspace_local_storage_is_scoped_by_actor_and_project():
    storage_source = (ROOT / "webui/src/features/workspace/utils/workspaceStorage.ts").read_text()
    character_source = (ROOT / "webui/src/features/workspace/composables/useCharacterTab.ts").read_text()
    cards_source = (ROOT / "webui/src/features/workspace/composables/useStoryStateAutosave.ts").read_text()
    tabs_source = (ROOT / "webui/src/features/workspace/composables/useWorkspaceTabs.ts").read_text()

    assert "moxi-workspace" in storage_source
    assert "return `user:${_safeSegment(userKey)}`" in storage_source
    assert "return `admin:${simpleHash(adminToken).slice(0, 12)}`" in storage_source
    assert storage_source.index("const userSession") < storage_source.index("const adminToken")
    assert "return [" in storage_source
    assert "STORAGE_PREFIX" in storage_source
    assert "legacyWorkspaceStorageKey(bucket, projectId)" in storage_source
    assert "_canReadLegacyStorage(scope)" in storage_source
    assert "scope.startsWith('admin:')" in storage_source
    assert "if (!_canReadLegacyStorage(scope)) return null" in storage_source
    assert "return `${bucket}_${projectId}`" in storage_source
    assert "saveWorkspaceStorage('characters'" in character_source
    assert "saveWorkspaceStorage('stateCards'" in cards_source
    assert "loadWorkspaceStorage('completedTabs'" in tabs_source
    assert "saveWorkspaceStorage('completedTabs'" in tabs_source


def test_script_toolbar_keeps_scene_title_readable():
    source = (ROOT / "webui/src/views/workspace/tabs/ScriptToolbar.vue").read_text()

    assert "flex-col lg:flex-row" in source
    assert "whitespace-nowrap" in source
    assert "flex-wrap lg:flex-nowrap" in source
    assert "truncate" in source


def test_projects_view_recovers_created_project_after_timeout_contract():
    view_source = (ROOT / "webui/src/views/ProjectsView.vue").read_text()
    store_source = (ROOT / "webui/src/stores/projects.ts").read_text()
    api_source = (ROOT / "webui/src/api/modules/projects.ts").read_text()

    assert "recoverCreatedProject" in view_source
    assert "isTimeoutError" in view_source
    assert "isDuplicateNameError" in view_source
    assert "projectsStore.fetchProjects(true)" in view_source
    assert "projectsStore.clearError()" in view_source
    assert "router.push(`/projects/${existing.id}/workspace" in view_source
    assert "function clearError" in store_source
    assert "lastError.value = ''" in store_source
    assert "lastFetchedAt.value = Date.now()" in store_source
    assert "profileOptionsLoaded" in view_source
    assert "void loadProfileOptions()" in view_source
    assert "loadProfileOptions()" not in view_source.split("onMounted(() => {", 1)[1].split("})", 1)[0]
    assert "AxiosRequestConfig" in api_source
    assert "timeout: 8000" in api_source
    assert "PROJECT_LIST_TIMEOUT_MS = 8_000" in store_source
    assert "activeListController?.abort()" in store_source
    assert "currentProjectListScope" in store_source
    assert "resetForAuthScope" in store_source
    assert "projects.value = []" in store_source
    assert "user_access_session" in store_source
    assert "admin_token" in store_source
    assert "ERR_CANCELED" in store_source


def test_workspace_outline_analysis_has_fast_local_fallback_contract():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    api_source = (ROOT / "webui/src/api/modules/projects.ts").read_text()
    raw_panel_source = (ROOT / "webui/src/views/workspace/tabs/OutlineRawPanel.vue").read_text()
    outline_body_source = (ROOT / "webui/src/views/workspace/tabs/OutlineTabBody.vue").read_text()

    assert "OUTLINE_ANALYZE_FAST_PARSE_CHARS" in source
    assert "_buildLocalOutlineAnalysis" in source
    assert "_extractLocalOutlineCharacters" in source
    assert "_extractLocalOutlineEpisodes" in source
    assert "_outlineChunkHasScriptBody" in source
    assert "_extractRangeOutlineEpisodes" in source
    assert "_extractLocalOutlineRelationships" in source
    assert "_attachAnalysisRelationshipsToOutlineCharacters" in source
    assert "_extractOutlineCharacterAnyField" in source
    assert "_isValidLocalCharacterName" in source
    assert "outlineAnalyzeStatus" in source
    assert "正在自动分割大纲内容" in source
    assert "自动分割完成" in source
    assert "原文没有识别到的内容已留空，需要用户手动补全" in source
    assert "projectsV2Api.analyzeOutline(outline, 0.3)" not in source
    assert "projectsV2Api.analyzeOutline(outline, 0.3, projectRules.value.total_episodes)" not in source
    assert "projectsV2Api.predictOutline" in source
    assert "predictOutlineAndFill" in source
    assert "_runOutlinePredictionFill" in source
    assert "outlineAiFeaturesPaused" in source
    assert "全局预测功能暂时关闭" in source
    assert "_outlineEpisodeFieldIsLowQuality" in source
    assert "围绕“" in source
    assert "剧本预测 · 一键补全" not in raw_panel_source
    assert "自动分割内容" in raw_panel_source
    assert "可以拖拽文件进入 / 点击上传" in raw_panel_source
    assert "功能尚未开发完全，需要用户手动完成所有信息的补全" in outline_body_source
    assert "{ timeout: 60000 }" in api_source
    assert "extractOutlineFile" in api_source
    assert "predictOutline" in api_source
    assert "{ timeout: 90000 }" in api_source
    assert "statusMessage" in raw_panel_source
    assert 'aria-live="polite"' in raw_panel_source
    assert ":status-message=\"outlineAnalyzeStatus\"" in outline_body_source


def test_workspace_outline_character_parser_uses_generic_labeled_character_block():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    extract_body = source.split("function _extractLocalOutlineCharacters", 1)[1].split("function _inferLocalRelationshipType", 1)[0]
    block_helper = source.split("function _extractLabeledCharacterBlock", 1)[1].split("function _extractCharactersFromLabeledBlock", 1)[0]

    assert "function _extractLabeledCharacterBlock" in source
    assert "function _extractCharactersFromLabeledBlock" in source
    assert "角色|主要角色|人物|人物小传|角色库" in block_helper
    assert "分集|集纲|第" in block_helper
    assert "_extractCharactersFromLabeledBlock(outline)" in extract_body
    assert extract_body.index("_extractCharactersFromLabeledBlock(outline)") < extract_body.index("_extractLocalInlineCharacterListRows")
    assert "林汐" not in block_helper
    assert "谢沉" not in block_helper
    assert "梁远" not in block_helper


def test_workspace_outline_episode_framework_is_per_episode_dropdown_contract():
    episodes_source = (ROOT / "webui/src/views/workspace/tabs/OutlineEpisodeFrameworkPanel.vue").read_text()

    assert "<details" in episodes_source
    assert "<summary" in episodes_source
    assert "单集集纲" in episodes_source
    assert "规则结构" in episodes_source
    assert "关系变化" in episodes_source
    assert "信息揭露" in episodes_source
    assert "爽点类型" in episodes_source
    assert "AI生成集纲" in episodes_source
    assert "AI生成集纲（暂停）" in episodes_source
    assert "结尾钩子" not in episodes_source
    assert "尾钩" not in episodes_source


def test_workspace_ai_generate_episodes_uses_background_job_contract():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    body = source.split("async function generateEpisodes", 1)[1].split("function addOutlineCharacter", 1)[0]

    # 集纲生成改为后台任务 + 轮询进度（规避前端 90s 超时；内部仍走全剧预测再分批生成）
    assert "startEpisodeOutlinesJob" in body
    assert "getEpisodeOutlinesJobStatus" in body
    assert "后台任务" in body
    assert "outlineAiFeaturesPaused" in body
    assert "AI生成集纲功能暂时关闭，请先手动补全集纲" in body
    assert "projectsV2Api.generateEpisodeOutlines" not in body
    assert "_applyOutlinePredictionResult" in body
    assert "_persistOutlineDraft('ai_generate_episodes_draft'" in body


def test_workspace_outline_fallback_copy_never_says_local_fill_or_generated_truth():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    prediction_body = source.split("async function _runOutlinePredictionFill", 1)[1].split("async function predictOutlineAndFill", 1)[0]
    episode_body = source.split("async function generateEpisodes", 1)[1].split("function addOutlineCharacter", 1)[0]

    assert "本地规则补齐" not in prediction_body
    assert "本地预测链路补齐" not in prediction_body
    assert "已用本地链路补齐" not in episode_body
    assert "候选占位" in prediction_body
    assert "等待确认" in episode_body


def test_workspace_outline_fallback_marks_candidate_boundary_before_main_chain():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()

    assert "outlineFallbackCandidateBoundary" in source
    assert "candidate_source: 'local_fallback'" in source
    assert "downstream_generation_allowed: false" in source
    assert "本地候选草稿，需确认后才会进入主生成链路" in source


def test_workspace_outline_prediction_stays_draft_until_confirmed():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    chat_source = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()
    generated_body = source.split("onOutlineGenerated: async", 1)[1].split("},\n})", 1)[0]
    analysis_body = source.split("async function _persistOutlineAnalysis", 1)[1].split("function _buildOutlineGenerationText", 1)[0]
    prediction_body = source.split("async function _runOutlinePredictionFill", 1)[1].split("async function predictOutlineAndFill", 1)[0]
    mounted_body = source.split("await bootstrapQueryPromptFromRoute()", 1)[1].split("// load episodes if script tab", 1)[0]

    assert "_persistOutlineDraft('chat_brainstorm_outline_draft'" in generated_body
    assert "const persisted = await _persistOutlineDraft('chat_brainstorm_outline_draft'" in generated_body
    assert "if (persisted !== true)" in generated_body
    assert "return true" in generated_body
    assert "const persisted = await opts.onOutlineGenerated" in chat_source
    assert "persisted !== true" in chat_source
    assert "候选字段已经生成，但没有保存成功" in chat_source
    assert "syncOutlineCharsToDesign" not in generated_body
    assert "_refreshSeriesSimulationPacket" not in generated_body
    assert "_persistOutlineDraft('outline_analyzed_draft'" in analysis_body
    assert "_refreshSeriesSimulationPacket" not in analysis_body
    assert "_refreshSeriesSimulationPacket('outline_prediction_fill" not in prediction_body
    assert "_isOutlineCommittedToMainChain()" in mounted_body
    assert "_refreshSeriesSimulationPacket('project_loaded_outline_snapshot'" in mounted_body


def test_workspace_direct_character_tab_syncs_outline_characters_contract():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    outline_gate_source = (ROOT / "webui/src/features/workspace/composables/useOutlineGate.ts").read_text()
    switch_body = source.split("async function switchTab", 1)[1].split("// 从导入文本框触发解析", 1)[0]
    save_body = source.split("async function saveOutline()", 1)[1].split("async function commitOutlineToMainChain", 1)[0]
    commit_body = source.split("async function commitOutlineToMainChain", 1)[1].split("async function saveOutlineAndContinue", 1)[0]
    persist_body = source.split("async function _persistOutlineSnapshot", 1)[1].split("function _ingestWorkflowUpdates", 1)[0]

    assert "switchTab: _switchWorkspaceTab" in source
    assert "async function switchTab(tab: WorkspaceTabId)" in source
    assert "_outlineNeedsMainChainCommit()" in switch_body
    assert "await commitOutlineToMainChain()" in switch_body
    assert "syncOutlineCharsToDesign" not in switch_body
    assert "_persistOutlineDraft('outline_saved_draft'" in save_body
    assert "syncOutlineCharsToDesign" not in save_body
    assert "_seedExistingScriptsFromOutline" not in save_body
    assert "_refreshSeriesSimulationPacket" not in save_body
    assert "syncOutlineCharsToDesign({ selectFirst: true })" in commit_body
    assert "_seedExistingScriptsFromOutline()" in commit_body
    assert "_refreshSeriesSimulationPacket('outline_committed'" in commit_body
    assert "_persistOutlineSnapshot('outline_committed'" in commit_body
    assert "const episodesReady = await createEpisodesBatch({ silent: true })" in commit_body
    assert "if (!episodesReady)" in commit_body
    assert commit_body.index("_persistOutlineSnapshot('outline_committed'") < commit_body.index("const episodesReady = await createEpisodesBatch({ silent: true })")
    assert "main_chain_committed" in persist_body
    assert "main_chain_dirty" in persist_body
    assert "main_chain_committed" in outline_gate_source
    assert "main_chain_dirty" in outline_gate_source
    assert "大纲草稿尚未确认进入角色设计" in outline_gate_source
    assert "syncOutlineCharsToDesign({ selectFirst: true })" in source
    assert "hasPreparedOutlineFromChat" in source
    assert "请先在聊天脑暴完成选题，或在大纲页上传/解析已有大纲" in source
    assert "_switchWorkspaceTab(tab)" in source
    assert "selectedCharacterId.value = mapped[0]?.id || null" in source
    assert "_extractOutlineCharacterRelationships" in source
    assert "_resolveImportedRelationships" in source
    assert "importedRelationships" in source
    assert "existingRelationships" in source
    assert "function ensureCharacterSelection()" in source
    assert "activeTab.value !== 'characters'" in source
    assert "selectedCharacterId.value = String(available[0].id)" in source
    assert "视觉档案" in source


def test_workspace_outline_main_chain_commit_blocks_incomplete_episode_outlines():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    outline_body = (ROOT / "webui/src/views/workspace/tabs/OutlineTabBody.vue").read_text()
    outline_header = (ROOT / "webui/src/views/workspace/tabs/OutlineTabHeader.vue").read_text()
    commit_body = source.split("async function commitOutlineToMainChain", 1)[1].split("async function saveOutlineAndContinue", 1)[0]
    pre_main_chain_snapshot = commit_body.split("_persistOutlineSnapshot('outline_committed'", 1)[0]

    assert "outlineMainChainCommitIssues" in source
    assert "outlineMainChainCommitBlocked" in source
    assert "outlineMainChainCommitBlockReason" in source
    assert "_ensureOutlineMainChainCommitGatePassed" in source
    assert "_ensureOutlineMainChainCommitGatePassed({ silent: options?.silent })" in pre_main_chain_snapshot
    assert "outlineData.value.episodes.length < confirmedCount" in source
    assert "请先补齐分集集纲" in source
    assert ":outline-main-chain-commit-blocked=\"outlineMainChainCommitBlocked\"" in source
    assert ":outline-main-chain-commit-block-reason=\"outlineMainChainCommitBlockReason\"" in source
    assert ":commit-blocked=\"outlineMainChainCommitBlocked\"" in source
    assert ":commit-block-reason=\"outlineMainChainCommitBlockReason\"" in source
    assert "outlineMainChainCommitBlocked" in outline_body
    assert ":disabled=\"outlineMainChainCommitBlocked\"" in outline_body
    assert "commitBlocked" in outline_header
    assert ":disabled=\"saving || commitBlocked\"" in outline_header


def test_manual_outline_prediction_uses_confirmed_episode_count_without_overwriting_from_generated_length():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    body = source.split("async function _runOutlinePredictionFill", 1)[1].split("async function predictOutlineAndFill", 1)[0]

    assert "const target = _effectiveUserConfirmedTotalEpisodes()" in body
    assert "projectRules.value.total_episodes = Math.max(1, Math.min(200, outlineData.value.episodes.length))" not in body
    assert "_syncProjectRulesTotalEpisodesFromConfirmedCount()" in body


def test_workspace_chat_episode_count_uses_confirmed_value_not_default_twelve():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()

    assert "resolveConfirmedEpisodeCount" in source
    assert "episodeCount: () => projectRules.value.total_episodes || 12" not in source
    assert "episodeCount: () => _effectiveUserConfirmedTotalEpisodes()" in source


def test_workspace_navigation_blocks_when_script_save_fails_without_ambiguous_continue_confirm():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    switch_body = source.split("async function switchTab", 1)[1].split("// 从导入文本框触发解析", 1)[0]
    leave_body = source.split("onBeforeRouteLeave(async () => {", 1)[1].split("// 真实写作进度", 1)[0]
    load_episode_body = source.split("async function loadScriptEpisode", 1)[1].split("async function selectScriptScene", 1)[0]
    select_scene_body = source.split("async function selectScriptScene", 1)[1].split("async function saveScript", 1)[0]

    assert "确定要切换页面吗" not in switch_body
    assert "确定要离开吗" not in leave_body
    assert "确定要切换场景吗" not in select_scene_body
    assert "正文保存失败，请先保存成功后再切换页面" in switch_body
    assert "正文保存失败，请先保存成功后再离开页面" in leave_body
    assert "当前场景保存失败，请先保存成功后再切换场景" in select_scene_body
    assert "const saved = await persistCurrentScriptContent" in load_episode_body
    assert "if (!saved)" in load_episode_body
    assert "正文保存失败，请先保存成功后再切换集数" in load_episode_body


def test_workspace_chat_outline_lock_state_is_explicit_and_visible_contract():
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    outline_body = (ROOT / "webui/src/views/workspace/tabs/OutlineTabBody.vue").read_text()
    outline_gate_source = (ROOT / "webui/src/features/workspace/composables/useOutlineGate.ts").read_text()
    persist_body = workspace.split("async function _persistOutlineSnapshot", 1)[1].split("function _ingestWorkflowUpdates", 1)[0]

    assert "main_chain_status" in persist_body
    assert "candidate_draft_needs_user_confirmation" in persist_body
    assert "user_locked_main_chain" in persist_body
    assert "user_confirmation_required" in persist_body
    assert "downstream_generation_allowed" in persist_body
    assert "main_chain_source" in persist_body
    assert "chat_brainstorm_candidate" in persist_body
    assert "outlineMainChainStatusText" in workspace
    assert ":outline-main-chain-status-text=\"outlineMainChainStatusText\"" in workspace
    assert "outlineMainChainStatusText" in outline_body
    assert "聊天脑暴候选草稿" in workspace
    assert "已锁定为主生成链路" in workspace
    assert "大纲草稿尚未确认进入角色设计" in outline_gate_source


def test_workspace_pasted_outline_candidate_save_returns_boolean_without_formal_promotion():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    generated_body = source.split("onOutlineGenerated: async", 1)[1].split("},\n})", 1)[0]

    assert "const persisted = await _persistOutlineDraft('chat_brainstorm_outline_draft'" in generated_body
    assert "preserveEditorData: generatedStandardOutlinePacket?.status !== 'confirmed'" in generated_body
    assert "markChatTabComplete" not in generated_body
    assert "switchToOutline" not in generated_body
    assert "commitOutlineToMainChain" not in generated_body
    assert "main_chain_committed" not in generated_body
    assert "generatedStandardOutlinePacket.status === 'confirmed'" in generated_body
    assert "projectStandardOutlinePacketToOutline(generatedStandardOutlinePacket)" in generated_body
    assert "if (!generatedStandardOutlinePacket)" in generated_body
    ai_mark_body = generated_body.split("if (!generatedStandardOutlinePacket)", 1)[1]
    assert "_markOutlineAiGenerated('characters')" in ai_mark_body
    assert "_markOutlineAiGenerated('episodes')" in ai_mark_body
    assert "standardOutlinePacket.value = previousStandardOutlinePacket" in generated_body
    assert "outlineData.value = previousOutlineData" in generated_body
    assert "outlineCharacters.value = previousOutlineCharacters" in generated_body
    assert "workflowContext.value = previousWorkflowContext" in generated_body
    assert "sanitizeOutlineCharacters: options?.preserveEditorData !== true" in source


def _legacy_workspace_pasted_outline_candidate_preview_contract():
    preview = (ROOT / "webui/src/views/workspace/tabs/PastedOutlineCandidatePreview.vue").read_text()
    preview_state = (ROOT / "webui/src/features/workspace/utils/pastedOutlineCandidatePreview.ts").read_text()
    chat_tab = (ROOT / "webui/src/views/workspace/tabs/ChatTab.vue").read_text()
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()

    assert "preview: PastedOutlineCandidatePreviewState | null" in preview
    assert "'retry': []" in preview
    assert "countContextChars(sourceText.value)" in preview
    assert "props.preview?.packet.source_material.raw_text" in preview
    assert "props.preview?.packet.current_stage" in preview
    assert "isConfirmedOutlinePreview(props.preview)" in preview
    assert "content_correctness_summary" in preview
    assert "field.status" in preview
    assert "field.source" in preview
    assert "'episode_count_plan.episode_count_reason': '集数理由'" in preview
    assert "'long_arc.summary': '长线故事弧'" in preview
    assert "recognized" in preview
    assert "inferred" in preview
    assert "incomplete" in preview
    assert "unrecognized" in preview
    assert "conflict_issues" in preview
    assert "已识别字段" in preview
    assert "候选推断" in preview
    assert "识别不完整" in preview
    assert "无法识别" in preview
    assert "<details" in preview
    assert "<summary" in preview
    assert "<pre" in preview
    assert "overflow" in preview
    assert "v-html" not in preview
    assert "已整理为候选资料包，等待你确认" in preview_state
    assert "候选整理未完成，原文已保存" in preview_state
    assert "尚待保存" in preview_state
    assert "当前页面保留" in preview_state
    assert "@click=\"emit('retry')\"" in preview
    assert "aria-live=\"polite\"" in preview
    assert "max-h-48 overflow-auto break-words" in preview
    assert "资料包已由你确认" in preview_state
    assert "candidatePreviewSaveStatusText(props.preview)" in preview
    assert "已确认资料包与原文已保存" in preview_state
    assert "重试保存" in preview
    assert "重试保存与整理" not in preview
    assert "全部阶段已确认" in preview
    assert "完整大纲已完成" not in preview + preview_state
    assert "可以直接生成剧本" not in preview + preview_state
    assert "自动确认" not in preview + preview_state

    assert "PastedOutlineCandidatePreview" in chat_tab
    assert "candidatePreview?: PastedOutlineCandidatePreviewState | null" in chat_tab
    assert ":preview=\"props.candidatePreview || null\"" in chat_tab
    assert "retryCandidateSave: () => Promise<boolean>" in chat_tab
    assert "@retry=\"void props.retryCandidateSave()\"" in chat_tab
    assert "@retry=\"emit('generate-outline')\"" not in chat_tab
    assert "candidatePreviewScrollIdentity(props.candidatePreview)" in chat_tab
    assert "props.candidatePreview?.packet.updated_at" not in chat_tab
    scroll_watch = chat_tab.split("watch(\n  [\n    () => props.messages.length", 1)[1].split("{ immediate: true },", 1)[0]
    assert "() => candidatePreviewScrollIdentity(props.candidatePreview)" in scroll_watch
    assert "props.outlineLoading" not in scroll_watch
    assert "继续当前资料包确认" in preview_state
    assert "进入大纲资料包确认" in preview_state
    assert "查看已确认大纲资料包" in preview_state
    assert "props.openOutlineForContext" in chat_tab
    assert chat_tab.index("<PastedOutlineCandidatePreview") < chat_tab.index("<textarea")
    assert chat_tab.count("<PastedOutlineCandidatePreview") == 1
    message_flow = chat_tab.split('<ScrollArea class="flex-1">', 1)[1].split("</ScrollArea>", 1)[0]
    assert message_flow.index("<PastedOutlineCandidatePreview") < message_flow.index('<div ref="messageEnd"')
    assert "<textarea" not in message_flow

    assert "pastedOutlineCandidatePreview" in workspace
    assert ":candidate-preview=\"pastedOutlineCandidatePreview\"" in workspace
    assert "retryPastedOutlineCandidateSave" in workspace
    assert ":retry-candidate-save=\"retryPastedOutlineCandidateSave\"" in workspace

    composable = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()
    retry_body = composable.split("async function retryPastedOutlineCandidateSave", 1)[1].split("\n  async function generateOutlineFromChat", 1)[0]
    assert "retryPastedOutlineCandidateSaveOnly" in retry_body
    assert "_enrichPastedOutlineCandidate" not in retry_body
    assert "chatApi" not in retry_body
    assert "retryPastedOutlineCandidateSave," in composable


def test_chat_brainstorm_keeps_existing_outline_in_editor_contract():
    chat_tab = (ROOT / "webui/src/views/workspace/tabs/ChatTab.vue").read_text()
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    composable = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()

    assert "聊天脑暴负责选题和创作探讨" in chat_tab
    assert "只有右侧明确确认的内容才进入大纲资料" in chat_tab
    assert "上传剧本" in chat_tab
    assert "上传大纲" not in chat_tab
    assert "accept=\".docx,.md,.markdown,.txt\"" in chat_tab
    assert "@upload-reference=\"handleChatReferenceUpload\"" in workspace
    assert "@upload-file=\"handleChatOutlineFileUpload\"" not in workspace
    assert "ingestOutlineDocument" not in workspace
    assert "pendingOutlineDocumentText" not in composable
    assert "【用户上传的大纲原文" not in composable
    assert "_isExistingOutlineHandlingRequest" not in composable


def test_workspace_outline_layout_resists_ai_panel_squeeze_contract():
    workspace_source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    outline_body_source = (ROOT / "webui/src/views/workspace/tabs/OutlineTabBody.vue").read_text()

    assert "flex-1 min-w-0 overflow-hidden flex flex-col" in workspace_source
    assert "relative inset-auto z-auto shadow-none" in workspace_source
    assert "absolute inset-y-0 right-0 z-30" not in workspace_source
    assert "xl:relative" in workspace_source
    assert "flex-1 min-w-0 flex overflow-hidden" in outline_body_source
    assert "min-w-[420px]" in outline_body_source


def test_ai_assistant_panel_does_not_cover_primary_workspace_actions():
    workspace_source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    panel_source = (ROOT / "webui/src/views/workspace/panels/AiAssistantPanel.vue").read_text()

    assert "AI创作助手" in panel_source
    assert "relative inset-auto z-auto shadow-none" in workspace_source
    assert "absolute inset-y-0 right-0 z-30" not in workspace_source


def test_compliance_empty_script_has_blocking_message_not_no_issues():
    source = (ROOT / "webui/src/views/workspace/tabs/ComplianceReviewTab.vue").read_text()

    assert "selectedEpisodeHasScriptBody" in source
    assert "本集暂无正文，不能审核通过" in source
    assert "当前无法审核：本集没有正文。" in source
    assert "当前没有待处理问题。" in source
    assert source.index("v-else-if=\"!selectedEpisodeHasScriptBody\"") < source.index("v-else-if=\"selectedFindings.length === 0\"")


def test_storyboard_tab_requires_saved_script_before_entry():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    switch_body = source.split("async function switchTab", 1)[1].split("async function importAndAnalyze", 1)[0]

    assert "function _hasSavedScriptContentForEpisode" in source
    assert "async function _ensureStoryboardHasSavedScriptContent" in source
    assert "await _ensureStoryboardHasSavedScriptContent()" in switch_body
    assert "本集还没有正文，不能生成分镜提示词" in source
    assert "await refreshEpisodesSilently()" in source
