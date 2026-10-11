"""短剧写作工作台（Session）管理接口

目标：为 WebUI 提供"非对话式、可手动操作"的短剧写作会话能力。

存储策略：复用 task 表的 metadata_json，不新增表。
- 写作会话：metadata.kind == "short_drama_writing_session"
- 数据持久化：仅写入 task.metadata_json（数据库）
"""

from __future__ import annotations

# 这个文件已经从 ~8300 行的单体 router 收敛为「路由聚合 + 兼容别名」薄壳层：
# - 所有 endpoint 定义都搬到了 app/routers/short_drama/*.py 子包
# - 所有业务逻辑都搬到了 app/services/short_drama_*.py
# - 这里保留 _X 前缀别名是给 episode_segment_router、tests 旧导入路径兼容用

from typing import Any, Optional

from fastapi import APIRouter, Depends

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.acceptance_criteria_service import run_acceptance_checks  # noqa: F401  re-export
from app.services.issue_feedback_service import build_issue_feedback_snapshot  # noqa: F401  re-export
from app.services.material_library_service import material_to_dict, select_project_materials  # noqa: F401  re-export
from app.services.short_drama_lab_service import (
    _build_selected_material_borrow_focus,
    _build_selected_material_do_not_copy,
    _build_selected_material_heat_signals,
    _build_selected_material_reference,
    _build_selected_material_risk_guardrails,
)
from app.services.duration_profile_service import infer_duration_profile
from app.services.short_drama_testing_normalizers import (
    as_clean_text_list as _as_clean_text_list,
    merge_testing_canon_packet as _merge_testing_canon_packet,
    normalize_testing_canon_packet as _normalize_testing_canon_packet,
    normalize_testing_episode_contract as _normalize_testing_episode_contract,
    normalize_testing_episode_memory_cards as _normalize_testing_episode_memory_cards,
    normalize_testing_series_simulation_packet as _normalize_testing_series_simulation_packet,
    testing_workflow_context_defaults as _testing_workflow_context_defaults,
)
from app.services.short_drama_session_metadata import (
    build_startup_checklist as _build_startup_checklist,
    deep_merge as _deep_merge,
    dump_metadata as _dump_metadata,
    ensure_is_session as _ensure_is_session,
    get_session_task as _get_session_task,
    load_metadata as _load_metadata,
    now_iso as _now_iso,
    save_metadata as _save_metadata,
)
from app.services.short_drama_state_cards import (
    build_relationship_guardrail_block as _build_relationship_guardrail_block,
    build_testing_state_cards_block as _build_testing_state_cards_block,
    card_availability_status as _card_availability_status,
    normalize_testing_state_cards as _normalize_testing_state_cards,
    strength_tier_rule as _strength_tier_rule,
)
from app.services.short_drama_workspace_blocks import (
    build_workspace_character_block as _build_workspace_character_block,
    build_workspace_concept_block as _build_workspace_concept_block,
    build_workspace_scene_block as _build_workspace_scene_block,
    condense_text as _condense_text,
    derive_workspace_project_type as _derive_workspace_project_type,
)
from app.services.short_drama_text_format import (
    count_testing_chars as _count_testing_chars,
    hard_truncate_by_sentence as _hard_truncate_by_sentence,
    is_testing_header_line as _is_testing_header_line,
    normalize_counting_text as _normalize_counting_text,
)
from app.services.short_drama_quality_helpers import (
    build_acceptance_gate_warning as _build_acceptance_gate_warning,
    build_step_result_extras as _build_step_result_extras,
    coerce_generation_text as _coerce_generation_text,
    derive_quality_step_guidance as _derive_quality_step_guidance,
    extract_step_text as _extract_step_text,
    normalize_quality_dimension as _normalize_quality_dimension,
    project_config_value as _project_config_value,
)
from app.services.short_drama_rule_resolver import (
    SAMPLE_TRACK_TO_RULE,
    SUBGENRE_TRACK_TO_RULE,
    infer_sample_track_rule_name_from_variables as _infer_sample_track_rule_name_from_variables,
    infer_subgenre_rule_name_from_variables as _infer_subgenre_rule_name_from_variables,
    load_agent_prompt as _load_agent_prompt,
    load_step_template as _load_step_template,
    prompts_dir as _prompts_dir,
    resolve_rules_injection as _resolve_rules_injection,
    resolve_sample_track_rule_name_from_variables as _resolve_sample_track_rule_name_from_variables,
    resolve_subgenre_rule_name_from_variables as _resolve_subgenre_rule_name_from_variables,
    try_load_rule as _try_load_rule,
)
from app.services.short_drama_workflow_config import (
    KIND,
    SCRIPT_DRAFT_MODES,
    STEP_ID,
    STEP_LABELS,
    STEP_PROMPT_FILE,
    STEP_SYSTEM_PROMPT_FILE,
    workflow_step_order_for_project as _workflow_step_order_for_project,
)
from app.services.skill_workflow_service import recommend_skill_workflow
from app.services.text_generation_service import (
    TextGenerationError,
    begin_usage_collection,
    end_usage_collection,
    generate_json,
    generate_text,
    generate_text_stream,
)
from app.schemas.short_drama_writing import (
    BenchmarkAssessment,
    ContinuityAssessment,
    ExportRequest,
    ExportResponse,
    IssueFeedbackRefreshRequest,
    IssueFeedbackRefreshResponse,
    MaterialSelectionRequest,
    MaterialSelectionResponse,
    RunStepRequest,
    SaveStepRequest,
    SessionCreateRequest,
    SessionDetail,
    SessionListItem,
    SessionUpdateRequest,
    StartupChecklistItem,
    StartupContextResponse,
    StepResult,
    TestingFailureAnalysis,
    TestingScriptAutoFixResponse,
    TestingScriptDeepAuditResponse,
    TestingScriptRequest,
    TestingScriptResponse,
    TestingScriptValidationRequest,
    TestingScriptValidationResponse,
    SceneSuggestRequest,
    SceneSuggestResponse,
    ScenePatchRequest,
    ScenePatchResponse,
    TestingResumeQuery,
    TestingResumeResponse,
)


