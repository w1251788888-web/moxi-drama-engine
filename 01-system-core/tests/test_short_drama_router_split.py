from app.services.short_drama_workflow_config import STEP_LABELS, workflow_step_order_for_project
from app.schemas.short_drama_writing import TestingScriptRequest


def test_workflow_config_lives_outside_short_drama_router():
    order = workflow_step_order_for_project({"project_type": "原创短剧"})

    assert "concept" in STEP_LABELS
    assert isinstance(order, list)


def test_testing_script_schema_lives_outside_short_drama_router():
    req = TestingScriptRequest(
        episode_no=3,
        scene_no=2,
        mode="segment",
        segment_id="hook",
    )

    assert req.episode_no == 3
    assert req.scene_no == 2
    assert req.segment_id == "hook"


def test_rule_resolver_module_exists_with_key_helpers():
    from app.services import short_drama_rule_resolver as rr

    assert callable(rr.prompts_dir)
    assert callable(rr.try_load_rule)
    assert callable(rr.resolve_rules_injection)
    assert "subgenre_female_face_slap" in rr.SUBGENRE_TRACK_TO_RULE
    assert "sample_track_a_high_pressure_female" in rr.SAMPLE_TRACK_TO_RULE


def test_advanced_generation_module_provides_profiles():
    """守住高级生成模式骨架在 services 层，不写进主 router。"""
    from pathlib import Path

    from app.services import short_drama_advanced_generation as ag

    assert callable(ag.list_advanced_generation_profiles)
    assert callable(ag.get_advanced_generation_profile)
    assert callable(ag.match_advanced_generation_profile)
    assert callable(ag.resolve_step_generation_route)
    assert callable(ag.build_advanced_generation_plan)
    assert callable(ag.resolve_testing_generation_route)
    assert callable(ag.apply_testing_generation_route)

    profiles = ag.list_advanced_generation_profiles()
    ids = {item["id"] for item in profiles}
    assert {"short_drama", "stage_play", "film", "long_series"} <= ids
    assert ag.get_advanced_generation_profile("stage_play")["label"] == "话剧"
    assert ag.match_advanced_generation_profile("电影项目")["id"] == "film"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef list_advanced_generation_profiles(" not in text
    assert "\ndef get_advanced_generation_profile(" not in text
    assert "\ndef resolve_step_generation_route(" not in text
    assert "\ndef build_advanced_generation_plan(" not in text
    assert "\ndef resolve_testing_generation_route(" not in text
    assert "\ndef apply_testing_generation_route(" not in text


def test_advanced_generation_routes_extracted_to_subpackage():
    """守住高级生成模式接口走 short_drama 子路由聚合。"""
    from pathlib import Path

    sub_router = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama"
        / "advanced_generation_routes.py"
    )
    assert sub_router.exists(), "缺 advanced_generation_routes.py 子文件"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "advanced_generation_routes" in text
    assert "include_router(_advanced_generation_routes.router)" in text


def test_testing_normalizers_module_exists_with_key_helpers():
    from app.services import short_drama_testing_normalizers as norm

    assert callable(norm.testing_workflow_context_defaults)
    assert callable(norm.normalize_testing_canon_packet)
    assert callable(norm.merge_testing_canon_packet)
    defaults = norm.testing_workflow_context_defaults()
    assert "materials" in defaults
    assert "rag_context" in defaults


def test_short_drama_writing_router_does_not_redefine_extracted_helpers():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")

    for line in (
        "\nSUBGENRE_TRACK_TO_RULE: dict",
        "\nSAMPLE_TRACK_TO_RULE: dict",
        "\ndef _prompts_dir(",
        "\ndef _load_step_template(",
        "\ndef _load_agent_prompt(",
        "\ndef _try_load_rule(",
        "\ndef _resolve_rules_injection(",
        "\ndef _testing_workflow_context_defaults(",
        "\ndef _normalize_testing_canon_packet(",
        "\ndef _merge_testing_canon_packet(",
        # 会话 metadata
        "\ndef _now_iso(",
        "\ndef _dump_metadata(",
        "\ndef _load_metadata(",
        "\ndef _deep_merge(",
        "\ndef _ensure_is_session(",
        "\ndef _get_session_task(",
        # quality/gate
        "\ndef _coerce_generation_text(",
        "\ndef _normalize_quality_dimension(",
        "\ndef _derive_quality_step_guidance(",
        "\ndef _build_step_result_extras(",
        "\ndef _build_acceptance_gate_warning(",
        "\ndef _extract_step_text(",
        "\ndef _project_config_value(",
        # text format
        "\ndef _normalize_counting_text(",
        "\ndef _count_testing_chars(",
        "\ndef _hard_truncate_by_sentence(",
        "\ndef _is_testing_header_line(",
        # workspace blocks
        "\ndef _condense_text(",
        "\ndef _derive_workspace_project_type(",
        "\ndef _build_workspace_character_block(",
        "\ndef _build_workspace_concept_block(",
        "\ndef _build_workspace_scene_block(",
        # state cards / relationship
        "\ndef _strength_tier_rule(",
        "\ndef _build_relationship_guardrail_block(",
        "\ndef _normalize_testing_state_cards(",
        "\ndef _card_availability_status(",
        "\ndef _build_testing_state_cards_block(",
    ):
        assert line not in text, f"已抽出的定义又出现在 router: {line.strip()}"


def test_session_metadata_module_provides_helpers():
    """守住 metadata 持久化辅助已抽到 services 层。"""
    from app.services import short_drama_session_metadata as md

    assert callable(md.now_iso)
    assert callable(md.dump_metadata)
    assert callable(md.load_metadata)
    assert callable(md.deep_merge)
    # 简单功能验证
    assert md.dump_metadata({"a": 1}) == '{"a":1}'
    assert md.load_metadata("") == {}
    assert md.deep_merge({"a": {"b": 1}}, {"a": {"c": 2}}) == {"a": {"b": 1, "c": 2}}


def test_quality_helpers_module_provides_helpers():
    """守住 quality/gate 辅助已抽到 services 层。"""
    from app.services import short_drama_quality_helpers as q

    assert q.coerce_generation_text({"a": 1}).strip().startswith("{")
    assert q.normalize_quality_dimension("节奏") == "rhythm"
    assert q.normalize_quality_dimension("rhythm") == "rhythm"
    # 空 payload 时 repair_scope 默认是 "rewrite_current_step"（非 verdict=pass 路径）
    assert q.derive_quality_step_guidance({})["repair_scope"] == "rewrite_current_step"
    assert q.project_config_value({"config": {"x": 1}}, "x") == 1
    assert q.extract_step_text(None) == ""


