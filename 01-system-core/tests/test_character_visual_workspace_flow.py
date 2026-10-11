from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_project(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_character_visual_generation_has_local_fallback_when_ai_disabled(monkeypatch):
    from app.services import character_visual_service as service

    monkeypatch.setattr(service, "generation_enabled", lambda: False)

    result = service.ai_generate_visual_text(
        character_name="何铮",
        narrative_profile="外冷内热的企业继承人，身份地位较高。",
        genre="现代都市男频",
        style_mode="realistic",
    )

    assert result["gender"] == "男"
    assert result["age_look"]
    assert "西装" in result["default_outfit"]
    assert result["style_tags"]

    result_with_meta = service.ai_generate_visual_text_result(
        character_name="何铮",
        narrative_profile="外冷内热的企业继承人，身份地位较高。",
        genre="现代都市男频",
        style_mode="realistic",
    )
    assert result_with_meta["backend"] == "fallback"
    assert result_with_meta["visual_text"]["gender"] == "男"


def test_character_visual_generation_uses_short_timeout_and_fallback(monkeypatch):
    from app.services import character_visual_service as service

    calls = []

    def fake_generate_text(*args, **kwargs):
        calls.append(kwargs)
        raise TimeoutError("slow upstream")

    monkeypatch.setattr(service, "generation_enabled", lambda: True)
    monkeypatch.setattr(service, "generate_text", fake_generate_text)

    result = service.ai_generate_visual_text_result(
        character_name="吴雪",
        narrative_profile="女主被迫逃离控制，掌握关键证据。",
        genre="现代都市悬疑",
        style_mode="realistic",
    )

    assert result["backend"] == "fallback"
    assert result["fallback_reason"] == "TimeoutError"
    assert result["visual_text"]["gender"] == "女"
    assert calls and calls[0]["timeout_seconds"] == 18
    assert calls[0]["max_retries"] == 1


def test_character_visual_routes_allow_project_actor_access_contract():
    source = read_project("app/routers/character_visual.py")

    assert "verify_project_actor" in source
    assert "ProjectAccessActor" in source
    assert "_get_project_for_actor_or_404" in source
    assert "run_in_threadpool" in source
    assert "verify_admin" not in source

    guarded_routes = [
        "generate_visual",
        "list_visual",
        "get_visual",
        "upsert_visual",
        "lock_visual",
        "unlock_visual",
        "list_scenes",
        "upsert_scene",
        "delete_scene",
    ]
    for route_name in guarded_routes:
        route_start = source.index(f"async def {route_name}")
        next_route = source.find("\n@router.", route_start + 1)
        body = source[route_start : next_route if next_route != -1 else len(source)]
        assert "verify_project_actor" in body
        assert "_get_project_for_actor_or_404" in body


def test_character_visual_panel_selection_save_and_timeout_contract():
    editor = read_project("webui/src/components/workshop/CharacterEditor.vue")
    tab = read_project("webui/src/views/workspace/tabs/CharacterTab.vue")
    visual_panel = read_project("webui/src/components/workshop/CharacterVisualPanel.vue")
    visual_api = read_project("webui/src/api/modules/visual.ts")
    character_state = read_project("webui/src/features/workspace/composables/useCharacterTab.ts")
    visual_service = read_project("app/services/character_visual_service.py")

    assert "(e: 'select', id: string): void" in editor
    assert "emit('select', character.id)" in editor
    assert "cloneCharacterForEdit" in editor
    assert "watch(" in editor and "props.selectedId" in editor
    assert "@select=\"(id) => { selectedCharacterId = id }\"" in tab
    assert "visualCharacterId" not in tab
    assert "openSelectedVisualPanel" not in tab
    assert "CharacterVisualPanel" not in tab
    assert "v-if=\"visualCharacterId\"" not in tab
    assert ":character-id=\"visualCharacterId\"" not in tab
    assert "@close=\"visualCharacterId = null\"" not in tab
    assert "@close=\"selectedCharacterId = null\"" not in tab
    assert "视觉档案" not in tab

    assert "resetDraft" in visual_panel
    assert "statusMessage" in visual_panel
    assert "已通过 AI 模型生成视觉档案草稿" in visual_panel
    assert "AI 暂不可用，已生成本地视觉档案草稿" in visual_panel
    assert "{{ generating ? 'AI 生成中...' : 'AI 生成' }}" in visual_panel
    assert "保存成功，当前视觉档案版本" in visual_panel
    assert "保存档案" in visual_panel
    assert "请先点击“保存档案”，保存成功后再锁定视觉档案。" in visual_panel
    assert "当前视觉档案已锁定，请先解锁后再保存。" in visual_panel
    assert "recoverAfterTimeout" in visual_panel
    assert "保存请求超时，但后端已落库为版本" in visual_panel
    assert "锁定请求超时，但后端已锁定版本" in visual_panel
    assert ':disabled="locking"' in visual_panel
    assert ':disabled="locking || !data"' not in visual_panel
    assert "保存角色" in editor
    assert "backend?: 'llm' | 'fallback'" in visual_api
    assert "VISUAL_FAST_WRITE_TIMEOUT_MS = 30000" in visual_api
    assert "关闭视觉档案" in visual_panel
    assert "emit('close')" in visual_panel
    assert "{ timeout: 60000 }" in visual_api
    assert "rag_dataset in rag.dataset_map" in visual_service
    assert "asyncio.wait_for" in visual_service

    assert "selectedCharacterId.value = created.id" in character_state
    assert "selectedCharacterId.value = characters.value[0]?.id || null" in character_state