router = APIRouter(prefix="/admin/short-drama", tags=["Admin Short Drama"])

TESTING_SCRIPT_SCENE_PROMPT_FILE = "05_script_test_scene.md"

# TESTING_SEGMENT_TASKS / TESTING_SEGMENT_TASKS_REALISTIC_FAMILY /
# REALISTIC_FAMILY_TRACKS / _resolve_segment_task
# 已抽到 app.services.short_drama_segment_tasks
from app.services.short_drama_segment_tasks import (  # noqa: E402
    TESTING_SEGMENT_TASKS,
    TESTING_SEGMENT_TASKS_REALISTIC_FAMILY,
    REALISTIC_FAMILY_TRACKS,
    resolve_segment_task as _resolve_segment_task,
)


# _extract_episode_keywords / _build_lockword_block / _build_segment_intent_block
# 已抽到 app.services.short_drama_episode_locks
from app.services.short_drama_episode_locks import (  # noqa: E402
    extract_episode_keywords as _extract_episode_keywords,
    build_lockword_block as _build_lockword_block,
    build_segment_intent_block as _build_segment_intent_block,
)


# market_check 门控阈值
MARKET_CHECK_REJECT_VERDICT = "reject"  # 硬阻断
MARKET_CHECK_WARN_VERDICT   = "warn"    # 软警告（前端提示，API 仍返回 200 但含 warning 字段）

# concept 商业性软阻断阈值（commercial_score < 此值时在响应中附加 warning）
# 修复32: 用户尚未接入有效市场数据，先禁用商业性判断（设为 -1 永不触发警告）
CONCEPT_COMMERCIAL_SCORE_WARN_THRESHOLD = -1
# 同样禁用 market_check 的"X项通过"软警告（同源问题：纯靠 LLM 瞎猜）
MARKET_CHECK_WARN_DISABLED = True