def test_text_format_module_provides_helpers():
    """守住字数/格式 工具已抽到 services 层。"""
    from app.services import short_drama_text_format as tf

    assert tf.count_testing_chars("你好，世界！", exclude_punctuation=True) == 4
    assert tf.is_testing_header_line("【场1-1：江家书房】") is True
    assert tf.is_testing_header_line("普通正文") is False


def test_workspace_blocks_module_provides_builders():
    """守住 workspace prompt block 构造器已抽到 services 层。"""
    from app.services import short_drama_workspace_blocks as wb

    assert wb.condense_text("a   b\n c", limit=10) == "a b c"
    assert "本集焦点角色" in wb.build_workspace_scene_block(
        episode_no=1, scene_no=2,
        episode_title="x", episode_summary="y",
        episode_conflict="z", episode_hook="h",
        selected_names=["甲", "乙"], continuity_notes="", task_instruction="开写",
    )


def test_scene_edit_routes_extracted_to_subpackage():
    """守住 testing/script-scene/suggest + patch 两个轻量路由已抽到子包。
    """
    from pathlib import Path
    sub_router = Path(__file__).resolve().parents[1] / "app" / "routers" / "short_drama" / "scene_edit_routes.py"
    assert sub_router.exists(), "缺 scene_edit_routes.py 子文件"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    # 主 router 不再内联这两个 endpoint 的 def
    assert "async def suggest_scene_improvement(" not in text
    assert "async def patch_scene_text(" not in text
    # 但会通过 include_router 把子 router 挂回
    assert "scene_edit_routes" in text and "include_router" in text


def test_resume_routes_extracted_to_subpackage():
    """守住 testing/resume 路由已抽到子包，主 router 不再内联。"""
    from pathlib import Path
    sub_router = Path(__file__).resolve().parents[1] / "app" / "routers" / "short_drama" / "resume_routes.py"
    assert sub_router.exists(), "缺 resume_routes.py 子文件"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "async def resume_testing_workflow(" not in text
    assert "resume_routes" in text and "include_router" in text


def test_session_metadata_module_extends_with_save_and_checklist():
    """守住 _save_metadata 和 _build_startup_checklist 已搬到 services 层。"""
    from app.services import short_drama_session_metadata as md

    assert callable(md.save_metadata)
    assert callable(md.build_startup_checklist)
    # 简单功能验证：build_startup_checklist 写回 metadata 并返回 6 条
    metadata: dict = {}
    items = md.build_startup_checklist(metadata)
    assert isinstance(items, list) and len(items) == 6
    assert metadata.get("startup_checklist") is items
    # 主 router 不再内联这两个 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _save_metadata(" not in text
    assert "\ndef _build_startup_checklist(" not in text


def test_step_payload_module_provides_helpers():
    """守住步骤产物读写已抽到 services 层。"""
    from app.services import short_drama_step_payload as sp

    assert callable(sp.is_per_episode_step)
    assert callable(sp.get_step_payload)
    assert callable(sp.set_step_payload)
    assert callable(sp.list_episodes_with_steps)
    assert "script_draft" in sp.PER_EPISODE_STEPS
    # 简单功能验证：写后能读
    md: dict = {}
    sp.set_step_payload(md, "script_draft", 1, {"full_output": "abc"})
    assert sp.get_step_payload(md, "script_draft", 1) == {"full_output": "abc"}
    assert sp.list_episodes_with_steps(md) == [1]
    # 指定集号时不能回退到 metadata["steps"] 的最新镜像，避免第2集误读第1集。
    assert sp.get_step_payload(md, "script_draft", 2) is None


def test_render_step_prompt_blanks_unresolved_template_vars(monkeypatch):
    """守住提示词里未知 ${x} 不再原样泄漏给模型。"""
    from app.services import short_drama_step_prompts as prompts

    monkeypatch.setattr(prompts, "load_step_template", lambda _name: "已知=${known}\n未知=${missing}\n短写=$other")
    monkeypatch.setattr(prompts, "resolve_rules_injection", lambda text, _vars: text)

    rendered = prompts.render_step_prompt("concept", {"known": "OK"})
    assert "已知=OK" in rendered
    assert "${missing}" not in rendered
    assert "$other" not in rendered


def test_testing_blocks_module_provides_helpers():
    """守住四个纯块构造器已抽到 services 层。"""
    from app.schemas.short_drama_writing import TestingScriptRequest
    from app.services import short_drama_testing_blocks as tb

    assert callable(tb.string_list)
    assert callable(tb.build_previous_episode_brief_block)
    assert callable(tb.build_future_episode_brief_block)
    assert callable(tb.build_relationship_diff_block)

    # string_list 行为：截断 + 上限
    out = tb.string_list(["a", "", "b" * 200, None, "c", "d", "e"], limit=3)
    assert out[:2] == ["a", "b" * 120]  # 第二条被截到 120 字
    assert len(out) == 3

    # 空 req → 兜底文案
    req = TestingScriptRequest(episode_no=1, scene_no=1, mode="scene")
    assert tb.build_previous_episode_brief_block(req) == "暂无前序集摘要。"
    assert tb.build_future_episode_brief_block(req) == "暂无后续集摘要。"

    # 主 router 不再内联这四个 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _string_list(",
        "\ndef _build_previous_episode_brief_block(",
        "\ndef _build_future_episode_brief_block(",
        "\ndef _build_relationship_diff_block(",
    ):
        assert fn not in text


def test_failure_classifier_module_provides_helpers():
    """守住 _classify_testing_failure 已抽到 services 层，主 router 不再内联。"""
    from app.schemas.short_drama_writing import TestingScriptRequest
    from app.services import short_drama_failure_classifier as fc

    assert callable(fc.classify_testing_failure)

    # 格式问题命中 format_break
    req = TestingScriptRequest(episode_no=1, scene_no=1, mode="scene")
    eval_state = {"blocking_issues": ["缺场次标头"], "quality_issues": [], "warnings": []}
    out = fc.classify_testing_failure(req, eval_state)
    assert out.failure_type == "format_break"
    assert out.evidence == ["缺场次标头"]

    # 默认无问题 -> dramatic_weakness（兜底分支）
    out2 = fc.classify_testing_failure(req, {})
    assert out2.failure_type == "dramatic_weakness"

    # 主 router 不再内联此 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _classify_testing_failure(" not in text


