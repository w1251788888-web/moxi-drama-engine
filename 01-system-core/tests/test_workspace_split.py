from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui" / "src"


def read_src(relative: str) -> str:
    return (WEBUI / relative).read_text(encoding="utf-8")


def test_ai_assistant_panel_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/panels/AiAssistantPanel.vue")

    assert "AiAssistantPanel" in workspace
    assert "AI创作助手" not in workspace
    assert "AI创作助手" in panel
    assert "defineEmits" in panel
    assert "send" in panel


def test_chat_tab_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    chat_tab = read_src("views/workspace/tabs/ChatTab.vue")
    panel = read_src("views/workspace/panels/OutlineConfirmationPanel.vue")

    assert "ChatTab" in workspace
    assert "聊天脑暴负责选题和创作探讨" not in workspace
    assert "聊天脑暴负责选题和创作探讨" in chat_tab
    assert "upload-reference" in chat_tab
    assert "OutlineConfirmationPanel" in workspace
    assert "整理当前讨论" in panel


def test_outline_header_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    header = read_src("views/workspace/tabs/OutlineTabHeader.vue")

    assert "OutlineTabHeader" in workspace
    assert "大纲编辑器" not in workspace
    assert "大纲编辑器" in header
    assert "continue" in header


def test_outline_body_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    body = read_src("views/workspace/tabs/OutlineTabBody.vue")

    assert "OutlineTabBody" in workspace
    assert "解析大纲并预测" not in workspace
    assert "v-model:raw-outline-text" in workspace
    assert "@generate-episodes" in workspace
    assert "defineEmits" in body


def test_outline_raw_panel_is_extracted_from_outline_body():
    body = read_src("views/workspace/tabs/OutlineTabBody.vue")
    raw_panel = read_src("views/workspace/tabs/OutlineRawPanel.vue")

    assert "OutlineRawPanel" in body
    assert "解析大纲并预测" not in body
    assert "v-model:raw-outline-text" in body
    assert "自动分割内容" in raw_panel
    assert "可以拖拽文件进入 / 点击上传" in raw_panel
    assert "大纲原文" in raw_panel
    assert "defineEmits" in raw_panel


def test_outline_workflow_settings_panel_is_extracted_from_outline_body():
    body = read_src("views/workspace/tabs/OutlineTabBody.vue")
    settings_panel = read_src("views/workspace/tabs/OutlineWorkflowSettingsPanel.vue")

    assert "OutlineWorkflowSettingsPanel" in body
    assert "工作流参数" not in body
    assert "项目生成模型" not in body
    assert "v-model:project-rules" in body
    assert "工作流参数" in settings_panel
    assert "项目生成模型" not in settings_panel
    assert "模型版本" not in settings_panel
    assert "统一科研生成链路" in settings_panel
    assert "中文场标" in settings_panel
    assert "简洁场标" in settings_panel
    assert "bracket ·" not in settings_panel
    assert "plain ·" not in settings_panel
    assert "v-model=\"projectRules.advanced_generation_mode\"" not in settings_panel
    assert "高级生成模式" not in settings_panel


def test_outline_right_side_sections_are_extracted_from_outline_body():
    body = read_src("views/workspace/tabs/OutlineTabBody.vue")
    direction = read_src("views/workspace/tabs/OutlineCreativeDirectionPanel.vue")
    core_fields = read_src("views/workspace/tabs/OutlineCoreFieldsPanel.vue")
    characters = read_src("views/workspace/tabs/OutlineCharacterListPanel.vue")
    episodes = read_src("views/workspace/tabs/OutlineEpisodeFrameworkPanel.vue")

    assert "OutlineCreativeDirectionPanel" in body
    assert "OutlineCoreFieldsPanel" in body
    assert "OutlineCharacterListPanel" in body
    assert "OutlineEpisodeFrameworkPanel" in body
    assert "已激活专属规则" not in body
    assert "一句话梗概" not in body
    assert "添加角色" not in body
    assert "AI生成框架" not in body
    assert "已激活专属规则" in direction
    assert "一句话梗概" in core_fields
    assert "AI优化暂停" in core_fields
    assert "添加角色" in characters
    assert "关系设计" in characters
    assert "relationshipLabels" in characters
    assert "AI生成集纲" in episodes
    assert "AI生成集纲（暂停）" in episodes


def test_character_tab_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    character_tab = read_src("views/workspace/tabs/CharacterTab.vue")

    assert "CharacterTab" in workspace
    assert "实时关系图谱" not in workspace
    assert "CharacterVisualPanel" not in workspace
    assert "角色库" in character_tab
    assert "角色库信息必须由用户手动补全" in character_tab
    assert "实时关系图谱" in character_tab
    assert "CharacterVisualPanel" not in character_tab
    assert "视觉档案" not in character_tab
    assert "请逐一检查角色身份、人物小传、关系和动机弧线" in character_tab


def test_script_sidebar_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    sidebar = read_src("views/workspace/tabs/ScriptSidebar.vue")

    assert "ScriptSidebar" in workspace
    assert "@select-scene" in workspace
    assert '@save-episode="saveEpisodeFromSidebar"' in workspace
    assert '@delete-episode="deleteEpisode"' in workspace
    assert "新建集" in sidebar
    assert "保存当前集" in sidebar
    assert "删除本集" in sidebar
    assert "ep.title" not in sidebar, "分集列表只展示干净集数，不再在下方重复显示第N集标题"
    assert "新建场" not in sidebar, "侧边栏不展示场层级；场标只存在于整集正文内部"
    assert "v-for=\"scene in" not in sidebar, "侧边栏不再列出场，避免把整集写作拆成手动场次"
    assert "defineEmits" in sidebar


def test_script_toolbar_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    toolbar = read_src("views/workspace/tabs/ScriptToolbar.vue")

    assert "ScriptToolbar" in workspace
    assert "ScriptConfirmButton" not in workspace
    assert "@run-script-rule-validation" in workspace
    assert "审查本集" in toolbar
    assert "规则/合规预检" in toolbar
    assert "ScriptConfirmButton" not in toolbar, "确认类低频动作不应挤占剧本写作主工具栏"
    assert "多模态写作" not in toolbar
    assert "联系管理员开启" not in toolbar
    assert "border-dashed" not in toolbar
    assert "isSegmentedInProgress" in toolbar
    assert "生成本集" in toolbar
    assert "继续生成" in toolbar
    assert "分段精写" not in toolbar
    assert "generateSegmented" not in toolbar
    assert "currentGenerationLabel" not in toolbar
    assert "showScriptGraph" not in toolbar
    assert "toggleScriptGraph" not in toolbar
    assert "健康" not in toolbar
    assert "Bot" not in toolbar
    assert ":current-generation-label" not in workspace
    assert ":show-script-graph" not in workspace
    assert "@toggle-script-graph" not in workspace
    assert "toggleAdvancedGeneration" not in toolbar
    assert "@toggle-advanced-generation" not in workspace
    assert "advanced_generation_mode" in workspace
    assert "defineEmits" in toolbar


def test_user_feedback_outline_genre_supports_custom_input():
    direction = read_src("views/workspace/tabs/OutlineCreativeDirectionPanel.vue")

    assert "自定义题材" in direction
    assert "customGenreInput" in direction
    assert "applyCustomGenre" in direction
    assert "v-model.trim=\"customGenreInput\"" in direction
    assert "甜宠先婚后爱" in direction
    assert "重生逆袭" in direction
    assert "其他" not in direction, "其他按钮不能再只是占位，必须改成可填写的自定义题材"