# quality_check 打回阈值（与 reviewer-quality-score.md 保持同步）
QUALITY_PASS_MIN_TOTAL_ORIGINAL = 42    # 原创项目（满分60）
QUALITY_PASS_MIN_TOTAL_NOVEL    = 49    # 小说IP改编（满分70）

# ── 步骤分级：项目级 vs 每集级 ────────────────────────────────────────────────
# 项目级步骤一个 session 只跑一次，写入 metadata["steps"][step_id]
# 每集级步骤每集独立一份，写入 metadata["episodes"][str(ep)]["steps"][step_id]
# ── P2-修复12: 温度策略分层 ──────────────────────────────────────────────
# 结构化步骤：temperature=0.0（确定性，避免 JSON 漂移）
# 节拍/分场：0.4（轻度发散）
# 创作步骤：0.7（保留随机性）
STEP_TEMPERATURE_PROFILE: dict[str, float] = {
    "project_init_check": 0.0,
    "novel_analysis": 0.3,
    "character_lock": 0.0,
    "market_check": 0.0,
    "concept": 0.2,
    "characters": 0.4,
    "episode_outlines": 0.3,  # 结构化骨架，温度低些
    "beat_sheet": 0.4,
    "scene_list": 0.5,
    "script_draft": 0.7,
    "quality_check": 0.0,
    "narrative_consistency": 0.0,
    "compliance_check": 0.0,
    "storyboard": 0.5,
}


def _resolve_step_temperature(step_id: str, override: Optional[float]) -> Optional[float]:
    """如果调用方传了温度，尊重；否则按步骤性质选择。"""
    if override is not None:
        return override
    return STEP_TEMPERATURE_PROFILE.get(step_id)


PROJECT_LEVEL_STEPS: set[str] = {
    "project_init_check",
    "novel_analysis",
    "character_lock",
    "market_check",
    "concept",
    "characters",
    "episode_outlines",  # 修复 30
    "beat_sheet",
}
# PER_EPISODE_STEPS / _is_per_episode_step / _get_step_payload / _set_step_payload /
# _list_episodes_with_steps 已抽到 app.services.short_drama_step_payload
from app.services.short_drama_step_payload import (  # noqa: E402
    PER_EPISODE_STEPS,
    is_per_episode_step as _is_per_episode_step,
    get_step_payload as _get_step_payload,
    set_step_payload as _set_step_payload,
    list_episodes_with_steps as _list_episodes_with_steps,
)


# _slice_beat_sheet_by_episode / _slice_novel_anchor_by_episode
# 已抽到 app.services.short_drama_episode_slicers
from app.services.short_drama_episode_slicers import (  # noqa: E402
    slice_beat_sheet_by_episode as _slice_beat_sheet_by_episode,
    slice_novel_anchor_by_episode as _slice_novel_anchor_by_episode,
)


# ── Bug Fix #5: 补齐 episode_novel_anchor / novel_analysis / market_check 等变量
KNOWN_TEMPLATE_KEYS: tuple[str, ...] = (
    "project_type",
    "episode_count",
    "episode_minutes",
    "audience_axis",
    "genre_main",
    "genre_sub",
    "subgenre_track",
    "sample_track",
    "rule_profile",
    "constraints",
    "brief",
    "novel_input",
    "novel_analysis",
    "locked_characters",
    "market_check",
    "concept",
    "characters",
    "world_rules",
    "relationship_guardrails",
    "state_cards_block",
    "golden_finger_rules",
    "conflict_plan",
    "material_references",
    "material_borrow_focus",
    "material_heat_signals",
    "material_risk_guardrails",
    "material_do_not_copy",
    "issue_feedback_summary",
    "negative_prompt_hints",
    "review_focus",
    "storyboard_requirements",
    "beat_sheet",
    "scene_list",
    "script_draft",
    "quality_report",
    "compliance_report",
    "draft_episode",
    "episode_novel_anchor",   # Bug Fix #5: 小说IP改编锚点
    "episode_beat",           # 修复3: beat_sheet 按集切片
    # 修复17/30: 分批生成
    "batch_start",
    "batch_end",
    "prev_batches_summary",
    # 修复30: 集纲注入下游
    "episode_outlines_block",
    "current_episode_outline",
    # 修复20/21: 已用爆点池 + 集尾倒钩
    "used_beats_block",
    "previous_cliffhanger",
    "scene_header_style",
    "commercial_score",       # concept 输出的商业性预判分数
    "primary_archetype",      # P4-H：concept 输出的主情节原型（对标 plot_archetypes.md）
    "secondary_archetype",    # P4-H：concept 输出的辅情节原型
    # RAG 注入变量（与 config.yaml 的 step_bindings.inject_as 一致）
    "rag_asset_references",
    "rag_market_signals",
    "rag_novel_chapters",
    "rag_script_references",
    "rag_character_references",
    "rag_beat_references",
    "rag_review_references",
)