def test_quality_anchors_module_provides_helpers():
    """守住测试页质量锚点 helper 已抽到 services 层。"""
    from app.schemas.short_drama_writing import TestingScriptRequest
    from app.services import short_drama_quality_anchors as qa

    assert callable(qa.infer_testing_sample_track)
    assert callable(qa.build_testing_quality_anchor_block)

    # 显式赛道：A 型直接命中
    req = TestingScriptRequest(
        episode_no=1, scene_no=1, mode="scene",
        sample_track="sample_track_a_high_pressure_female",
    )
    name, notes = qa.infer_testing_sample_track(req)
    assert name.startswith("A.")
    assert isinstance(notes, list) and len(notes) >= 1
    block = qa.build_testing_quality_anchor_block(req)
    assert "当前对标模型：A." in block

    # 主 router 不再内联这两个 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _infer_testing_sample_track(" not in text
    assert "\ndef _build_testing_quality_anchor_block(" not in text


def test_rag_injection_module_provides_helpers():
    """守住 RAG 注入两个 helper + 数据集白名单 已抽到 services 层。"""
    from app.services import short_drama_rag_injection as rag

    assert callable(rag.augment_2026_rule_rag_query)
    assert callable(rag.apply_rag_injection)
    assert "writing_tutorials_2026" in rag.RAG_2026_RULE_DATASETS
    # 不在白名单的 dataset：query 应原样返回
    assert rag.augment_2026_rule_rag_query("not_in_whitelist", "abc", {}, {}) == "abc"
    # 主 router 不再内联这两个 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _augment_2026_rule_rag_query(" not in text
    assert "\nasync def _apply_rag_injection(" not in text


def test_testing_failure_module_provides_helpers():
    """守住 _log_testing_failure_analysis / _build_testing_skill_workflow 已抽到 services 层。"""
    from app.services import short_drama_testing_failure as tf

    assert callable(tf.log_testing_failure_analysis)
    assert callable(tf.build_testing_skill_workflow)
    # build_testing_skill_workflow 接受 None / dict / Pydantic：传 None 应不抛
    out = tf.build_testing_skill_workflow(None, blocking_issues=[], warnings=[])
    assert isinstance(out, dict)
    # 主 router 不再内联这两个 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _log_testing_failure_analysis(" not in text
    assert "\ndef _build_testing_skill_workflow(" not in text