def test_user_feedback_character_relationships_support_custom_types_and_stages():
    editor = read_src("components/workshop/CharacterEditor.vue")

    assert "父女" in editor
    assert "母子" in editor
    assert "亲属" in editor
    assert "自定义关系" in editor
    assert "customRelationshipType" in editor
    assert "normalizeRelationshipType" in editor
    assert "早期关系" in editor
    assert "后期关系" in editor
    assert "转折集" in editor
    assert "转折条件" in editor
    assert "禁止提前写出" in editor
    assert "earlyType" in editor
    assert "lateType" in editor
    assert "transitionEpisode" in editor
    assert "transitionTrigger" in editor
    assert "finalBoundary" in editor
    assert "candidateStatus" in editor
    assert "能力属性" not in editor
    assert "updateStatValue" not in editor
    assert "stats:" not in editor


def test_outline_relationship_candidates_require_confirmation_and_link_to_episode_changes():
    characters = read_src("views/workspace/tabs/OutlineCharacterListPanel.vue")
    episodes = read_src("views/workspace/tabs/OutlineEpisodeFrameworkPanel.vue")

    assert "AI识别关系候选" in characters
    assert "needs_user_confirmation" in characters
    assert "确认关系线" in characters
    assert "早期关系" in characters
    assert "后期关系" in characters
    assert "转折集" in characters
    assert "confirmRelationshipLine(char, relIndex)" in characters
    assert "outlineCharacters.value = outlineCharacters.value.map" in characters
    assert "candidate_status: 'confirmed'" in characters
    assert "关系联动提示" in episodes
    assert "改动本集关系变化后，请回到角色关系线核对" in episodes


def test_generation_request_carries_episode_relationship_timeline_context():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    types = read_src("types/workshop.ts")

    assert "_buildRelationshipTimelineContext" in workspace
    assert "relationship_timeline_context" in workspace
    assert "earlyType" in workspace
    assert "lateType" in workspace
    assert "transitionEpisode" in workspace
    assert "finalBoundary" in workspace
    assert "stats:" not in types


def test_outline_character_field_parser_accepts_colon_equals_and_fullwidth_equals_delimiters():
    workspace = read_src("views/ProjectWorkspaceView.vue")

    parser_section = workspace.split("const OUTLINE_CHARACTER_SUBFIELD_LINE_RE", 1)[1].split(
        "function _extractLocalOutlineNameBlocks",
        1,
    )[0]
    block_header_section = workspace.split("const blockHeaderRe =", 1)[1].split("const blocks =", 1)[0]

    for case_name, delimiter in (
        ("colon", "："),
        ("ascii_colon", ":"),
        ("equals", "="),
        ("fullwidth_equals", "＝"),
    ):
        assert delimiter in parser_section, f"{case_name} delimiter missing from subfield parser"
        assert delimiter in block_header_section, f"{case_name} delimiter missing from character block lookahead"


def test_outline_character_field_parser_keeps_whitespace_and_malformed_field_guards():
    workspace = read_src("views/ProjectWorkspaceView.vue")

    parser_section = workspace.split("const OUTLINE_CHARACTER_SUBFIELD_LINE_RE", 1)[1].split(
        "function _extractLocalOutlineNameBlocks",
        1,
    )[0]
    block_header_section = workspace.split("const blockHeaderRe =", 1)[1].split("const blocks =", 1)[0]
    allowed_fields = "年龄|性别|身份|职业|阵营|性格|人物性格|背景"

    assert r"\s*[：:=＝]" in parser_section
    assert r"\s*[：:=＝]" in block_header_section
    assert allowed_fields in parser_section
    assert allowed_fields in block_header_section
    assert "任意字段" not in parser_section
    assert ".*\\s*[：:=＝]" not in parser_section


def test_user_feedback_script_sidebar_supports_batch_episode_creation():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    sidebar = read_src("views/workspace/tabs/ScriptSidebar.vue")

    assert "createEpisodesBatch" in workspace
    assert '@create-episodes-batch="createEpisodesBatch"' in workspace
    assert "createEpisodesBatch" in sidebar
    assert "批量建集" in sidebar
    assert "补齐到总集数" in sidebar
    assert "isAtEpisodeLimit" in sidebar
    assert "已达到项目总集数上限" in sidebar
    assert "projectRules.value.total_episodes" in workspace


def test_user_feedback_script_toolbar_hides_internal_chain_and_word_advice():
    toolbar = read_src("views/workspace/tabs/ScriptToolbar.vue")
    workflow = read_src("features/workspace/composables/useOutlineWorkflow.ts")

    assert "字数建议" not in toolbar
    assert "单集科研生成链路" not in toolbar
    assert "projectRules.word_count_per_episode" not in toolbar
    assert "{{ projectRules.scene_header_style" not in toolbar
    assert "审查本集" in toolbar
    assert "审查中..." in toolbar
    assert "规则/合规预检" in toolbar
    assert "rawText === '1080-1320'" in workflow
    assert "derivedRange.text" in workflow


def test_segment_review_panel_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/SegmentReviewPanel.vue")

    assert "SegmentReviewPanel" in workspace
    assert "AI 建议（可直接发给 AI 修改）" not in workspace
    assert "v-model:show-segment-panel" in workspace
    assert "AI 建议（可直接发给 AI 修改）" in panel
    assert "内部四段审阅" in panel
    assert "生成B版" in panel
    assert "generateVariant" in panel
    assert "@generate-variant" in workspace
    assert "defineEmits" in panel


def test_script_generation_ensures_episode_before_ai_writing():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    workflow_state = read_src("features/workspace/utils/workflowState.ts")

    assert "ensureScriptEpisodeReady" in workspace
    assert "runSegmentedWritingWithEpisode" in workspace
    assert '@generate-script="runSegmentedWritingWithEpisode"' in workspace
    assert '@generate-script="runQuickScriptWithEpisode"' not in workspace
    assert '@regenerate-step="_handleRegenerateConfirmationStep"' in workspace
    assert '@regenerate-step="runQuickScriptWithEpisode"' not in workspace
    assert "第${targetEp}集已自动建立，可以开始写作" in workspace
    assert "切集前自动保存" in workspace
    assert "分段草稿自动保存" in workspace
    assert "deleteEpisode" in workspace
    assert "delete (progress as Record<string, unknown>)[String(targetEp)]" in workspace
    assert "_hydrateSegmentProgressForEpisode" in workspace
    assert "script_segment_progress" in workspace
    assert "script_segment_progress" in workflow_state
    assert "final_generation_contract: Record<string, any>" in workflow_state
    assert "core_generation_contract_hash: string" in workflow_state
    assert "rag_evidence_hash: string" in workflow_state
    assert "final_generation_contract_hash: string" in workflow_state


def test_script_generation_checks_outline_gate_before_creating_or_switching_episode():
    workspace = read_src("views/ProjectWorkspaceView.vue")

    segmented_body = workspace.split("async function runSegmentedWritingWithEpisode", 1)[1].split("async function prepareNextEpisodeForWriting", 1)[0]
    next_body = workspace.split("async function prepareNextEpisodeForWriting", 1)[1].split("async function runNextEpisodeSegmentedWriting", 1)[0]

    assert "const target = _startSegmentedGenerationTarget(selectedEpisode.value, selectedScene.value)" in segmented_body
    assert segmented_body.index("ensureOutlineGatePassed({ episodeLimit: target.episodeNo })") < segmented_body.index("ensureScriptEpisodeReady(target.episodeNo)")
    assert next_body.index("persistCurrentScriptContent") < next_body.index("ensureOutlineGatePassed({ episodeLimit: nextEp })")
    assert next_body.index("ensureOutlineGatePassed({ episodeLimit: nextEp })") < next_body.index("ensureScriptEpisodeReady(nextEp)")
    assert "async function runQuickScriptWithEpisode" not in workspace
    assert "async function runNextEpisodeQuickWriting" not in workspace
    assert "prepareNextEpisodeForWriting('quick')" not in workspace


def test_script_scene_status_panel_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/ScriptSceneStatusPanel.vue")

    assert "ScriptSceneStatusPanel" in workspace
    assert "本场角色：" not in workspace
    assert "全剧契约" not in workspace
    assert "本集角色：" in panel
    # 4 张工作流指标卡片现已隐藏（用户不关心），但 prop 类型保留
    assert "workflowChainStatus" in panel
    assert "defineEmits" in panel