# ============================================================
# Helpers
# ============================================================









# _hydrate_session_project_runtime_context 已抽到 app.services.short_drama_session_hydrate
from app.services.short_drama_session_hydrate import (  # noqa: E402
    hydrate_session_project_runtime_context as _hydrate_session_project_runtime_context,
)


# _build_base_template_vars 已抽到 app.services.short_drama_template_vars
from app.services.short_drama_template_vars import (  # noqa: E402
    build_base_template_vars as _build_base_template_vars_svc,
)


def _build_base_template_vars(metadata: dict, *, draft_episode: int) -> dict[str, str]:
    return _build_base_template_vars_svc(metadata, draft_episode=draft_episode, known_template_keys=KNOWN_TEMPLATE_KEYS)


# _load_testing_project_payload / _enrich_testing_request_from_project 已抽到
# app.services.short_drama_testing_enrich
from app.services.short_drama_testing_enrich import (  # noqa: E402
    enrich_testing_request_from_project as _enrich_testing_request_from_project,
    load_testing_project_payload as _load_testing_project_payload,
)


# _render_step_prompt / _system_prompt_for_step 已抽到 app.services.short_drama_step_prompts
# _render_testing_scene_prompt 已抽到 app.services.short_drama_scene_generation
from app.services.short_drama_step_prompts import (  # noqa: E402
    render_step_prompt as _render_step_prompt,
    system_prompt_for_step as _system_prompt_for_step,
)
from app.services.short_drama_scene_generation import _render_testing_scene_prompt  # noqa: E402,F401


# _infer_testing_sample_track / _build_testing_quality_anchor_block
# 已抽到 app.services.short_drama_quality_anchors
from app.services.short_drama_quality_anchors import (  # noqa: E402
    build_testing_quality_anchor_block as _build_testing_quality_anchor_block,
    infer_testing_sample_track as _infer_testing_sample_track,
)


# _build_testing_length_rule / _build_testing_format_rule
# 已抽到 app.services.short_drama_testing_rules
from app.services.short_drama_testing_rules import (  # noqa: E402
    build_testing_length_rule as _build_testing_length_rule,
    build_testing_format_rule as _build_testing_format_rule,
)


# _normalize_testing_generated_content / _expected_testing_scene_header /
# _apply_testing_hard_repairs / _detect_segment_overlap_issue 已抽到 app.services.short_drama_format_repairs
from app.services.short_drama_format_repairs import (  # noqa: E402
    normalize_testing_generated_content as _normalize_testing_generated_content,
    expected_testing_scene_header as _expected_testing_scene_header,
    apply_testing_hard_repairs as _apply_testing_hard_repairs,
    detect_segment_overlap_issue as _detect_segment_overlap_issue,
)


# _validate_testing_script_output / _analyze_testing_character_health /
# _detect_relationship_updates / _detect_state_card_suggestions 已抽到
# app.services.short_drama_detection_helpers
from app.services.short_drama_detection_helpers import (  # noqa: E402
    validate_testing_script_output as _validate_testing_script_output,
    analyze_testing_character_health as _analyze_testing_character_health,
    detect_relationship_updates as _detect_relationship_updates,
    detect_state_card_suggestions as _detect_state_card_suggestions,
)