def test_testing_enrich_module_provides_helpers():
    """守住 _enrich_testing_request_from_project / _load_testing_project_payload
    已抽到 services 层，主 router 不再内联这两个 80 行函数。
    """
    from app.services import short_drama_testing_enrich as te

    assert callable(te.enrich_testing_request_from_project)
    assert callable(te.load_testing_project_payload)
    # 主 router 不再内联这两个 def
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _load_testing_project_payload(" not in text
    assert "\ndef _enrich_testing_request_from_project(" not in text


def test_export_module_provides_helpers():
    """守住导出工具已抽到 services 层。"""
    from app.services import short_drama_export as ex

    assert callable(ex.resolve_export_episode_range)
    assert callable(ex.normalize_script_text)
    assert callable(ex.export_txt)
    assert callable(ex.export_docx)
    # 纯文本透传
    assert ex.normalize_script_text("普通正文\n第二行") == "普通正文\n第二行"
    # one_episode 默认就是 [episode_no]
    assert ex.resolve_export_episode_range({}, "one_episode", 5) == [5]


def test_export_route_extracted_to_subpackage():
    """守住 sessions/{id}/export 路由已抽到子包。"""
    from pathlib import Path
    sub_router = Path(__file__).resolve().parents[1] / "app" / "routers" / "short_drama" / "export_routes.py"
    assert sub_router.exists(), "缺 export_routes.py 子文件"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "async def export_session(" not in text, "主 router 不应再内联 export_session"
    # 主 router 也不应再内联 _export_txt / _export_docx / _normalize_script_text 的 def
    assert "\ndef _export_txt(" not in text
    assert "\ndef _export_docx(" not in text
    assert "\ndef _normalize_script_text(" not in text
    # 必须 include_router
    assert "export_routes" in text


def test_sessions_crud_routes_extracted_to_subpackage():
    """守住 sessions CRUD 四个路由已抽到子包。"""
    from pathlib import Path
    sub_router = Path(__file__).resolve().parents[1] / "app" / "routers" / "short_drama" / "sessions_crud_routes.py"
    assert sub_router.exists(), "缺 sessions_crud_routes.py 子文件"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    # 四个 endpoint 不再内联在主 router
    for fn in ("create_session", "list_sessions", "get_session", "update_session"):
        assert f"async def {fn}(" not in text, f"主 router 不应再内联 {fn}"
    assert "sessions_crud_routes" in text


def test_state_cards_module_provides_builders():
    """守住状态卡 / 关系护栏 已抽到 services 层。"""
    from app.services import short_drama_state_cards as sc

    assert callable(sc.strength_tier_rule)
    assert callable(sc.build_relationship_guardrail_block)
    assert callable(sc.normalize_testing_state_cards)
    assert callable(sc.card_availability_status)
    assert callable(sc.build_testing_state_cards_block)
    # normalize 接受 dict-like 输入
    out = sc.normalize_testing_state_cards({"relationship_cards": []})
    assert "relationship_cards" in out


def test_state_cards_block_ignores_cards_bound_only_to_deleted_characters():
    """状态卡绑定必须能对上当前人物库，避免旧人物 ID 污染正式护栏。"""
    from app.services import short_drama_state_cards as sc

    block = sc.build_testing_state_cards_block(
        {
            "relationship_cards": [
                {
                    "title": "旧人物关系",
                    "summary": "这张卡只绑定已经删除的人物，不能进入当前护栏。",
                    "related_character_ids": ["deleted-char"],
                },
                {
                    "title": "现有人物关系",
                    "summary": "这张卡绑定当前人物，可以进入护栏。",
                    "related_character_ids": ["char-a"],
                },
            ],
            "locked_fact_cards": [
                {
                    "title": "全局禁改事实",
                    "summary": "没有绑定人物的全局事实仍应保留。",
                }
            ],
        },
        characters=[{"id": "char-a", "name": "林晚"}],
        selected_ids=set(),
        current_episode=2,
    )

    assert "旧人物关系" not in block
    assert "现有人物关系" in block
    assert "全局禁改事实" in block


def test_seam_continuity_module_provides_helpers():
    """守住集间接续 + 连续性回退评估 已抽到 services 层。"""
    from collections import OrderedDict
    from app.services import short_drama_seam_continuity as sc

    for fn in (
        "testing_script_body_lines",
        "testing_os_line_count",
        "testing_char_bigrams",
        "testing_overlap_ratio",
        "previous_testing_tail_block",
        "assess_testing_episode_seam",
        "apply_testing_seam_gate_to_continuity",
        "fallback_continuity_assessment",
        "deep_audit_fingerprint",
    ):
        assert callable(getattr(sc, fn)), f"缺函数 {fn}"
    assert isinstance(sc.DEEP_AUDIT_CACHE, OrderedDict)
    assert isinstance(sc.DEEP_AUDIT_CACHE_MAX, int)
    # 简单行为校验：bigram 重叠率
    assert sc.testing_overlap_ratio("abc", "abc") >= 0.99
    assert 0.0 <= sc.testing_overlap_ratio("完全不同的内容", "另外一段彻底不一样") <= 1.0

    # 主 router 内不应再内联这些定义
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _testing_char_bigrams(",
        "\ndef _testing_overlap_ratio(",
        "\ndef _previous_testing_tail_block(",
        "\ndef _assess_testing_episode_seam(",
        "\ndef _apply_testing_seam_gate_to_continuity(",
        "\ndef _fallback_continuity_assessment(",
        "\ndef _deep_audit_fingerprint(",
        "\ndef _testing_script_body_lines(",
        "\ndef _testing_os_line_count(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"


def test_benchmark_assessment_module_provides_helpers():
    """守住头部对标 + 局部硬伤检测 + benchmark 评分封顶 已抽到 services 层。"""
    from app.services import short_drama_benchmark_assessment as ba

    for fn in (
        "detect_testing_local_patch_issues",
        "dialogue_body_for_testing",
        "detect_testing_head_quality_issues",
        "apply_testing_benchmark_caps",
        "fallback_benchmark_assessment",
    ):
        assert callable(getattr(ba, fn)), f"缺函数 {fn}"

    # dialogue_body_for_testing 行为冒烟
    assert ba.dialogue_body_for_testing("林夏：你不该来这里") == "你不该来这里"
    assert ba.dialogue_body_for_testing("LinXia: hello") == "hello"
    assert ba.dialogue_body_for_testing("没有冒号的旁白") == ""

    # 主 router 内不应再内联 inline 实现（detect/caps/fallback 在主 router 里以 thin wrapper 形式存在，体内只有 1 行委托调用）
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    # 关键判别：原本 70+ 行的 _detect_testing_head_quality_issues 不应再有"开篇钩子弱"等正文检测细节字符串
    assert "开篇钩子弱：漫剧前三集开头前5行" not in text, "head_quality 细节字符串不应再留在主 router"
    assert "通用物件补丁重复：终稿打磨污染当前集物件" not in text, "benchmark caps 细节字符串不应再留在主 router"
    assert '"已按头部短剧锚点做回退评估。"' not in text, "fallback_benchmark_assessment 细节字符串不应再留在主 router"
    # 大块常量也搬走了
    for name in (
        "_TESTING_GENERIC_PROP_PATCH_HINTS",
        "_TESTING_ABSTRACT_ENDING_HINTS",
        "_TESTING_NOVELISTIC_HINTS",
        "_TESTING_GENERIC_VILLAIN_LINES",
        "_TESTING_OPENING_PRESSURE_TOKENS",
        "_TESTING_SATISFACTION_BEAT_TOKENS",
    ):
        assert f"\n{name} = " not in text, f"常量 {name} 不应再留在主 router"


def test_format_repairs_module_provides_helpers():
    """守住剧本格式硬修复 + 场标头规范化 已抽到 services 层。"""
    from app.services import short_drama_format_repairs as fr
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "normalize_testing_generated_content",
        "expected_testing_scene_header",
        "apply_testing_hard_repairs",
        "detect_segment_overlap_issue",
    ):
        assert callable(getattr(fr, fn)), f"缺函数 {fn}"

    # bracket 风格场标头
    req = TestingScriptRequest(
        episode_no=2,
        scene_no=3,
        scene_header_style="bracket",
    )
    header = fr.expected_testing_scene_header(req)
    assert header == "【场2-3：日  内  本集主场】"
    # plain 风格
    req2 = TestingScriptRequest(episode_no=1, scene_no=1, scene_header_style="plain")
    assert fr.expected_testing_scene_header(req2) == "1-1  日  内  本集主场"

    # 非 hook 分段允许自然进入新场，但会去掉重复上一段场标。
    continuation_req = TestingScriptRequest(
        episode_no=2,
        scene_no=1,
        scene_header_style="bracket",
        mode="segment",
        segment_id="validation",
        current_content="【场2-1：夜  内  客厅】\n△ 旧内容",
    )
    assert fr.normalize_testing_generated_content(
        continuation_req,
        "【场2-2：日  外  门口】\n△ 新场推进",
    ).startswith("【场2-2")
    assert fr.normalize_testing_generated_content(
        continuation_req,
        "【场2-1：夜  内  客厅】\n△ 重复场标",
    ).startswith("△ 重复场标")

    # 主 router 内不应再内联实现
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _normalize_testing_generated_content(",
        "\ndef _expected_testing_scene_header(",
        "\ndef _apply_testing_hard_repairs(",
        "\ndef _detect_segment_overlap_issue(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"


def test_deep_audit_module_provides_helpers():
    """守住 _run_testing_deep_audit + 生成参数透传 已抽到 services 层。"""
    from app.services import short_drama_deep_audit as da
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "generation_kwargs_from_req",
        "generation_kwargs_from_metadata",
        "run_testing_deep_audit",
    ):
        assert callable(getattr(da, fn)), f"缺函数 {fn}"

    # generation_kwargs_from_req 行为冒烟
    req = TestingScriptRequest(generation_provider="anthropic", generation_model="claude-sonnet-4")
    out = da.generation_kwargs_from_req(req)
    assert out == {"provider": "anthropic", "model": "claude-sonnet-4"}
    # 空字段不传
    req2 = TestingScriptRequest()
    assert da.generation_kwargs_from_req(req2) == {}

    # 主 router 内不应再内联 inline 实现（深审 prompt 字符串与 JSON 模板字符串都不应再出现）
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "你是头部短剧总编兼系列统筹" not in text, "深审 system_prompt 不应再留在主 router"
    assert '"benchmark": {' not in text, "深审 JSON 输出模板不应再留在主 router"


def test_evaluation_pipeline_module_provides_helpers():
    """守住评估流水线 6 个 helper + 缓存常量 已抽到 services 层。"""
    from collections import OrderedDict
    from app.services import short_drama_evaluation_pipeline as ep
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "split_testing_generation_issues",
        "evaluation_score",
        "apply_scene_level_gate",
        "review_testing_scene_quality",
        "fallback_episode_memory_card",
        "structured_update_fingerprint",
    ):
        assert callable(getattr(ep, fn)), f"缺函数 {fn}"
    assert isinstance(ep.STRUCTURED_UPDATE_CACHE, OrderedDict)
    assert isinstance(ep.STRUCTURED_UPDATE_CACHE_MAX, int)

    # split_testing_generation_issues 行为冒烟
    req = TestingScriptRequest(mode="scene")
    blocking, warnings = ep.split_testing_generation_issues(req, [
        "输出为空",
        "净字数不足：当前 1120，要求至少 1150。",
        "字数贴近上限",
    ])
    assert "输出为空" in blocking
    assert "净字数不足：当前 1120，要求至少 1150。" in warnings  # 快写/分段统一：轻微字数偏差先提醒
    assert "字数贴近上限" in warnings

    severe_blocking, _ = ep.split_testing_generation_issues(req, [
        "净字数不足：当前 600，要求至少 1150。",
    ])
    assert "净字数不足：当前 600，要求至少 1150。" in severe_blocking

    req2 = TestingScriptRequest(mode="segment")
    blocking2, warnings2 = ep.split_testing_generation_issues(req2, ["净字数不足"])
    assert "净字数不足" in warnings2  # segment 模式宽松
    assert blocking2 == []

    # evaluation_score 行为冒烟
    assert ep.evaluation_score({"blocking_issues": ["a", "b"], "warnings": ["w"], "quality_passed": False}) == (2, 1, 1)

    # 主 router 内不应再内联 inline 实现
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _split_testing_generation_issues(",
        "\ndef _evaluation_score(",
        "\ndef _review_testing_scene_quality(",
        "\ndef _fallback_episode_memory_card(",
        "\ndef _structured_update_fingerprint(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"
    # 关键 LLM prompt 字符串也搬走了
    assert "你是头部短剧总编（对标《重生后我叫他阿兄》漫剧" not in text
    assert "_STRUCTURED_UPDATE_CACHE: " not in text  # 常量声明搬走


def test_detection_helpers_module_provides_helpers():
    """守住 5 个 detection helper（输出格式校验 + 角色/关系/状态卡）已抽到 services 层。"""
    from app.services import short_drama_detection_helpers as dh
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "validate_testing_script_output",
        "analyze_testing_character_health",
        "detect_relationship_updates",
        "detect_state_card_suggestions",
        "detect_testing_narrative_logic_issues",
    ):
        assert callable(getattr(dh, fn)), f"缺函数 {fn}"

    # validate_testing_script_output 行为冒烟：空文本应返回 [输出为空。]
    req = TestingScriptRequest(mode="scene")
    char_count, errors = dh.validate_testing_script_output("", req)
    assert char_count == 0
    assert errors == ["输出为空。"]

    # 主 router 内不应再内联实现 + 关键反模式正则也搬走了
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _validate_testing_script_output(",
        "\ndef _analyze_testing_character_health(",
        "\ndef _detect_relationship_updates(",
        "\ndef _detect_state_card_suggestions(",
        "\ndef _detect_testing_narrative_logic_issues(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"
    # 头部样板反模式特征字符串也不应再出现
    assert "出现广播式自报身份或解说式台词" not in text


def test_narrative_drift_module_provides_helpers():
    """守住叙事漂移检测器 + 2 个文本工具 已抽到 services 层。"""
    from app.services import short_drama_narrative_drift as nd
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "normalize_testing_story_text",
        "contains_testing_story_markers",
        "detect_testing_narrative_drift_issues",
    ):
        assert callable(getattr(nd, fn)), f"缺函数 {fn}"

    # normalize_testing_story_text 行为冒烟：去掉空白和标点
    out = nd.normalize_testing_story_text("你 好，世界！")
    assert out == "你好世界"
    # contains_testing_story_markers 行为冒烟
    assert nd.contains_testing_story_markers("我替弟还了赌债", ["替弟", "赌债"])
    assert not nd.contains_testing_story_markers("普通文本", ["不存在的marker"])

    # mode=segment 时 detect_testing_narrative_drift_issues 直接返回 []
    req = TestingScriptRequest(mode="segment")
    assert nd.detect_testing_narrative_drift_issues(req, "任何内容") == []

    # scene 模式下，“封存/待核验/登记/受理”也应被识别为桥接动作，
    # 不能把截图等民间线索误判成直接跳到官方闭环证据。
    req = TestingScriptRequest(mode="scene", episode_no=2)
    bridged_content = "\n".join([
        "△林晚把工资截图、考勤日志和U盘推到行政合规台。",
        "陈珩：只封存待核验，不做仲裁结论。",
        "△窗口生成待核验登记号，封存袋压住回执。",
    ])
    assert nd.detect_testing_narrative_drift_issues(req, bridged_content) == []

    # 主 router 内不应再内联实现
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _normalize_testing_story_text(",
        "\ndef _contains_testing_story_markers(",
        "\ndef _detect_testing_narrative_drift_issues(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"
    # 关键检测函数体已搬走（autofix directives 等下游代码可能仍以子串方式检查 issue 文本，正常）
    assert 'issues.append("民间线索直接跳成官方闭环证据' not in text
    assert "本集开场重复调用了前集已经完成的核心动作节点" not in text


def test_canon_blocks_module_provides_helpers():
    """守住 canon 包推断 + canon/记忆卡 prompt 块构造器 已抽到 services 层。"""
    from app.services import short_drama_canon_blocks as cb
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "build_inferred_canon_packet",
        "format_testing_canon_block",
        "build_testing_episode_memory_block",
    ):
        assert callable(getattr(cb, fn)), f"缺函数 {fn}"

    # build_inferred_canon_packet 行为冒烟
    req = TestingScriptRequest(
        episode_no=3,
        episode_conflict="主角被退婚",
        episode_hook="退婚现场被追债",
        relationship_guardrails="- 男主和女配从来不是恋人",
        brief="一个被退婚少女的逆袭",
    )
    canon = cb.build_inferred_canon_packet(req)
    assert canon["premise"] == "一个被退婚少女的逆袭"
    assert "男主和女配从来不是恋人" in canon["relationship_limits"]
    assert any("第3集冲突：主角被退婚" in t for t in canon["timeline_anchors"])

    # 主 router 内不应再内联实现
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _build_inferred_canon_packet(",
        "\ndef _format_testing_canon_block(",
        "\ndef _build_testing_episode_memory_block(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"


def test_segment_tasks_module_provides_helpers():
    """守住 segment 任务模板 + resolve_segment_task 已抽到 services 层。"""
    from app.services import short_drama_segment_tasks as st

    assert isinstance(st.TESTING_SEGMENT_TASKS, dict)
    assert "hook" in st.TESTING_SEGMENT_TASKS
    assert isinstance(st.TESTING_SEGMENT_TASKS_REALISTIC_FAMILY, dict)
    assert "hook" in st.TESTING_SEGMENT_TASKS_REALISTIC_FAMILY
    assert "subgenre_hybrid_realistic_family" in st.REALISTIC_FAMILY_TRACKS
    assert callable(st.resolve_segment_task)

    # 路由行为冒烟
    realistic = st.resolve_segment_task("hook", "subgenre_hybrid_realistic_family", "")
    assert "字数自律" in realistic
    realistic_explosion = st.resolve_segment_task("explosion", "subgenre_hybrid_realistic_family", "")
    assert "情绪临界必须可见" in realistic_explosion
    assert "不可逆半步" in realistic_explosion
    assert "禁止打脸" in realistic_explosion
    default_hook = st.resolve_segment_task("hook", "anything", "anything")
    assert "钩子段" in default_hook

    # 主 router 内不应再内联
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _resolve_segment_task(" not in text
    assert "TESTING_SEGMENT_TASKS: dict[str, str] = {" not in text
    assert "TESTING_SEGMENT_TASKS_REALISTIC_FAMILY: dict[str, str] = {" not in text


def test_episode_locks_module_provides_helpers():
    """守住 关键名词锁 + 本段意图 已抽到 services 层。"""
    from app.services import short_drama_episode_locks as el
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "extract_episode_keywords",
        "build_lockword_block",
        "build_segment_intent_block",
    ):
        assert callable(getattr(el, fn)), f"缺函数 {fn}"

    keywords = el.extract_episode_keywords("欠款10万，住院手术", "签字结婚")
    assert "住院" in keywords or "欠款" in keywords
    assert any("10万" in k for k in keywords)

    req = TestingScriptRequest(
        episode_no=2,
        segment_id="hook",
        episode_summary="主角在医院签字",
    )
    block = el.build_segment_intent_block(req)
    assert "本段意图" in block

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _extract_episode_keywords(",
        "\ndef _build_lockword_block(",
        "\ndef _build_segment_intent_block(",
    ):
        assert fn not in text, f"主 router 不应再内联 {fn.strip()}"


def test_episode_slicers_module_provides_helpers():
    """守住 beat_sheet / novel_analysis 按集切片 已抽到 services 层。"""
    from app.services import short_drama_episode_slicers as sl

    assert callable(sl.slice_beat_sheet_by_episode)
    assert callable(sl.slice_novel_anchor_by_episode)

    sample = "## 第1集\nA 内容\n## 第2集\nB 内容\n## 第3集\nC 内容\n"
    cut = sl.slice_beat_sheet_by_episode(sample, 2)
    assert "B 内容" in cut and "C 内容" not in cut

    anchor_text = "第1集：原著第1-2章\n第2集：原著第3-4章\n"
    anchor = sl.slice_novel_anchor_by_episode(anchor_text, 2)
    assert "第3-4章" in anchor

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _slice_beat_sheet_by_episode(",
        "\ndef _slice_novel_anchor_by_episode(",
    ):
        assert fn not in text


def test_testing_rules_module_provides_helpers():
    """守住 testing 字数规则 / 格式规则 已抽到 services 层。"""
    from app.services import short_drama_testing_rules as tr
    from app.schemas.short_drama_writing import TestingScriptRequest

    assert callable(tr.build_testing_length_rule)
    assert callable(tr.build_testing_format_rule)

    req = TestingScriptRequest(episode_no=1, mode="scene", episode_minutes=2)
    length_rule = tr.build_testing_length_rule(req)
    assert "字数" in length_rule or "字" in length_rule
    assert "1330～2070" in length_rule
    assert "90秒=1200纯字符" in length_rule
    fmt = tr.build_testing_format_rule(req)
    assert "场次标头" in fmt or "△" in fmt

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _build_testing_length_rule(",
        "\ndef _build_testing_format_rule(",
    ):
        assert fn not in text


def test_episode_contract_module_provides_helpers():
    """守住 剧作契约 + 全剧推演沙盘 + 连续性 guardrails 已抽到 services 层。"""
    from app.services import short_drama_episode_contract as ec
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "infer_testing_contract_guardrails",
        "episode_contract_from_brief",
        "build_testing_series_simulation_packet",
        "current_testing_episode_contract",
        "format_testing_episode_contract_block",
        "build_testing_continuity_guardrails",
    ):
        assert callable(getattr(ec, fn))

    # guardrails 关键词触发冒烟
    req = TestingScriptRequest(
        episode_no=2,
        brief="一个被退婚少女靠摆摊还债",
        episode_summary="主角在医院签字、扛起债务",
        episode_conflict="债主上门",
    )
    rails = ec.infer_testing_contract_guardrails(req)
    assert any("债务" in r for r in rails)

    # 当前集契约可拿到
    contract = ec.current_testing_episode_contract(req)
    assert int(contract.get("episode_no") or 0) == 2

    # 主 router 内不应再内联
    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _infer_testing_contract_guardrails(",
        "\ndef _episode_contract_from_brief(",
        "\ndef _build_testing_series_simulation_packet(",
        "\ndef _current_testing_episode_contract(",
        "\ndef _format_testing_episode_contract_block(",
        "\ndef _build_testing_continuity_guardrails(",
    ):
        assert fn not in text