def test_director_writer_generation_trace_is_visible_and_persisted():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/ScriptSceneStatusPanel.vue")
    workflow_state = read_src("features/workspace/utils/workflowState.ts")
    stream = read_src("features/workspace/composables/useRuleBackedScriptStream.ts")

    assert "_currentDirectorBlueprintPacket" in workspace
    assert "...directorBlueprintPacket" in workspace
    assert "director_generation_trace" in workspace
    assert "latestDirectorGenerationTrace" in workspace
    assert "generation_trace" in stream
    assert "director_blueprint" in workflow_state
    assert "director_blueprints" in workflow_state
    assert "director_generation_trace" in workflow_state
    assert "后台生成记录" not in panel
    assert "本次生成记录已保存" not in panel
    assert "用户改稿接续记录" not in panel
    assert "生成失败记录" not in panel
    assert "模型链路记录" not in panel
    assert "总导演模板" not in panel
    assert "写手成稿" not in panel
    assert "质量复核" not in panel
    assert "DeepSeek" not in panel
    assert "Kimi" not in panel


def test_rag_evidence_history_panel_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/RagEvidenceHistoryPanel.vue")
    workflow_state = read_src("features/workspace/utils/workflowState.ts")

    assert "RagEvidenceHistoryPanel" in workspace
    assert 'v-if="showRagEvidenceDiagnostics"' in workspace
    assert ":logs=\"ragEvidenceLogs\"" in workspace
    assert "ragEvidenceLogs" in workspace
    assert "RAG_EVIDENCE_LOG_MAX" in workspace
    assert "export const RAG_EVIDENCE_LOG_MAX = 24" in workflow_state
    assert "参考素材历史" in panel
    assert "当前集" in panel
    assert "全部来源" in panel
    assert "全部文档" in panel
    assert "全部用途" in panel
    assert "清除筛选" in panel
    assert "知识召回历史" not in panel
    assert "全部槽位" not in panel
    assert "Dify" not in panel
    assert "本地知识分块" not in panel
    assert "filteredLogs" in panel
    assert "visibleLogs" in panel
    assert "docTypeFilter" in panel
    assert "injectTargetFilter" in panel
    assert "formatInjectTarget" in panel
    assert "logEvidenceCount" in panel
    assert "itemEvidenceCount" in panel
    assert "resetFilters" in panel
    assert "defineProps" in panel


def test_script_editor_panel_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/ScriptEditorPanel.vue")

    assert "ScriptEditorPanel" in workspace
    assert "开始写作这个场景" not in workspace
    assert "进入分镜提示词" not in workspace
    assert "开始写作这一集" in panel
    assert "进入分镜提示词" in panel
    assert "生成第${selectedEpisode + 1}集" in panel
    assert "选择第{{ selectedEpisode + 1 }}集写作方式" not in panel
    assert "快写下一集" not in panel
    assert "分段精写下一集" not in panel
    assert "fixed bottom-16 left-4 right-4 z-[80]" not in panel
    assert "sm:absolute sm:bottom-full sm:left-auto sm:right-0" not in panel
    assert "generateNextEpisodeResearch" in panel
    assert "generateNextEpisodeQuick" not in panel
    assert "@generate-next-episode-research" in workspace
    assert "@generate-next-episode-quick" not in workspace
    assert "@generate-next-episode-segmented" not in workspace
    assert "@generate-next-episode=" not in workspace
    assert "runNextEpisodeSegmentedWriting" in workspace
    assert "prepareNextEpisodeForWriting" in workspace
    assert "activeTab === 'script'" in workspace
    assert "relative inset-auto z-auto shadow-none" in workspace
    assert "const liveIncomplete = _hasSegmentedWritingProgress() && !segmentSteps.value.every(step => step.status === 'confirmed')" in workspace
    assert "return liveIncomplete || _hasStoredIncompleteSegmentProgress(selectedEpisode.value)" in workspace
    assert "&& !isSegmentedDraftIncomplete.value" in workspace
    assert ':is-segmented-draft-incomplete="isSegmentedDraftIncomplete"' in workspace
    assert "isSegmentedDraftIncomplete?: boolean" in panel
    assert "当前集未完成，确认四段后再生成下一集" in workspace
    assert "nextEpisodeGateMessage" in panel
    assert "defineEmits" in panel


def test_script_word_count_confirmation_is_user_controlled():
    workspace = read_src("views/ProjectWorkspaceView.vue")

    assert "_confirmWordCountIssueOnce" in workspace
    assert "_isWordCountIssue" in workspace
    assert "确定：接受当前字数，不因字数打回重写。" in workspace
    assert "取消：不放行，返回页面手动调整或重新生成。" in workspace
    assert "autoFixRuleBackedScript(requestPayload)" in workspace


def test_full_script_generation_does_not_hide_autofix_chain_by_default():
    workspace = read_src("views/ProjectWorkspaceView.vue")

    assert "async function ensureScriptInternallyApproved(options?: { silent?: boolean; deepAudit?: boolean; allowAutoFix?: boolean })" in workspace
    assert "if (!options?.allowAutoFix) {\n    return false\n  }\n\n  try {\n    const { data } = await adminConfigApi.autoFixRuleBackedScript(_buildScriptValidationRequest())" in workspace
    assert "ensureScriptInternallyApproved({ silent: true, allowAutoFix: false })" in workspace
    assert "ensureScriptInternallyApproved({ silent: true, deepAudit, allowAutoFix: false })" in workspace


def test_segment_confirmation_does_not_hide_autofix_chain_by_default():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    segmented = read_src("features/workspace/composables/useSegmentedWriting.ts")

    assert "allowAutoFix?: boolean" in workspace
    assert "if (!options?.allowAutoFix) {" in workspace
    assert "return false\n  }\n\n  try {\n    const { data } = await adminConfigApi.autoFixRuleBackedScript(requestPayload)" in workspace
    assert "approveSegment: idx => ensureSegmentInternallyApproved(idx, { silent: true, allowAutoFix: false })" in workspace
    assert "if (!options?.allowAutomaticSegmentPatch) {\n      step.status = 'reviewing'" in segmented
    assert "return\n    }\n\n    if (step.repairAttempts < 1) {" in segmented


def test_segment_generation_uses_remaining_episode_budget():
    workspace = read_src("views/ProjectWorkspaceView.vue")

    policy_body = workspace.split("function _resolveRequestLengthPolicy", 1)[1].split("function _buildEpisodeDraftContent", 1)[0]
    assert "const currentSegmentIndex = SEGMENT_DEFS.findIndex(item => item.id === options.segmentId)" in policy_body
    assert "const remainingSegments = Math.max(1, SEGMENT_DEFS.length - currentSegmentIndex)" in policy_body
    assert "const remainingMax = Math.max(0, episodePolicy.max - existingCount)" in policy_body
    assert "const minimumViableSegmentChars = Math.max(180, Math.round(segmentDef.target * 0.72))" in policy_body
    assert "const cappedSegmentMax = Math.min(" in policy_body
    assert "segmentDef.target + 80" in policy_body
    assert "Math.max(minimumViableSegmentChars, Math.floor(remainingMax / remainingSegments))" in policy_body
    assert "const cappedSegmentTarget = Math.min(" in policy_body
    assert "Math.max(minimumViableSegmentChars, Math.floor(remainingTarget / remainingSegments))" in policy_body
    assert "segment_existing_chars: lengthPolicy?.existingCount" in workspace
    assert "segment_remaining_chars_max: lengthPolicy?.remainingMax" in workspace


def test_script_health_panel_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/ScriptHealthPanel.vue")

    assert "ScriptHealthPanel" in workspace
    assert "状态与健康" not in workspace
    assert "头部质量门禁" not in workspace
    assert "状态与健康" in panel
    assert "头部质量门禁" in panel
    assert "defineEmits" in panel


