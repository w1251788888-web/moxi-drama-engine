from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_normal_chat_has_no_local_phrase_or_outline_routing():
    source = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()
    send_body = source.split("async function sendChatMessage", 1)[1].split(
        "async function generateOutlineFromChat", 1
    )[0]

    assert "callUserAiChatWithRetry" in send_body
    assert "buildChatContextPacket" in send_body
    assert "_isCompleteOutlineInput" not in send_body
    assert "_isExplicitOutlinePacketRequest" not in send_body
    assert "assessPastedOutlineInput" not in send_body
    assert "classifyOutlineCandidateSource" not in send_body
    assert "_isStageConfirmationInput" not in send_body
    assert "_applyExplicitFormatChoice" not in send_body
    assert "_shouldAskFormatBeforeTopic" not in send_body
    assert "_buildLocalTopicFeedback" not in send_body
    assert "_syncStandardOutlinePacketCandidate" not in send_body


def test_backend_chat_does_not_infer_hidden_workflow_from_user_words():
    source = (ROOT / "app/routers/admin_config.py").read_text()
    response_body = source.split("async def generate_ai_chat_response", 1)[1].split(
        '@router.post("/ai/chat"', 1
    )[0]

    assert "_is_outline_framework_request" not in response_body
    assert "keyword in normalized" not in source


def test_chat_page_uses_real_workspace_ratio_and_editor_confirmation_sidebar():
    chat_tab = (ROOT / "webui/src/views/workspace/tabs/ChatTab.vue").read_text()
    panel = (ROOT / "webui/src/views/workspace/panels/OutlineConfirmationPanel.vue").read_text()
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()

    placeholder = "聊天脑暴负责选题和创作探讨。自然语言直接发给大模型；只有右侧明确确认的内容才进入大纲资料。"
    assert f'placeholder="{placeholder}"' in chat_tab
    assert "聊天脑暴只负责选题和创作探讨，并会整理标准大纲资料包。" not in chat_tab
    assert 'accept=".docx,.md,.markdown,.txt"' in chat_tab
    assert "'upload-reference': [file: File]" in chat_tab
    assert "上传剧本" in chat_tab

    assert 'class="w-72 xl:w-80' in panel
    assert "OUTLINE_EDITOR_CONFIRMATION_SECTIONS" in panel
    assert "确认本项" in panel
    assert "<details" in panel

    chat_block = workspace.split('<template v-if="activeTab === \'chat\'">', 1)[1].split(
        "</template>", 1
    )[0]
    assert 'class="flex-1 min-w-0 flex overflow-hidden"' in chat_block
    assert "<OutlineConfirmationPanel" in chat_block
    assert '@upload-reference="handleChatReferenceUpload"' in chat_block


def test_uploaded_script_is_reference_only_and_never_auto_confirms_outline():
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    composable = (ROOT / "webui/src/features/workspace/composables/useChatBrainstorm.ts").read_text()
    handler = workspace.split("async function handleChatReferenceUpload", 1)[1].split(
        "async function", 1
    )[0]
    reference_body = composable.split("async function sendChatReferenceDocument", 1)[1].split(
        "async function bootstrapFromQueryPrompt", 1
    )[0]

    assert "projectsV2Api.extractOutlineFile(file)" in handler
    assert "sendChatReferenceDocument" in handler
    assert "confirmOutlineEditorSection" not in handler
    assert "standardOutlinePacket.value =" not in handler
    assert "outlineData.value =" not in handler
    assert "outlineCharacters.value =" not in handler
    assert "【上传剧本参考：" in reference_body
    assert "【剧本参考摘要（AI 整理，需核对）：" in reference_body
    assert reference_body.index("role: 'user'") < reference_body.index("role: 'ai'")
    assert "standardOutlinePacket" not in reference_body
    assert "onOutlineGenerated" not in reference_body


def test_upload_extraction_locks_chat_controls_and_reports_rejected_handoff():
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    chat_tab = (ROOT / "webui/src/views/workspace/tabs/ChatTab.vue").read_text()
    panel = (ROOT / "webui/src/views/workspace/panels/OutlineConfirmationPanel.vue").read_text()
    handler = workspace.split("async function handleChatReferenceUpload", 1)[1].split(
        "const consumedQueryPrompts", 1
    )[0]

    assert "const chatReferenceLoading = ref(false)" in workspace
    assert "chatReferenceLoading.value = true" in handler
    assert "chatReferenceLoading.value = false" in handler
    assert "const accepted = await sendChatReferenceDocument" in handler
    assert "if (!accepted)" in handler
    assert ':reference-loading="chatReferenceLoading"' in workspace
    assert "referenceLoading: boolean" in chat_tab
    assert "props.referenceLoading" in chat_tab
    assert "referenceLoading: boolean" in panel
    assert "referenceLoading" in panel


def test_confirmation_save_failure_keeps_manual_panel_draft_for_retry():
    panel = (ROOT / "webui/src/views/workspace/panels/OutlineConfirmationPanel.vue").read_text()
    watch_body = panel.split("watch(", 1)[1].split("</script>", 1)[0]

    assert "if (props.confirmingSection) return" in watch_body


def test_confirmed_projection_text_keeps_total_and_relationships():
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text()
    callback = workspace.split("onOutlineGenerated: async", 1)[1].split("},\n})", 1)[0]

    assert "nextRawOutlineText = generatedRawOutlineText" in callback