def test_testing_contexts_module_provides_helpers():
    """守住 素材/问题反馈/报告 上下文块 已抽到 services 层。"""
    from app.services import short_drama_testing_contexts as tc
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "build_testing_material_context",
        "build_testing_issue_feedback_context",
        "build_testing_report_context",
    ):
        assert callable(getattr(tc, fn))

    req = TestingScriptRequest(episode_no=1)
    assert tc.build_testing_material_context(req) == "暂无素材参考。"
    assert tc.build_testing_issue_feedback_context(req) == "暂无历史问题反馈。"
    assert tc.build_testing_report_context(req) == "暂无历史质量/合规报告。"

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _build_testing_material_context(",
        "\ndef _build_testing_issue_feedback_context(",
        "\ndef _build_testing_report_context(",
    ):
        assert fn not in text


def test_segment_blocks_module_provides_helpers():
    """守住 分段 focus / mini角色 / 已确认前文 / 分段护栏 已抽到 services 层。"""
    from app.services import short_drama_segment_blocks as sb
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "build_testing_segment_focus_block",
        "build_testing_segment_character_mini_block",
        "build_testing_segment_confirmed_context_block",
        "build_testing_segment_guardrail_block",
    ):
        assert callable(getattr(sb, fn))

    req = TestingScriptRequest(
        episode_no=1,
        episode_title="开场",
        segment_id="hook",
        episode_summary="主角摆摊被砸",
    )
    focus = sb.build_testing_segment_focus_block(req)
    assert "第1集" in focus and "hook" in focus

    confirmed = sb.build_testing_segment_confirmed_context_block(req)
    assert "暂无已确认前文" in confirmed

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _build_testing_segment_focus_block(",
        "\ndef _build_testing_segment_character_mini_block(",
        "\ndef _build_testing_segment_confirmed_context_block(",
        "\ndef _build_testing_segment_guardrail_block(",
    ):
        assert fn not in text