def test_storyboard_export_and_floating_graph_are_extracted():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    floating_graph = read_src("views/workspace/panels/FloatingCharacterGraph.vue")
    storyboard_tab = read_src("views/workspace/tabs/StoryboardTab.vue")
    export_tab = read_src("views/workspace/tabs/ExportTab.vue")

    assert "FloatingCharacterGraph" in workspace
    assert "StoryboardTab" in workspace
    assert "ExportTab" in workspace
    assert "角色关系图谱" not in workspace
    assert "导出你的作品" not in workspace
    assert "角色关系图谱" in floating_graph
    assert "StoryboardPanel" in storyboard_tab
    assert "导出你的作品" in export_tab
    assert "copyExportLocked" in workspace
    assert "@copy.capture=\"preventCopyExport\"" in workspace
    assert "guardedExportProject" in workspace
    assert "refreshUserPermissionSnapshot" in workspace
    assert "auth.refreshUserSession()" in workspace
    assert "tab === 'export' || tab === 'storyboard'" in workspace
    assert "当前密钥未开启复制导出权限" in export_tab


def test_workspace_header_is_extracted_from_project_workspace():
    workspace = read_src("views/ProjectWorkspaceView.vue")
    header = read_src("views/workspace/panels/WorkspaceHeader.vue")

    assert "WorkspaceHeader" in workspace
    assert "<header" not in workspace
    assert "AI助手" in header
    assert "showAiPanel" in header
    assert ':show-ai-panel="activeTab !== \'chat\'"' in workspace
    assert 'v-if="aiPanelOpen && activeTab !== \'chat\'"' in workspace
    assert "defineEmits" in header


def test_workspace_deep_watches_do_not_synchronously_write_localstorage():
    """守住编辑器卡顿优化：deep watch 里 localStorage.setItem 必须在 setTimeout 内。

    曾经把 JSON.stringify + localStorage.setItem 放在 deep watch 顶层，
    每次按键都同步阻塞主线程，造成可见卡顿。
    """
    # characters 的 watch 在 useCharacterTab；
    # storyStateCards 的 watch 已搬到 useStoryStateAutosave。
    char_tab = read_src("features/workspace/composables/useCharacterTab.ts")
    autosave = read_src("features/workspace/composables/useStoryStateAutosave.ts")

    for source_label, source, marker in [
        ("useCharacterTab", char_tab, "watch(characters,"),
        ("useStoryStateAutosave", autosave, "watch(opts.storyStateCards,"),
    ]:
        idx = source.find(marker)
        assert idx >= 0, f"{source_label} 中找不到 {marker}"
        end = source.find("}, { deep: true })", idx)
        assert end >= 0, f"{source_label}.{marker} 缺 deep watch 结束"
        block = source[idx:end]
        for line_no, line in enumerate(block.splitlines(), start=1):
            if "localStorage.setItem" in line:
                preceding = "\n".join(block.splitlines()[:line_no])
                assert "setTimeout(" in preceding, (
                    f"{source_label} 中 {marker} 区段: localStorage.setItem 不在 setTimeout 内"
                )


def test_story_state_cards_crud_composable_extracted():
    """守住 storyStateCards CRUD 已抽到 composable，主 View 不再内联这一套。"""
    cards = read_src("features/workspace/composables/useStoryStateCards.ts")
    view = read_src("views/ProjectWorkspaceView.vue")

    assert "export function useStoryStateCards(" in cards
    for fn in (
        "addStoryStateCard",
        "upsertStoryStateCard",
        "removeStoryStateCard",
        "toggleStateCardCharacter",
        "makeStateCard",
    ):
        assert f"function {fn}(" in cards, f"composable 缺 {fn}"
    # 主 View 不再内联这五个定义
    for fn in (
        "function _makeStateCard(",
        "function addStoryStateCard(",
        "function upsertStoryStateCard(",
        "function removeStoryStateCard(",
        "function toggleStateCardCharacter(",
    ):
        assert fn not in view, f"主 View 不应再内联 {fn}"
    assert "useStoryStateCards({" in view


def test_story_state_autosave_composable_extracted():
    """守住 storyStateCards / workflowContext 的 debounce 写库已抽到 composable，
    主 View 不再直接 watch 这些 ref（避免 3000 行的 view 文件越长越胖）。
    """
    autosave = read_src("features/workspace/composables/useStoryStateAutosave.ts")
    view = read_src("views/ProjectWorkspaceView.vue")

    assert "export function useStoryStateAutosave(" in autosave
    assert "watch(opts.storyStateCards" in autosave
    assert "watch(\n    [opts.workflowContext, opts.canonPacket, opts.episodeMemoryCards]" in autosave \
        or "watch([opts.workflowContext, opts.canonPacket, opts.episodeMemoryCards]" in autosave \
        or "watch(\n    [opts.workflowContext" in autosave
    # 主 View 不再内联这两个 watch
    assert "watch(storyStateCards," not in view, "主 View 不应再内联 storyStateCards 的 watch"
    assert "watch([workflowContext, canonPacket, episodeMemoryCards]" not in view, (
        "主 View 不应再内联 workflowContext 的 watch"
    )
    # 必须挂上 composable
    assert "useStoryStateAutosave({" in view


def test_projects_pinia_store_exists_and_caches_list():
    """守住项目列表 pinia store —— 避免回退到组件本地 ref 状态，
    导致离开页面再回来列表消失。
    """
    store = read_src("stores/projects.ts")

    assert "defineStore('projects'" in store
    assert "fetchProjects" in store
    assert "isFresh" in store, "store 必须有缓存新鲜度判断"
    assert "lastFetchedAt" in store
    assert "upsertProject" in store
    assert "removeProject" in store


def test_projects_view_uses_projects_store():
    """守住 ProjectsView 通过 store 拿数据，而不是自己 ref<ProjectV2[]>([])"""
    view = read_src("views/ProjectsView.vue")

    assert "useProjectsStore" in view
    assert "projectsStore.fetchProjects" in view
    # 不应再有组件本地 projects ref
    assert "const projects = ref<ProjectV2[]>([])" not in view


def test_api_403_handler_guards_against_concurrent_redirects():
    """守住 http.ts 的 403 拦截不会被并发请求同时触发整页 reload。"""
    http_ts = read_src("api/http.ts")

    assert "_apiAuthRedirecting" in http_ts, (
        "api 拦截器必须有去重 flag，否则并发 403 会重复触发 window.location 跳转，"
        "把所有内存状态清空"
    )


def test_load_scenes_does_not_block_on_autosave():
    """切集时 autoSaveCurrentScene 必须 fire-and-forget，不能 await。

    否则点击分集卡顿，且 sceneContent 提前清空导致"内容一下消失"。
    实现已搬到 useEpisodeScenes composable。
    """
    composable = read_src("features/workspace/composables/useEpisodeScenes.ts")

    idx = composable.find("async function loadScenes(")
    assert idx >= 0, "useEpisodeScenes 缺 loadScenes"
    body = composable[idx:idx + 1200]

    assert "void autoSaveCurrentScene()" in body, (
        "loadScenes 必须用 void autoSaveCurrentScene() 后台保存，不能 await，"
        "否则切集会因为等保存接口而卡顿"
    )
    assert "await autoSaveCurrentScene()" not in body, (
        "loadScenes 内仍有 await autoSaveCurrentScene()，会卡顿"
    )

    assert "_loadScenesToken" in composable, (
        "缺竞态保护：快速连点分集时，旧响应回包可能覆盖新选中集的内容"
    )


def test_select_scene_inline_handler_does_not_block_on_autosave():
    view = read_src("views/ProjectWorkspaceView.vue")
    assert 'await _autoSaveCurrentScene(); selectedScene' not in view, (
        "@select-scene 内联 handler 仍 await autosave，会让点场动作卡顿"
    )