# _RAG_2026_RULE_DATASETS / _augment_2026_rule_rag_query / _apply_rag_injection
# 已抽到 app.services.short_drama_rag_injection
from app.services.short_drama_rag_injection import (  # noqa: E402
    RAG_2026_RULE_DATASETS as _RAG_2026_RULE_DATASETS,
    apply_rag_injection as _apply_rag_injection,
    augment_2026_rule_rag_query as _augment_2026_rule_rag_query,
)


# _step_generation_payload / _derive_category_path / _build_startup_context
# 已抽到 app.services.short_drama_step_prompts
from app.services.short_drama_step_prompts import (  # noqa: E402
    derive_category_path as _derive_category_path,
    build_startup_context as _build_startup_context_svc,
    step_generation_payload as _step_generation_payload_svc,
)


async def _step_generation_payload(step_id: STEP_ID, metadata: dict, req_vars: dict[str, Any], *, draft_episode: int) -> tuple[dict[str, str], str, str, list[dict[str, Any]]]:
    return await _step_generation_payload_svc(step_id, metadata, req_vars, draft_episode=draft_episode, known_template_keys=KNOWN_TEMPLATE_KEYS)


def _build_startup_context(metadata: dict, recommended_materials: list[dict[str, Any]] | None = None) -> StartupContextResponse:
    return _build_startup_context_svc(metadata, recommended_materials)


# _build_segment_lite_prompt 已抽到 app.services.short_drama_scene_generation
from app.services.short_drama_scene_generation import (  # noqa: E402
    build_segment_lite_prompt as _build_segment_lite_prompt,
)


# _review_testing_scene_quality 已抽到 app.services.short_drama_evaluation_pipeline
from app.services.short_drama_evaluation_pipeline import (  # noqa: E402
    review_testing_scene_quality as _review_testing_scene_quality,
)


# _detect_testing_narrative_logic_issues 已抽到 app.services.short_drama_detection_helpers
from app.services.short_drama_detection_helpers import (  # noqa: E402
    detect_testing_narrative_logic_issues as _detect_testing_narrative_logic_issues,
)


# _normalize_testing_story_text / _contains_testing_story_markers /
# _detect_testing_narrative_drift_issues 已抽到 app.services.short_drama_narrative_drift
from app.services.short_drama_narrative_drift import (  # noqa: E402
    normalize_testing_story_text as _normalize_testing_story_text,
    contains_testing_story_markers as _contains_testing_story_markers,
    detect_testing_narrative_drift_issues as _detect_testing_narrative_drift_issues,
)


# _detect_testing_episode_contract_issues / _evaluate_testing_scene /
# _extract_testing_structured_updates 已抽到 app.services.short_drama_evaluate_scene
from app.services.short_drama_evaluate_scene import (  # noqa: E402
    detect_testing_episode_contract_issues as _detect_testing_episode_contract_issues,
    evaluate_testing_scene as _evaluate_testing_scene,
    extract_testing_structured_updates as _extract_testing_structured_updates,
)


# _evaluation_score / _apply_scene_level_gate 已抽到 app.services.short_drama_evaluation_pipeline
from app.services.short_drama_evaluation_pipeline import (  # noqa: E402
    evaluation_score as _evaluation_score,
    apply_scene_level_gate as _apply_scene_level_gate_svc,
)
from app.services.short_drama_final_generation_contract import (  # noqa: E402
    current_testing_final_generation_contract as _current_testing_final_generation_contract,
)


def _apply_scene_level_gate(req: "TestingScriptRequest", evaluation: dict[str, Any]) -> dict[str, Any]:
    return _apply_scene_level_gate_svc(req, evaluation, _current_testing_final_generation_contract(req))