def test_rag_cards_module_provides_helpers():
    """守住 RAG 卡片编译 / 选段 / 格式化 已抽到 services 层。"""
    from app.services import short_drama_rag_cards as rc
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "make_testing_rag_card",
        "infer_testing_top_script_pattern_cards",
        "compile_testing_rag_context_cards",
        "select_testing_rag_cards_for_segment",
        "format_testing_rag_context_pack",
        "build_testing_rule_context",
        "build_testing_rag_context",
    ):
        assert callable(getattr(rc, fn))

    # make_testing_rag_card 行为冒烟
    card = rc.make_testing_rag_card("episode_contract", "标题", "内容内容内容", authority=90)
    assert card["context_type"] == "episode_contract"
    assert card["authority_level"] == 90

    req = TestingScriptRequest(episode_no=1, segment_id="hook")
    cards = rc.compile_testing_rag_context_cards(req)
    assert isinstance(cards, list)
    pack = rc.format_testing_rag_context_pack(req, budget=1200)
    assert "RAG" in pack or "暂无" in pack

    rule = rc.build_testing_rule_context(req)
    assert "暂无额外规则上下文" in rule or "规则" in rule

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _make_testing_rag_card(",
        "\ndef _infer_testing_top_script_pattern_cards(",
        "\ndef _compile_testing_rag_context_cards(",
        "\ndef _select_testing_rag_cards_for_segment(",
        "\ndef _format_testing_rag_context_pack(",
        "\ndef _build_testing_rule_context(",
        "\ndef _build_testing_rag_context(",
    ):
        assert fn not in text