def test_script_generation_uses_explicit_persist_for_critical_checkpoints():
    """主链路生成 / 内部四段审阅 / 下一集入口必须走显式保存，避免生成内容提示成功但未落库。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    draft = read_src("features/workspace/composables/useScriptDraftGeneration.ts")

    assert "async function persistCurrentScriptContent" in view
    assert "changeNote: '主链路生成自动保存'" in view
    assert "changeNote: '内部四段审阅完成'" in view
    assert "changeNote: '分段确认自动保存'" in view
    assert "changeNote: '进入下一集前保存'" in view
    assert "AI生成已写入编辑器，但自动保存失败" in draft


def test_persist_script_content_prepares_episode_and_scene_before_saving():
    """用户直接点击保存时，也必须先确保 Episode/Scene 已存在，不能只在生成入口做准备。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    idx = view.find("async function persistCurrentScriptContent")
    assert idx >= 0
    body = view[idx:idx + 2200]

    assert "ensureScriptEpisodeReady(snapshotEp)" in body
    assert body.index("ensureScriptEpisodeReady(snapshotEp)") < body.index("projectsV2Api.saveSceneContent")


def test_persist_script_content_prepare_guard_prevents_autosave_recursion():
    """保存前准备分集/场景可能触发 loadScenes autosave，必须有递归保护。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    idx = view.find("async function persistCurrentScriptContent")
    assert idx >= 0
    body = view[idx:idx + 2400]

    assert "let isPreparingScriptPersistence = false" in view
    assert "if (!options?.skipEpisodeReadyCheck && !isPreparingScriptPersistence)" in body
    assert "isPreparingScriptPersistence = true" in body
    assert "finally" in body
    assert "isPreparingScriptPersistence = false" in body
    assert body.index("isPreparingScriptPersistence = true") < body.index("ensureScriptEpisodeReady(snapshotEp)")
    assert body.index("ensureScriptEpisodeReady(snapshotEp)") < body.index("projectsV2Api.saveSceneContent")


def test_script_save_marks_prior_manual_edit_consumed_before_recording_new_edit():
    """保存目标下一集时，先消费上一集人工改稿，再记录当前集新改稿。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    idx = view.find("async function persistCurrentScriptContent")
    assert idx >= 0
    body = view[idx:idx + 4200]

    assert "markManualEditGateConsumed(manualEditBeforeSaveRecord, snapshotEp" in body
    assert body.index("markManualEditGateConsumed(manualEditBeforeSaveRecord, snapshotEp") < body.index("_recordManualEditContext(")


def test_manual_edit_context_records_model_candidate_snapshot_and_tail_delta():
    view = read_src("views/ProjectWorkspaceView.vue")

    assert "_recordModelCandidateSnapshot" in view
    assert "model_candidate_snapshot" in view
    assert "manual_edit_evidence" in view
    assert "head_excerpt" in view
    assert "tail_excerpt" in view
    assert "manual_added_excerpt" in view
    assert "manual_removed_excerpt" in view
    assert "previous_candidate_hash" in view
    assert "saved_content_hash" in view


def test_manual_edit_context_stays_internal_after_user_page_cleanup():
    view = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/ScriptSceneStatusPanel.vue")

    assert "must_read_manual_edit" in view
    assert "manual_edit_context" in view
    assert "用户改稿接续记录" not in panel
    assert "上一集用户定稿已作为" not in panel


def test_candidate_snapshot_can_restore_after_refresh_without_canon_save():
    view = read_src("views/ProjectWorkspaceView.vue")
    settings = read_src("api/modules/settings.ts")

    assert "function _restoreCandidateSnapshotIfEditorBlank" in view
    assert "_modelCandidateSnapshot(episodeNo, sceneNo)" in view
    assert "候选稿已恢复到编辑器，请确认后保存" in view
    assert "async function _restoreLatestJobCandidateIfEditorBlank" in view
    assert "getLatestRuleBackedScriptJob" in view
    assert "后台候选稿已恢复到编辑器，请确认后保存" in view
    assert "script-scene/jobs/latest" in settings
    assert "changeNote: '候选稿刷新恢复'" not in view
    load_body = view.split("async function loadScriptEpisode", 1)[1].split("async function selectScriptScene", 1)[0]
    mounted_body = view.split("await ensureCurrentEpisodeExistingScriptVisible(selectedEpisode.value, { silent: true })", 1)[1].split("})", 1)[0]
    assert "_restoreCandidateSnapshotIfEditorBlank(episodeNumber)" in load_body
    assert "await _restoreLatestJobCandidateIfEditorBlank(episodeNumber)" in load_body
    assert "await _restoreLatestJobCandidateIfEditorBlank(selectedEpisode.value)" in mounted_body


def test_single_research_generation_path_keeps_internal_task_contract_clear():
    """用户只看到一条科研生成链路；内部任务合同仍要防止误入逐段确认或 A/B 双版本。"""
    view = read_src("views/ProjectWorkspaceView.vue")

    assert "research_generation_mode: true" in view
    assert "draft_mode: 'research_chain'" in view
    assert "research_chain_draft" in view
    assert "quick_write_mode: true" not in view
    assert "draft_mode: 'quick_write'" not in view
    assert "quick_write_draft" not in view
    assert "科研链路：按分步确认和最终生成合同写当前集" in view
    assert "如果当前集已有正文，就紧接现有正文继续写" in view
    assert "正文内部可以自然包含多场戏和多个场标" in view
    assert "不要进入需要用户逐段选择的并列流程" not in view
    assert "不要一次生成 A/B 双版本" in view
    assert "runQuickScriptWithEpisode" not in view
    assert "runNextEpisodeQuickWriting" not in view


def test_segmented_research_generation_uses_backend_job_for_auditable_model_tasks():
    """科研分段链路必须走后台任务，才能留下真实模型任务、RAG、合同 hash 和候选稿证据。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    stream = read_src("features/workspace/composables/useRuleBackedScriptStream.ts")
    settings = read_src("api/modules/settings.ts")

    assert "startRuleBackedScriptJob" in settings
    assert "getRuleBackedScriptJobStatus" in settings
    assert "async function _runRuleBackedScriptJob" in view
    assert "adminConfigApi.startRuleBackedScriptJob(requestPayload)" in view
    assert "adminConfigApi.getRuleBackedScriptJobStatus(jobId)" in view
    assert "_runRuleBackedScriptJob(requestPayload, onProgress)" in view
    assert "generateRuleBackedScriptStreamUrl()" not in view
    assert "streamRuleBackedScript({" not in view
    assert "fetch(url" in stream


def test_segmented_resume_restarts_empty_reviewing_step():
    """旧的空分段进度不能把用户卡在"等待确认"，必须重新生成当前段。"""
    segmented = read_src("features/workspace/composables/useSegmentedWriting.ts")

    reviewing_branch = segmented.split("if (step.status === 'reviewing')", 1)[1].split("if (step.status === 'error')", 1)[0]
    assert "!step.editedContent.trim()" in reviewing_branch
    assert "!step.versionA.trim()" in reviewing_branch
    assert "!step.versionB.trim()" in reviewing_branch
    assert "await segmentRetry(idx)" in reviewing_branch
    assert "return" in reviewing_branch


def test_backend_candidate_recovery_is_segment_scoped_and_restores_segment_card():
    """后台已有候选稿时，必须按当前四段恢复到四段卡，不能只恢复到正文或串到别的段。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    segmented = read_src("features/workspace/composables/useSegmentedWriting.ts")
    settings = read_src("api/modules/settings.ts")
    backend = (ROOT / "app" / "routers" / "short_drama" / "scene_routes.py").read_text(encoding="utf-8")

    assert "recoverLatestSegmentCandidate?: (idx: number, step: SegmentStep) => Promise<SegmentStreamResult | null | undefined>" in segmented
    assert "async function recoverLatestCandidateIntoSegment" in segmented
    assert "await recoverLatestCandidateIntoSegment(idx, 'stale_generating')" in segmented
    assert "await recoverLatestCandidateIntoSegment(idx, 'empty_reviewing')" in segmented
    assert "await recoverLatestCandidateIntoSegment(idx, 'error_resume')" in segmented

    assert "recoverLatestSegmentCandidate: (idx, step) => _restoreLatestRuleBackedSegmentCandidate(idx, step)" in view
    assert "async function _restoreLatestRuleBackedSegmentCandidate" in view
    assert "segment_id: String(step.id || '')" in view
    assert "return _ruleBackedJobStatusToSegmentResult(data, String(data.job_id || ''))" in view

    assert "segment_id?: string" in settings
    assert "segment_id: str = \"\"" in backend
    assert "_job_request_segment_id(job)" in backend