# _generation_kwargs_from_req / _generation_kwargs_from_metadata 已抽到 app.services.short_drama_deep_audit
from app.services.short_drama_deep_audit import (  # noqa: E402
    generation_kwargs_from_req as _generation_kwargs_from_req,
    generation_kwargs_from_metadata as _generation_kwargs_from_metadata,
)


# _string_list / _build_previous_episode_brief_block / _build_future_episode_brief_block
# 已抽到 app.services.short_drama_testing_blocks
from app.services.short_drama_testing_blocks import (  # noqa: E402
    build_future_episode_brief_block as _build_future_episode_brief_block,
    build_previous_episode_brief_block as _build_previous_episode_brief_block,
    string_list as _string_list,
)


# _infer_testing_contract_guardrails / _episode_contract_from_brief /
# _build_testing_series_simulation_packet / _current_testing_episode_contract /
# _format_testing_episode_contract_block / _build_testing_continuity_guardrails
# 已抽到 app.services.short_drama_episode_contract
from app.services.short_drama_episode_contract import (  # noqa: E402
    infer_testing_contract_guardrails as _infer_testing_contract_guardrails,
    episode_contract_from_brief as _episode_contract_from_brief,
    build_testing_series_simulation_packet as _build_testing_series_simulation_packet,
    current_testing_episode_contract as _current_testing_episode_contract,
    format_testing_episode_contract_block as _format_testing_episode_contract_block,
    build_testing_continuity_guardrails as _build_testing_continuity_guardrails,
)


# _build_inferred_canon_packet / _format_testing_canon_block /
# _build_testing_episode_memory_block 已抽到 app.services.short_drama_canon_blocks
from app.services.short_drama_canon_blocks import (  # noqa: E402
    build_inferred_canon_packet as _build_inferred_canon_packet,
    format_testing_canon_block as _format_testing_canon_block,
    build_testing_episode_memory_block as _build_testing_episode_memory_block,
)


# _build_testing_material_context / _build_testing_issue_feedback_context /
# _build_testing_report_context 已抽到 app.services.short_drama_testing_contexts
from app.services.short_drama_testing_contexts import (  # noqa: E402
    build_testing_material_context as _build_testing_material_context,
    build_testing_issue_feedback_context as _build_testing_issue_feedback_context,
    build_testing_report_context as _build_testing_report_context,
)


# _make_testing_rag_card / _infer_testing_top_script_pattern_cards /
# _compile_testing_rag_context_cards / _select_testing_rag_cards_for_segment /
# _format_testing_rag_context_pack / _build_testing_rule_context /
# _build_testing_rag_context 已抽到 app.services.short_drama_rag_cards
from app.services.short_drama_rag_cards import (  # noqa: E402
    make_testing_rag_card as _make_testing_rag_card,
    infer_testing_top_script_pattern_cards as _infer_testing_top_script_pattern_cards,
    compile_testing_rag_context_cards as _compile_testing_rag_context_cards,
    select_testing_rag_cards_for_segment as _select_testing_rag_cards_for_segment,
    format_testing_rag_context_pack as _format_testing_rag_context_pack,
    build_testing_rule_context as _build_testing_rule_context,
    build_testing_rag_context as _build_testing_rag_context,
)


# _build_testing_segment_focus_block / _build_testing_segment_character_mini_block /
# _build_testing_segment_confirmed_context_block / _build_testing_segment_guardrail_block
# 已抽到 app.services.short_drama_segment_blocks
from app.services.short_drama_segment_blocks import (  # noqa: E402
    build_testing_segment_focus_block as _build_testing_segment_focus_block,
    build_testing_segment_character_mini_block as _build_testing_segment_character_mini_block,
    build_testing_segment_confirmed_context_block as _build_testing_segment_confirmed_context_block,
    build_testing_segment_guardrail_block as _build_testing_segment_guardrail_block,
)