def test_evaluate_scene_module_provides_helpers():
    """守住 场景评估主流程 + 契约违反 + 结构化更新 已抽到 services 层。"""
    from app.services import short_drama_evaluate_scene as es

    for fn in (
        "detect_testing_episode_contract_issues",
        "extract_testing_structured_updates",
        "evaluate_testing_scene",
    ):
        assert callable(getattr(es, fn))

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _detect_testing_episode_contract_issues(",
        "\ndef _evaluate_testing_scene(",
        "\ndef _extract_testing_structured_updates(",
    ):
        assert fn not in text


def test_autofix_module_provides_helpers():
    """守住 自动修复主流程 + 结构化兜底 + 定向指令 已抽到 services 层。"""
    from app.services import short_drama_autofix as af
    from app.schemas.short_drama_writing import TestingScriptRequest

    for fn in (
        "build_internal_rewrite_prompt",
        "testing_character_names_by_ids",
        "testing_fallback_speaker",
        "insert_testing_line_after_header",
        "apply_testing_narrative_autofix_fallback",
        "build_testing_autofix_directives",
        "auto_fix_testing_script_content",
    ):
        assert callable(getattr(af, fn))

    # testing_fallback_speaker 行为冒烟
    req = TestingScriptRequest(
        episode_no=1,
        characters=[{"id": "c1", "name": "苏小禾", "role": "protagonist"}],
    )
    assert af.testing_fallback_speaker(req) == "苏小禾"

    # testing_character_names_by_ids 行为冒烟
    names = af.testing_character_names_by_ids(
        [{"id": "c1", "name": "甲"}, {"id": "c2", "name": "乙"}],
        {"c1"},
    )
    assert names == ["甲"]

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _build_internal_rewrite_prompt(",
        "\ndef _testing_character_names_by_ids(",
        "\ndef _testing_fallback_speaker(",
        "\ndef _insert_testing_line_after_header(",
        "\ndef _apply_testing_narrative_autofix_fallback(",
        "\ndef _build_testing_autofix_directives(",
        "\ndef _auto_fix_testing_script_content(",
    ):
        assert fn not in text


def test_audit_routes_extracted_to_subpackage():
    """守住 validate / deep-audit / auto-fix 三个 endpoint 已搬到 app.routers.short_drama.audit_routes。"""
    from app.routers.short_drama import audit_routes
    from pathlib import Path

    paths = [str(getattr(rt, "path", "")) for rt in audit_routes.router.routes]
    assert any(p.endswith("/script-scene/validate") for p in paths)
    assert any(p.endswith("/script-scene/deep-audit") for p in paths)
    assert any(p.endswith("/script-scene/auto-fix") for p in paths)

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '@router.post("/testing/script-scene/validate"',
        '@router.post("/testing/script-scene/deep-audit"',
        '@router.post("/testing/script-scene/auto-fix"',
    ):
        assert marker not in text, f"主 router 不应再注册 {marker}"