def test_latest_candidate_status_is_reused_by_polling_and_recovery():
    """轮询完成和刷新恢复必须使用同一套候选解析逻辑，避免一个路径成功另一路径空白。"""
    view = read_src("views/ProjectWorkspaceView.vue")

    assert "function _ruleBackedJobStatusToSegmentResult" in view
    polling_body = view.split("async function _runRuleBackedScriptJob", 1)[1].split("async function _restoreLatestRuleBackedSegmentCandidate", 1)[0]
    assert "_ruleBackedJobStatusToSegmentResult(latest, jobId)" in polling_body
    restore_body = view.split("async function _restoreLatestRuleBackedSegmentCandidate", 1)[1].split("function _loadSuggestionsAsync", 1)[0]
    assert "_ruleBackedJobStatusToSegmentResult(data, String(data.job_id || ''))" in restore_body


def test_segmented_progress_does_not_persist_empty_steps_over_saved_progress():
    """页面有正文但四段状态为空时，不能把空进度写回工作流上下文。"""
    workspace = read_src("views/ProjectWorkspaceView.vue")

    persist_body = workspace.split("function _persistCurrentSegmentProgress", 1)[1].split("async function _hydrateSegmentProgressForEpisode", 1)[0]
    assert "if (!snapshot.has_progress) return" in persist_body
    assert "if (!snapshot.has_progress && !snapshot.scene_content.trim()) return" not in persist_body
    assert "script_segment_progress: store" in persist_body


def test_manual_edit_context_replaces_latest_instead_of_deep_merging_stale_fields():
    """用户定稿承接记录必须整体替换，不能把旧 consumed 字段深合并进最新记录。"""
    workspace = read_src("views/ProjectWorkspaceView.vue")

    assert "function _setManualEditContext" in workspace
    assert "manual_edit_context: clonePlain(context)" in workspace
    assert "_deepMergeRecord(workflowContext.value, {\n    manual_edit_context:" not in workspace
    assert "_setManualEditContext(context)" in workspace
    assert "_setManualEditContext(next)" in workspace
    assert "_setManualEditContext(consumedManualEditContext)" in workspace


def test_load_scenes_shows_loading_indicator_for_cache_miss():
    """切集时若缓存未命中，必须立刻把 scenesLoading 打开（让用户看到"正在加载"），
    不再硬性要求清空 scenes/sceneContent —— 保留上一集内容更平滑（避免白屏一闪）。
    真实数据回包后由 applyScenesData 替换，token 守竞态。
    """
    composable = read_src("features/workspace/composables/useEpisodeScenes.ts")

    idx = composable.find("async function loadScenes(")
    assert idx >= 0
    body = composable[idx:idx + 1500]

    listscenes_at = body.find("await projectsV2Api.listScenes")
    pre_fetch = body[:listscenes_at]
    assert "scenesLoading.value = true" in pre_fetch, (
        "loadScenes 缓存未命中分支必须先把 scenesLoading 打开"
    )
    # 必须仍有 token 守卫，避免旧响应覆盖新场
    assert "_loadScenesToken" in body, "loadScenes 必须用 token 防竞态"


def test_settings_view_load_is_non_blocking_with_retry():
    """SettingsView onMounted 不能 await，否则后端慢会让整页空白。
    必须有 loadError + 重试按钮。
    """
    view = read_src("views/SettingsView.vue")
    assert "onMounted(() => { void loadSettings() })" in view, (
        "SettingsView onMounted 必须 fire-and-forget，不能 await，否则后端慢会让整页空白"
    )
    assert "loadError" in view, "SettingsView 缺 loadError 状态"
    assert "重试" in view and "@click=\"loadSettings\"" in view, "SettingsView 缺重试按钮"


def test_lab_view_surfaces_load_error_with_retry():
    """LabView 加载失败必须有可见提示和重试，不能静默失败。"""
    view = read_src("views/LabView.vue")
    assert "loadError" in view, "LabView 缺 loadError 状态"
    assert "@click=\"loadAITopics()\"" in view or "loadAITopics()" in view, "LabView 缺重试按钮"


def test_lab_to_outline_editor_prefills_query_contract():
    """Lab 去创作带的 query 必须被大纲分析器消费，不能丢用户选择。"""
    lab = read_src("views/LabView.vue")
    outline = read_src("views/OutlineEditorView.vue")
    assert "query: { logline: topic.title, type: topic.type }" in lab
    assert "query: { template: selectedCase.value.structure }" in lab
    assert "query: { logline: data.content.slice(0, 80) }" in lab
    assert "route.query.logline" in outline
    assert "route.query.type" in outline
    assert "route.query.template" in outline


def test_app_layout_setup_check_does_not_block_render():
    """AppLayout onMounted 调 setupApi 必须 then/catch 不阻塞，
    否则后端慢会让 layout 整体卡住。
    """
    view = read_src("views/AppLayout.vue")
    # 不应有顶层 await 调用 setupApi
    assert "await setupApi.status()" not in view, (
        "AppLayout onMounted 仍 await setupApi —— 后端慢时整 layout 都阻塞"
    )
    assert "setupApi.status()" in view  # 调用还在
    assert ".then(" in view  # 但用 then


def test_workspace_uses_projects_store_for_optimistic_render():
    """ProjectWorkspaceView 必须用 projectsStore 缓存先填顶部元数据，
    避免进编辑器秒级空白。回写 store 让列表保持新鲜。
    """
    view = read_src("views/ProjectWorkspaceView.vue")
    assert "useProjectsStore" in view, "缺 useProjectsStore 导入"
    assert "projectsStore.findById(projectId.value)" in view, (
        "进入工作台必须先尝试 findById 拿缓存"
    )
    assert "projectsStore.upsertProject(data)" in view, (
        "API 数据回来后必须 upsert 回 store"
    )


def test_autosave_only_runs_when_content_actually_changed():
    """autosave 必须有"脏标记"机制：内容和上次加载/保存的一致就跳过保存。
    实现在 useEpisodeScenes composable 里。
    """
    composable = read_src("features/workspace/composables/useEpisodeScenes.ts")
    assert "_lastSavedSceneContent" in composable, "缺脏标记 ref"
    assert "markSceneContentClean" in composable, "缺标记函数"
    assert "snapshotContent === _lastSavedSceneContent" in composable, (
        "autosave 必须先比对内容是否真的变了"
    )