# _STRUCTURED_UPDATE_CACHE / _structured_update_fingerprint 已抽到 app.services.short_drama_evaluation_pipeline
from app.services.short_drama_evaluation_pipeline import (  # noqa: E402
    STRUCTURED_UPDATE_CACHE as _STRUCTURED_UPDATE_CACHE,
    STRUCTURED_UPDATE_CACHE_MAX as _STRUCTURED_UPDATE_CACHE_MAX,
    structured_update_fingerprint as _structured_update_fingerprint,
)


# _fallback_episode_memory_card 已抽到 app.services.short_drama_evaluation_pipeline
from app.services.short_drama_evaluation_pipeline import (  # noqa: E402
    fallback_episode_memory_card as _fallback_episode_memory_card,
)


# _testing_script_body_lines / _testing_os_line_count 已抽到 app.services.short_drama_seam_continuity
from app.services.short_drama_seam_continuity import (  # noqa: E402
    testing_script_body_lines as _testing_script_body_lines,
    testing_os_line_count as _testing_os_line_count,
)


# _detect_testing_local_patch_issues / _dialogue_body_for_testing /
# _detect_testing_head_quality_issues / _apply_testing_benchmark_caps /
# _fallback_benchmark_assessment 已抽到 app.services.short_drama_benchmark_assessment
from app.services import short_drama_benchmark_assessment as _benchmark_assessment_svc  # noqa: E402


def _detect_testing_local_patch_issues(req: "TestingScriptRequest", content_text: str) -> list[str]:
    return _benchmark_assessment_svc.detect_testing_local_patch_issues(req, content_text)


def _dialogue_body_for_testing(line: str) -> str:
    return _benchmark_assessment_svc.dialogue_body_for_testing(line)


def _detect_testing_head_quality_issues(req: "TestingScriptRequest", content_text: str) -> list[str]:
    return _benchmark_assessment_svc.detect_testing_head_quality_issues(
        req, content_text, _current_testing_final_generation_contract(req),
    )


def _apply_testing_benchmark_caps(
    req: "TestingScriptRequest",
    benchmark: "BenchmarkAssessment",
    evaluation: dict[str, Any],
    episode_text: str,
) -> "BenchmarkAssessment":
    return _benchmark_assessment_svc.apply_testing_benchmark_caps(
        req, benchmark, evaluation, episode_text, _current_testing_final_generation_contract(req),
    )


def _fallback_benchmark_assessment(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
) -> "BenchmarkAssessment":
    return _benchmark_assessment_svc.fallback_benchmark_assessment(
        req, evaluation, _current_testing_final_generation_contract(req),
    )


# _testing_char_bigrams / _testing_overlap_ratio / _previous_testing_tail_block /
# _assess_testing_episode_seam / _apply_testing_seam_gate_to_continuity /
# _fallback_continuity_assessment 已抽到 app.services.short_drama_seam_continuity
from app.services.short_drama_seam_continuity import (  # noqa: E402
    testing_char_bigrams as _testing_char_bigrams,
    testing_overlap_ratio as _testing_overlap_ratio,
    previous_testing_tail_block as _previous_testing_tail_block,
    assess_testing_episode_seam as _assess_testing_episode_seam,
    apply_testing_seam_gate_to_continuity as _apply_testing_seam_gate_to_continuity,
    fallback_continuity_assessment as _fallback_continuity_assessment,
)


# _build_relationship_diff_block 已抽到 app.services.short_drama_testing_blocks
from app.services.short_drama_testing_blocks import (  # noqa: E402
    build_relationship_diff_block as _build_relationship_diff_block,
)


# _DEEP_AUDIT_CACHE / _deep_audit_fingerprint 已抽到 app.services.short_drama_seam_continuity
from app.services.short_drama_seam_continuity import (  # noqa: E402
    DEEP_AUDIT_CACHE as _DEEP_AUDIT_CACHE,
    DEEP_AUDIT_CACHE_MAX as _DEEP_AUDIT_CACHE_MAX,
    deep_audit_fingerprint as _deep_audit_fingerprint,
)


# _run_testing_deep_audit 已抽到 app.services.short_drama_deep_audit
from app.services.short_drama_deep_audit import run_testing_deep_audit as _run_testing_deep_audit_svc  # noqa: E402