def test_scene_routes_extracted_to_subpackage():
    """守住 script-scene 同步/流式生成 已搬到 app.routers.short_drama.scene_routes。"""
    from app.routers.short_drama import scene_routes
    from pathlib import Path

    paths = [str(getattr(rt, "path", "")) for rt in scene_routes.router.routes]
    assert any(p.endswith("/script-scene") for p in paths)
    assert any(p.endswith("/script-scene/stream") for p in paths)

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert '@router.post("/testing/script-scene", response_model=TestingScriptResponse' not in text
    assert '@router.post("/testing/script-scene/stream"' not in text


def test_scene_generation_module_provides_helpers():
    """守住 场景生成主流程 / prompt 装配 / segment-lite prompt 已抽到 services。"""
    from app.services import short_drama_scene_generation as sg

    for fn in (
        "build_segment_lite_prompt",
        "prepare_testing_script_generation",
        "generate_testing_scene_passed",
    ):
        assert callable(getattr(sg, fn))

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _build_segment_lite_prompt(",
        "\ndef _generate_testing_scene_passed(",
        "\ndef _prepare_testing_script_generation(",
    ):
        assert fn not in text


def test_template_vars_module_provides_helpers():
    """守住 _build_base_template_vars 主体已抽到 services。"""
    from app.services import short_drama_template_vars as tv

    assert callable(tv.build_base_template_vars)

    # 行为冒烟：空 metadata 也能装出最小变量集
    keys = ("project_type", "draft_episode", "state_cards_block", "used_beats_block")
    result = tv.build_base_template_vars({}, draft_episode=1, known_template_keys=keys)
    assert result["draft_episode"] == "1"
    assert "used_beats_block" in result

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    # router 保留薄 wrapper，但主体已经搬走（>200 行的 base dict 不应该再出现）
    assert text.count('storyboard_requirements = [') == 0, "主 router 不应再内联 _build_base_template_vars 主体"


def test_step_prompts_module_provides_helpers():
    """守住 render_step_prompt / system_prompt_for_step / step_generation_payload /
    derive_category_path / build_startup_context 已抽到 services 层。"""
    from app.services import short_drama_step_prompts as sp

    for fn in (
        "render_step_prompt",
        "system_prompt_for_step",
        "step_generation_payload",
        "derive_category_path",
        "build_startup_context",
    ):
        assert callable(getattr(sp, fn))

    # derive_category_path 行为冒烟
    assert sp.derive_category_path({}) == "当前赛道"
    assert sp.derive_category_path({"project": {"genre_main": "都市", "genre_sub": "重生"}}) == "都市 / 重生"

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for fn in (
        "\ndef _render_step_prompt(",
        "\ndef _system_prompt_for_step(",
        "\ndef _render_testing_scene_prompt(",
    ):
        assert fn not in text


def test_session_hydrate_module_provides_helpers():
    """守住 _hydrate_session_project_runtime_context 已抽到 services 层。"""
    from app.services import short_drama_session_hydrate as sh

    assert callable(sh.hydrate_session_project_runtime_context)

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _hydrate_session_project_runtime_context(" not in text


def test_sse_module_provides_helpers():
    """守住 sse_event / stream_sync_text_generation 已抽到 services 层。"""
    from app.services import short_drama_sse as sse

    assert callable(sse.sse_event)
    assert callable(sse.stream_sync_text_generation)
    assert sse.sse_event("token", {"text": "你"}).startswith("event: token\ndata: ")

    from pathlib import Path
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    assert "\ndef _sse_event(" not in text
    assert "\nasync def _stream_sync_text_generation(" not in text


def test_step_routes_extracted_to_subpackage():
    """守住 run-step / save-step / run-step-stream 三个重型路由已搬到 step_routes。"""
    from app.routers.short_drama import step_routes
    from pathlib import Path

    paths = [str(getattr(rt, "path", "")) for rt in step_routes.router.routes]
    assert any(p.endswith("/run-step") for p in paths)
    assert any(p.endswith("/save-step") for p in paths)
    assert any(p.endswith("/run-step-stream") for p in paths)

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '@router.post("/sessions/{task_id}/run-step"',
        '@router.post("/sessions/{task_id}/save-step"',
        '@router.get(\n    "/sessions/{task_id}/run-step-stream"',
    ):
        assert marker not in text, f"主 router 不应再注册 {marker}"


def test_session_routes_extracted_to_subpackage():
    """守住 startup-context / materials / issue-feedback 已搬到 session_routes。"""
    from app.routers.short_drama import session_routes
    from pathlib import Path

    paths = [str(getattr(rt, "path", "")) for rt in session_routes.router.routes]
    for needle in ("/startup-context", "/materials/recommend", "/materials/select", "/issue-feedback/refresh"):
        assert any(p.endswith(needle) for p in paths), f"missing {needle}"

    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "short_drama_writing.py"
    ).read_text(encoding="utf-8")
    for marker in (
        '@router.get("/sessions/{task_id}/startup-context"',
        '@router.post("/sessions/{task_id}/materials/recommend"',
        '@router.post("/sessions/{task_id}/materials/select"',
        '@router.post("/sessions/{task_id}/issue-feedback/refresh"',
    ):
        assert marker not in text


def test_step_config_module_provides_helpers():
    """守住 STEP_TEMPERATURE_PROFILE / KNOWN_TEMPLATE_KEYS / resolve_step_temperature 已抽到 services 层。"""
    from app.services import short_drama_step_config as sc

    assert isinstance(sc.STEP_TEMPERATURE_PROFILE, dict)
    assert "script_draft" in sc.STEP_TEMPERATURE_PROFILE
    assert isinstance(sc.KNOWN_TEMPLATE_KEYS, tuple)
    assert "brief" in sc.KNOWN_TEMPLATE_KEYS

    # resolve_step_temperature 行为冒烟
    assert sc.resolve_step_temperature("script_draft", None) == 0.7
    assert sc.resolve_step_temperature("script_draft", 0.3) == 0.3  # override 优先
    assert sc.resolve_step_temperature("unknown_step", None) is None