def test_workspace_load_failure_keeps_cached_data_when_available():
    """有 store 缓存时，项目接口失败不强制跳转，让用户继续浏览缓存。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    assert "if (!cached) {" in view, "项目加载失败时应根据 cached 决定是否跳转"
    assert "项目不存在或已被删除" in view, "404 应明确提示"


def test_health_panel_is_rendered_off_for_user_but_data_flow_preserved():
    """状态健康面板对用户隐藏（v-if=false），但 computed/ref 仍被代码引用。
    恢复显示只需把 v-if 去掉即可，不需要再接 props。
    """
    view = read_src("views/ProjectWorkspaceView.vue")
    # 渲染关闭
    assert 'v-if="false"' in view, "ScriptHealthPanel 必须 v-if=false 隐藏"
    # 但还在 import + props 都还在（数据通路保留）
    assert "ScriptHealthPanel" in view
    assert ":character-health=\"characterHealth\"" in view
    assert ":script-deep-audit=\"scriptDeepAudit\"" in view


def test_real_progress_percent_uses_episode_completion():
    """顶部进度条改成真实写作进度（按集 completed_scenes/total_scenes 加权）。
    不再用早期 useWorkspaceTabs 的"Tab 走过几个"伪进度。
    """
    view = read_src("views/ProjectWorkspaceView.vue")
    assert "realProgressPercent" in view
    assert ":progress-percent=\"realProgressPercent\"" in view
    assert "completed_scenes" in view, "进度计算必须读 completed_scenes"
    assert "refreshEpisodesSilently" in view, "保存后必须刷新 episodes 让进度条跟进"


def test_project_cards_show_backend_episode_progress():
    """项目卡片进度必须展示后端回传的已完成集数，不只显示静态百分比。"""
    view = read_src("views/ProjectsView.vue")
    assert "getCompletedEpisodes(project)" in view
    assert "getProjectTotalEpisodes(project)" in view
    assert "completed_episodes" in view
    assert "创作进度" in view
    assert "写作中" in view


def test_status_panel_metric_cards_hidden_from_user():
    """ScriptSceneStatusPanel 的 4 张指标卡片对用户隐藏。
    workflowChainStatus props 保留，AI 生成时仍要用。
    """
    panel = read_src("views/workspace/tabs/ScriptSceneStatusPanel.vue")
    assert "全剧契约" not in panel, "全剧契约卡片必须从 UI 移除"
    assert "当前窗口" not in panel, "当前窗口卡片必须从 UI 移除"
    assert "RAG卡片" not in panel, "RAG卡片必须从 UI 移除"
    assert "打磨问题" not in panel, "打磨问题卡片必须从 UI 移除"
    # 但 prop 类型仍保留（数据通路给 AI 生成用）
    assert "workflowChainStatus" in panel


def test_rag_evidence_diagnostics_hidden_from_normal_script_ui():
    """参考素材记录是调试/验收信息，普通用户写作界面默认不展示。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    panel = read_src("views/workspace/tabs/ScriptSceneStatusPanel.vue")

    assert "showRagEvidenceDiagnostics" in view
    assert "route.query.debug === 'rag'" in view
    assert ":show-rag-evidence=\"showRagEvidenceDiagnostics\"" in view
    assert "props.showRagEvidence && evidenceItems.length" in panel
    assert "{{ item.inject_as }}" not in panel
    assert "formatSourcePath(source.source_path)" not in panel
    assert "#{{ source.chunk_index }}" not in panel
    assert "知识召回证据" not in panel
    assert "Dify" not in panel
    assert "本地知识分块" not in panel


def test_scenes_in_memory_cache_for_instant_episode_switch():
    """切集必须用内存缓存做秒切，不能每次都打 API。
    实现在 useEpisodeScenes composable 里。
    """
    composable = read_src("features/workspace/composables/useEpisodeScenes.ts")
    assert "_scenesByEpCache" in composable, "缺切集内存缓存"
    assert "prefetchAdjacentScenes" in composable, "缺邻集预热"
    assert "invalidateScenesCache" in composable, "缺缓存失效"
    assert "refreshScenesInBackground" in composable, "缺后台静默刷新"


def test_scene_prefetch_uses_batch_api():
    """后台预热应批量取场景，避免大项目打开后串行请求多集。"""
    composable = read_src("features/workspace/composables/useEpisodeScenes.ts")
    api = read_src("api/modules/projects.ts")

    assert "listScenesBatch" in api, "projects API 缺批量场景接口"
    assert "projectsV2Api.listScenesBatch" in composable, "场景预热必须优先用批量接口"
    assert "prefetchScenesBatch" in composable, "缺批量预热封装"
    assert "_scenesPrefetchInFlight" in composable, "批量预热必须记录 in-flight，避免重复预热同一集"
    prefetch_idx = composable.find("async function prefetchInitialScenes")
    assert prefetch_idx >= 0
    prefetch_body = composable[prefetch_idx:prefetch_idx + 700]
    assert "setTimeout" not in prefetch_body, "初始预热不应再靠 setTimeout 串行拖慢"


def test_episode_scene_loading_aborts_stale_requests_and_bounds_cache():
    """切集请求必须可取消，场景缓存必须有上限。

    大项目里用户快速切集时，旧 listScenes 请求不应继续占用前端状态通道；
    预热缓存也不能随着集数无限增长。
    """
    composable = read_src("features/workspace/composables/useEpisodeScenes.ts")
    api = read_src("api/modules/projects.ts")

    assert "options?: { signal?: AbortSignal }" in api, "listScenes 必须透传 AbortSignal"
    assert "signal: options?.signal" in api, "axios 请求必须接收 signal"

    assert "MAX_SCENE_CACHE_EPISODES" in composable, "场景缓存必须有明确上限"
    assert "function trimScenesCache()" in composable, "缺缓存上限裁剪函数"
    assert "_activeLoadScenesController?.abort()" in composable, "切集时必须中止上一轮未完成请求"
    assert "new AbortController()" in composable, "缺单集加载 AbortController"
    assert "{ signal: controller.signal }" in composable, "listScenes 必须携带当前 signal"
    assert "controller.signal.aborted" in composable, "旧请求返回后必须再次检查 signal"
    assert "onUnmounted(() =>" in composable, "组件卸载时必须清理未完成请求"
    assert "_disposed" in composable, "异步回包必须有卸载态保护"


def test_episode_scenes_logic_extracted_to_composable():
    """守住集 / 场 / 缓存 / autosave 已抽到 useEpisodeScenes composable，
    主组件不再直接管理这些底层状态机制。
    """
    view = read_src("views/ProjectWorkspaceView.vue")
    assert "useEpisodeScenes" in view, "ProjectWorkspaceView 必须使用 useEpisodeScenes composable"
    # 主组件中不应再有 loadScenes / autoSaveCurrentScene 等函数体定义
    assert "async function loadScenes(" not in view, (
        "loadScenes 必须在 composable 里，主组件不应再有定义"
    )
    assert "async function _autoSaveCurrentScene(" not in view, (
        "_autoSaveCurrentScene 必须在 composable 里"
    )
    assert "const _scenesByEpCache" not in view, (
        "_scenesByEpCache 必须在 composable 里"
    )


def test_storyboard_tab_renamed_to_prompt_words():
    """分镜预览 → 分镜提示词。明确不生图/生视频，只产文字提示词。"""
    tabs = read_src("features/workspace/composables/useWorkspaceTabs.ts")
    assert "分镜提示词" in tabs
    assert "分镜预览" not in tabs

    panel = read_src("components/workshop/StoryboardPanel.vue")
    assert "分镜提示词" in panel, "面板标题应使用新名"
    assert "本系统不生成图像或视频" in panel, "应明确告诉用户不出图/不出视频"
    assert "LLM 未联通，请联系管理员" in panel
    assert "config.yaml" not in panel, "LLM 失败态不应把配置细节暴露给普通用户"
    assert "未锁定角色" not in panel, "分镜页不再展示黄色资格详情框"