def _run_testing_deep_audit(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
) -> tuple["BenchmarkAssessment", "ContinuityAssessment"]:
    return _run_testing_deep_audit_svc(req, evaluation, _current_testing_final_generation_contract(req))


# _classify_testing_failure 已抽到 app.services.short_drama_failure_classifier
from app.services.short_drama_failure_classifier import (  # noqa: E402
    classify_testing_failure as _classify_testing_failure,
)


from app.services.short_drama_testing_failure import (  # noqa: E402
    build_testing_skill_workflow as _build_testing_skill_workflow,
    log_testing_failure_analysis as _log_testing_failure_analysis,
)


# _build_internal_rewrite_prompt / _testing_character_names_by_ids /
# _testing_fallback_speaker / _insert_testing_line_after_header /
# _apply_testing_narrative_autofix_fallback / _build_testing_autofix_directives /
# _auto_fix_testing_script_content 已抽到 app.services.short_drama_autofix
from app.services.short_drama_autofix import (  # noqa: E402
    build_internal_rewrite_prompt as _build_internal_rewrite_prompt,
    testing_character_names_by_ids as _testing_character_names_by_ids,
    testing_fallback_speaker as _testing_fallback_speaker,
    insert_testing_line_after_header as _insert_testing_line_after_header,
    apply_testing_narrative_autofix_fallback as _apply_testing_narrative_autofix_fallback,
    build_testing_autofix_directives as _build_testing_autofix_directives,
    auto_fix_testing_script_content as _auto_fix_testing_script_content,
)


# _generate_testing_scene_passed / _prepare_testing_script_generation
# 已抽到 app.services.short_drama_scene_generation
from app.services.short_drama_scene_generation import (  # noqa: E402
    generate_testing_scene_passed as _generate_testing_scene_passed,
    prepare_testing_script_generation as _prepare_testing_script_generation,
)


# ============================================================
# Routes
# ============================================================

# /testing/script-scene 同步/流式生成 已抽到 app.routers.short_drama.scene_routes

# /testing/script-scene/validate, /deep-audit, /auto-fix 已抽到 app.routers.short_drama.audit_routes


# /testing/resume 已抽到 app.routers.short_drama.resume_routes


# sessions CRUD（POST /sessions, GET /sessions, GET /sessions/{id}, PUT /sessions/{id}）
# 已抽到 app.routers.short_drama.sessions_crud_routes


# /sessions/{task_id}/startup-context, /materials/recommend, /materials/select,
# /issue-feedback/refresh 已抽到 app.routers.short_drama.session_routes


# /sessions/{task_id}/run-step / save-step / run-step-stream
# 已抽到 app.routers.short_drama.step_routes


# ── 从 short_drama 子包聚合的轻量路由 ──────────────────────────────────────
from app.routers.short_drama import audit_routes as _audit_routes  # noqa: E402
from app.routers.short_drama import session_routes as _session_routes  # noqa: E402
from app.routers.short_drama import step_routes as _step_routes  # noqa: E402
from app.routers.short_drama import scene_routes as _scene_routes  # noqa: E402
from app.routers.short_drama import scene_edit_routes as _scene_edit_routes  # noqa: E402
from app.routers.short_drama import resume_routes as _resume_routes  # noqa: E402
from app.routers.short_drama import sessions_crud_routes as _sessions_crud_routes  # noqa: E402
from app.routers.short_drama import export_routes as _export_routes  # noqa: E402
from app.routers.short_drama import advanced_generation_routes as _advanced_generation_routes  # noqa: E402
router.include_router(_audit_routes.router)
router.include_router(_session_routes.router)
router.include_router(_step_routes.router)
router.include_router(_scene_routes.router)
router.include_router(_scene_edit_routes.router)
router.include_router(_resume_routes.router)
router.include_router(_sessions_crud_routes.router)
router.include_router(_export_routes.router)
router.include_router(_advanced_generation_routes.router)