def test_storyboard_episode_follows_script_episode_on_tab_enter():
    """切到分镜 Tab 时，storyboardEpisode 自动同步到 selectedEpisode。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    assert "tab === 'storyboard'" in view
    assert "storyboardEpisode.value = selectedEpisode.value" in view


def test_user_sidebar_does_not_expose_legacy_advanced_generation_entry():
    """前台只保留项目工作区正式科研链路，不再给用户单独暴露旧高级生成入口。"""
    layout = read_src("views/AppLayout.vue")
    router = read_src("router/index.ts")

    assert "to=\"/advanced-generation\"" not in layout
    assert ":to=\"advancedMenuItem.path\"" not in layout
    assert "auth.advancedGenerationEnabled" not in layout
    assert "path: 'advanced-generation'" in router
    assert "redirect: '/projects'" in router
    assert "AdvancedGenerationView.vue" not in router


def test_root_path_requires_access_key_entry_instead_of_auto_projects_redirect():
    """根域名必须进入密钥入口，已有登录态也不能直接跳项目页。"""
    router = read_src("router/index.ts")

    assert "path: '/',\n      redirect: '/login'," in router
    assert router.index("redirect: '/login'") < router.index("component: () => import('@/views/AppLayout.vue')")
    assert "path: '',\n          redirect: '/projects'" not in router
    assert "to.name === 'login' && auth.isAuthenticated" not in router
    assert not (WEBUI / "views" / "HomeView.vue").exists()


def test_step_confirmation_candidate_save_triggers_real_save_and_clear_labels():
    """正文候选确认必须触发真实保存，重生成按钮保持当前步骤语义。"""
    panel = read_src("views/workspace/tabs/ScriptStepConfirmationPanel.vue")
    workspace = read_src("views/ProjectWorkspaceView.vue")

    assert "saveCandidate" in panel
    assert "emit('saveCandidate')" in panel
    assert '@save-candidate="_handleStepCandidateSave"' in workspace
    assert "async function _handleStepCandidateSave()" in workspace
    assert "await saveScript()" in workspace
    assert "重新生成本步" in panel
    assert "重新生成本集" not in panel
    assert "function _clearCandidatePendingStatusAfterSave()" in workspace


def test_sidebar_shows_loading_indicator_during_episode_switch():
    """sidebar 切集时必须有 loading 视觉反馈。"""
    sidebar = read_src("views/workspace/tabs/ScriptSidebar.vue")
    assert "scenesLoading" in sidebar
    assert "Loader2" in sidebar


def test_heavy_script_watchers_gated_by_active_tab():
    """重 watcher（角色识别/规则校验/字数分析）必须在非剧本 Tab 上跳过，
    避免大纲/角色/分镜 Tab 上 sceneContent 改动也触发不必要的 CPU 开销。
    """
    view = read_src("views/ProjectWorkspaceView.vue")
    assert "_isScriptTabActive" in view, "缺剧本 Tab 活跃门控"
    # 三个重 watcher 必须用门控
    assert view.count("if (!_isScriptTabActive.value) return") >= 3, (
        "至少 3 个重 watcher（角色识别/规则校验/字数分析）必须门控"
    )
    assert "_characterDetectionCatalogSignature" in view
    assert "_lastCharacterDetectionSignature" in view
    assert "_scriptValidationInFlight" in view
    assert "_lastQueuedRuleValidationKey" in view
    assert "currentCacheKey !== cacheKey" in view, "规则校验旧响应不能覆盖新正文诊断"
    assert "requestPayload?: ReturnType<typeof _buildScriptValidationRequest>" in view


def test_ai_generation_errors_use_structured_payload():
    """AI 生成失败时必须读取后端结构化错误。

    用户页只保留业务级失败原因；内部 detail/suggestion 写入后台记录，
    不能把模型链路细节直接展示给用户。
    """
    draft = read_src("features/workspace/composables/useScriptDraftGeneration.ts")
    assert "formatRuleBackedScriptStreamError" in draft
    assert "public_detail: PUBLIC_BLOCKED_DETAIL" in draft
    assert "public_suggestion: PUBLIC_BLOCKED_SUGGESTION" in draft
    view = read_src("views/ProjectWorkspaceView.vue")
    # 多个 AI/接口入口都接入
    assert view.count("notifyApiError") >= 5


def test_generation_failure_reason_remains_visible_on_page():
    """主链路生成失败不能只靠短暂 toast；页面状态区必须保留失败原因，避免用户误以为吞稿。"""
    draft = read_src("features/workspace/composables/useScriptDraftGeneration.ts")
    assert "scriptStreamStatus.value = PUBLIC_BLOCKED_DETAIL" in draft
    assert "scriptStreamStatus.value = [\n          PUBLIC_CANDIDATE_DETAIL," in draft
    assert "scriptStreamStatus.value = ''\n      const info = formatRuleBackedScriptStreamError(e)" not in draft
    assert "research_chain_job_timeout" in draft
    assert "quick_write_stream_timeout" not in draft
    assert "startScriptJob" in draft
    assert "getScriptJobStatus" in draft
    assert "pollScriptJobUntilReady" in draft
    assert "startRuleBackedScriptJob" in read_src("views/ProjectWorkspaceView.vue")
    assert "getRuleBackedScriptJobStatus" in read_src("views/ProjectWorkspaceView.vue")
    assert "recordGenerationFailure" in draft
    assert "生成超过10分钟仍未返回正文，本次已自动停止，没有保存空内容" in draft
    assert "生成超过4分钟仍未返回正文，本次已自动停止，没有保存空内容" not in draft
    assert "single_episode_target_ms: SCRIPT_DRAFT_EPISODE_TARGET_MS" in draft
    assert "single_episode_timeout_ms: SCRIPT_DRAFT_STREAM_TIMEOUT_MS" in draft


def test_script_editor_marks_unsaved_manual_changes_without_showing_manual_log():
    view = read_src("views/ProjectWorkspaceView.vue")
    editor = read_src("views/workspace/tabs/ScriptEditorPanel.vue")
    panel = read_src("views/workspace/tabs/ScriptSceneStatusPanel.vue")

    assert ':has-unsaved-changes="hasUnsavedSceneChanges()"' in view
    assert ':manual-edit-markers="manualEditLineMarkers"' in view
    assert "lastSavedSceneContent" in view
    assert "hasUnsavedChanges" in editor
    assert "manualEditMarkers" in editor
    assert "人工修改标记" in editor
    assert "border-amber-300" in editor
    assert "用户改稿接续记录" not in panel


def test_legacy_tasks_page_removed_and_logs_are_bounded():
    """旧任务页不再保留源码；日志页仍必须有有界渲染和服务端分页。"""
    router = read_src("router/index.ts")
    logs = read_src("views/LogsView.vue")

    assert not (ROOT / "webui" / "src" / "views" / "TasksView.vue").exists()
    assert "path: 'tasks'" in router
    assert "redirect: '/projects'" in router

    assert "const PAGE_SIZE = 20" in logs
    assert "visibleLogItems" in logs
    assert "page_size: PAGE_SIZE" in logs
    assert "v-for=\"(log, idx) in visibleLogItems\"" in logs


def test_chat_brainstorm_extracted_to_composable():
    """聊天脑暴 Tab 状态机搬到 useChatBrainstorm composable。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    composable = read_src("features/workspace/composables/useChatBrainstorm.ts")

    assert "useChatBrainstorm" in view
    # 主组件不再有内联 chatMessages ref
    assert "const chatMessages = ref<" not in view
    assert "async function sendChatMessage(" not in view
    # composable 提供核心函数
    assert "sendChatMessage" in composable
    assert "generateOutlineFromChat" in composable
    assert "bootstrapFromQueryPrompt" in composable


def test_character_tab_extracted_to_composable():
    """角色 Tab 状态机搬到 useCharacterTab composable。"""
    view = read_src("views/ProjectWorkspaceView.vue")
    composable = read_src("features/workspace/composables/useCharacterTab.ts")

    assert "useCharacterTab" in view
    # 主组件不再有内联 characters ref
    assert "const characters = ref<" not in view
    assert "function addCharacter(char: any) {\n  characters.value.push" not in view
    # composable 提供核心函数
    assert "addCharacter" in composable
    assert "addRelationship" in composable
    assert "ROLE_COLORS" in composable
    # 持久化 watch 必须在 composable 内
    assert "watch(characters" in composable
    assert "saveCharacters" in composable
