from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.services.short_drama_workflow_config import STEP_ID


class SessionCreateRequest(BaseModel):
    name: str = Field(..., description="会话名称")
    description: str = Field("", description="会话说明")

    project: dict[str, Any] = Field(default_factory=dict, description="项目信息（project_type/episode_count/...）")
    inputs: dict[str, Any] = Field(default_factory=dict, description="写作输入（brief/world_rules/...）")


class SessionListItem(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionDetail(SessionListItem):
    pass


class SessionUpdateRequest(BaseModel):
    metadata: Optional[dict[str, Any]] = Field(default=None, description="完整替换 metadata")
    patch: Optional[dict[str, Any]] = Field(default=None, description="对 metadata 做深度合并 patch")


class RunStepRequest(BaseModel):
    step_id: STEP_ID
    draft_episode: int = Field(default=1, ge=1)
    template_vars: dict[str, Any] = Field(default_factory=dict)
    temperature: Optional[float] = None


class StepResult(BaseModel):
    step_id: STEP_ID
    context_output: str
    full_output: str
    updated_at: str
    manual_override: bool = False
    gate_warning: str = ""
    quality_verdict: str = ""
    repair_scope: str = ""
    revision_summary: str = ""
    rag_evidence: list[dict[str, Any]] = Field(default_factory=list)


class TestingScriptRequest(BaseModel):
    __test__ = False

    project_id: str = ""
    project_type: str = ""
    audience_axis: str = ""
    genre_main: str = ""
    genre_sub: str = ""
    subgenre_track: str = ""
    sample_track: str = ""
    format_type: str = "真人短剧"
    episode_count: int = Field(default=1, ge=1)
    episode_minutes: float = Field(default=1.5, ge=0.5)
    scene_header_style: Literal["bracket", "plain"] = "bracket"
    brief: str = ""
    golden_finger: str = ""
    worldview: str = ""
    conflict: str = ""
    episode_no: int = Field(default=1, ge=1)
    scene_no: int = Field(default=1, ge=1)
    episode_title: str = ""
    episode_summary: str = ""
    episode_conflict: str = ""
    episode_hook: str = ""
    current_content: str = ""
    continuity_notes: str = ""
    relationship_guardrails: str = ""
    word_count_target: Optional[int] = Field(default=None, ge=0)
    word_count_min: Optional[int] = Field(default=None, ge=0)
    word_count_max: Optional[int] = Field(default=None, ge=0)
    exclude_punctuation_for_count: bool = True
    enforce_standard_format: bool = True
    target_chars: Optional[int] = Field(default=None, ge=0)
    mode: Literal["scene", "segment"] = "scene"
    segment_id: Optional[Literal["hook", "validation", "explosion", "resolution"]] = None
    selected_character_ids: list[str] = Field(default_factory=list)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    state_cards: dict[str, Any] = Field(default_factory=dict)
    series_title: str = ""
    episode_content: str = ""
    previous_episode_briefs: list[dict[str, Any]] = Field(default_factory=list)
    future_episode_briefs: list[dict[str, Any]] = Field(default_factory=list)
    previous_relationship_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    episode_memory_cards: list[dict[str, Any]] = Field(default_factory=list)
    canon_packet: dict[str, Any] = Field(default_factory=dict)
    manual_edit_context: dict[str, Any] = Field(default_factory=dict)
    step_confirmation_packet: dict[str, Any] = Field(default_factory=dict)
    user_confirmed_generation_packet: dict[str, Any] = Field(default_factory=dict)
    series_simulation_packet: dict[str, Any] = Field(default_factory=dict)
    episode_contract: dict[str, Any] = Field(default_factory=dict)
    generation_source_packet: dict[str, Any] = Field(default_factory=dict)
    previous_episode_continuity_packet: dict[str, Any] = Field(default_factory=dict)
    final_generation_contract: dict[str, Any] = Field(default_factory=dict)
    director_blueprint: dict[str, Any] = Field(default_factory=dict)
    director_blueprint_hash: str = ""
    writer_brief_hash: str = ""
    review_contract_hash: str = ""
    materials: list[dict[str, Any]] = Field(default_factory=list)
    issue_feedback: dict[str, Any] = Field(default_factory=dict)
    rule_profile: str = ""
    world_rules: str = ""
    golden_finger_rules: str = ""
    conflict_plan: str = ""
    quality_report: dict[str, Any] = Field(default_factory=dict)
    compliance_report: dict[str, Any] = Field(default_factory=dict)
    episode_novel_anchor: str = ""
    rag_asset_references: str = ""
    rag_market_signals: str = ""
    rag_novel_chapters: str = ""
    rag_script_references: str = ""
    rag_character_references: str = ""
    rag_beat_references: str = ""
    rag_review_references: str = ""
    rag_context_pack: dict[str, Any] = Field(default_factory=dict)
    generation_provider: str = ""
    generation_model: str = ""
    generation_timeout_seconds: Optional[int] = Field(default=None, ge=1)
    generation_max_retries: Optional[int] = Field(default=None, ge=1)
    autofix_lightweight_validation: bool = False
    autofix_single_pass: bool = False
    advanced_generation_mode: bool = False
    advanced_generation_profile_id: str = ""
    advanced_generation_providers: dict[str, Any] = Field(default_factory=dict)
    advanced_generation_routes: dict[str, Any] = Field(default_factory=dict)
    temperature: Optional[float] = None


class BenchmarkAssessment(BaseModel):
    track_name: str = ""
    score: int = 0
    raw_score: int | None = None
    human_projection_score: int | None = None
    human_projection_passed: bool | None = None
    calibration_note: str = ""
    passed: bool = False
    summary: str = ""
    matched_signals: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    rule_upgrades: list[str] = Field(default_factory=list)


class ContinuityAssessment(BaseModel):
    checked_episode_span: str = ""
    score: int = 0
    raw_score: int | None = None
    human_projection_score: int | None = None
    human_projection_passed: bool | None = None
    calibration_note: str = ""
    calibration_only_failure: bool = False
    passed: bool = False
    summary: str = ""
    preserved_anchors: list[str] = Field(default_factory=list)
    relationship_risks: list[str] = Field(default_factory=list)
    plot_risks: list[str] = Field(default_factory=list)


class TestingScriptResponse(BaseModel):
    content: str
    char_count_excluding_punctuation: int
    overflow_content: str = ""
    warnings: list[str] = Field(default_factory=list)
    benchmark_assessment: BenchmarkAssessment = Field(default_factory=BenchmarkAssessment)
    continuity_assessment: ContinuityAssessment = Field(default_factory=ContinuityAssessment)
    episode_memory_card: dict[str, Any] = Field(default_factory=dict)
    canon_packet: dict[str, Any] = Field(default_factory=dict)
    usage_metrics: dict[str, Any] = Field(default_factory=dict)
    rag_evidence: list[dict[str, Any]] = Field(default_factory=list)
    director_blueprint: dict[str, Any] = Field(default_factory=dict)
    generation_trace: dict[str, Any] = Field(default_factory=dict)


class TestingFailureAnalysis(BaseModel):
    failure_type: str = ""
    failed_segment: str = ""
    root_cause: str = ""
    fix_strategy: str = ""
    repair_scope: str = ""
    rollback_recommendation: str = ""
    evidence: list[str] = Field(default_factory=list)


class TestingScriptValidationRequest(TestingScriptRequest):
    scene_content: str = ""


class TestingScriptValidationResponse(BaseModel):
    char_count_excluding_punctuation: int
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    present_character_ids: list[str] = Field(default_factory=list)
    health_items: list[dict[str, Any]] = Field(default_factory=list)
    relationship_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    state_card_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    benchmark_assessment: BenchmarkAssessment = Field(default_factory=BenchmarkAssessment)
    continuity_assessment: ContinuityAssessment = Field(default_factory=ContinuityAssessment)
    failure_analysis: TestingFailureAnalysis = Field(default_factory=TestingFailureAnalysis)
    skill_workflow: dict[str, Any] = Field(default_factory=dict)
    episode_memory_card: dict[str, Any] = Field(default_factory=dict)
    canon_packet: dict[str, Any] = Field(default_factory=dict)


class TestingScriptAutoFixResponse(BaseModel):
    success: bool
    content: str
    char_count_excluding_punctuation: int
    overflow_content: str = ""
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    present_character_ids: list[str] = Field(default_factory=list)
    health_items: list[dict[str, Any]] = Field(default_factory=list)
    relationship_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    state_card_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    benchmark_assessment: BenchmarkAssessment = Field(default_factory=BenchmarkAssessment)
    continuity_assessment: ContinuityAssessment = Field(default_factory=ContinuityAssessment)
    failure_analysis: TestingFailureAnalysis = Field(default_factory=TestingFailureAnalysis)
    skill_workflow: dict[str, Any] = Field(default_factory=dict)
    episode_memory_card: dict[str, Any] = Field(default_factory=dict)
    canon_packet: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class TestingScriptDeepAuditResponse(BaseModel):
    benchmark_assessment: BenchmarkAssessment = Field(default_factory=BenchmarkAssessment)
    continuity_assessment: ContinuityAssessment = Field(default_factory=ContinuityAssessment)
    failure_analysis: TestingFailureAnalysis = Field(default_factory=TestingFailureAnalysis)
    skill_workflow: dict[str, Any] = Field(default_factory=dict)


class SaveStepRequest(BaseModel):
    step_id: STEP_ID
    context_output: str = ""
    full_output: str = ""
    manual_override: bool = True
    episode_no: int = Field(default=0, ge=0, description="每集级步骤必填集号；项目级步骤填 0/不填")


class ExportRequest(BaseModel):
    format: Literal["txt", "docx"] = "docx"
    episode_no: int = Field(default=1, ge=1)
    scope: Literal["all_steps", "one_episode", "all_episodes"] = "one_episode"


class ExportResponse(BaseModel):
    path: str


class StartupChecklistItem(BaseModel):
    key: str
    label: str
    done: bool
    hint: str = ""


class StartupContextResponse(BaseModel):
    materials: list[dict[str, Any]] = Field(default_factory=list)
    recommended_materials: list[dict[str, Any]] = Field(default_factory=list)
    issue_feedback: dict[str, Any] = Field(default_factory=dict)
    startup_checklist: list[StartupChecklistItem] = Field(default_factory=list)


class MaterialSelectionRequest(BaseModel):
    material_ids: list[str] = Field(default_factory=list)


class MaterialSelectionResponse(BaseModel):
    materials: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class IssueFeedbackRefreshRequest(BaseModel):
    category_path: Optional[str] = ""


class IssueFeedbackRefreshResponse(BaseModel):
    issue_feedback: dict[str, Any] = Field(default_factory=dict)
    startup_checklist: list[StartupChecklistItem] = Field(default_factory=list)


class AdvancedGenerationStep(BaseModel):
    id: str
    label: str
    purpose: str = ""
    output_type: str = ""


class AdvancedGenerationArtifact(BaseModel):
    id: str
    label: str
    description: str = ""


class AdvancedGenerationProfile(BaseModel):
    id: str
    label: str
    status: Literal["active", "scaffold"] = "scaffold"
    project_type_aliases: list[str] = Field(default_factory=list)
    rule_scopes: list[str] = Field(default_factory=list)
    workflow_steps: list[AdvancedGenerationStep] = Field(default_factory=list)
    artifacts: list[AdvancedGenerationArtifact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AdvancedGenerationProfileListResponse(BaseModel):
    mode_id: str = "advanced_generation"
    mode_label: str = "高级生成模式"
    profiles: list[AdvancedGenerationProfile] = Field(default_factory=list)


class AdvancedGenerationPlanRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    base_generation_kwargs: dict[str, Any] = Field(default_factory=dict)


class AdvancedGenerationOrchestrationRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    base_generation_kwargs: dict[str, Any] = Field(default_factory=dict)
    max_review_rounds: int = Field(default=2, ge=1, le=5)


class AdvancedGenerationRoutePreview(BaseModel):
    step_id: str
    role: str
    role_label: str
    provider: str = ""
    model: str = ""
    temperature: Optional[float] = None
    reason: str = ""


class AdvancedGenerationPlanResponse(BaseModel):
    mode_id: str = "advanced_generation"
    mode_label: str = "高级生成模式"
    enabled: bool = False
    profile_id: str = "short_drama"
    profile_label: str = "短剧"
    routes: list[AdvancedGenerationRoutePreview] = Field(default_factory=list)


class AdvancedGenerationOrchestrationStatusResponse(BaseModel):
    workflow_id: str
    workflow_label: str
    available: bool = False
    backend: str = "builtin_fallback"
    degraded: bool = True
    langchain_available: bool = False
    langgraph_available: bool = False
    langchain_version: str = ""
    langgraph_version: str = ""
    compiled: bool = False
    error: str = ""


class AdvancedGenerationWorkflowNode(BaseModel):
    id: str
    role: str
    role_label: str
    step_id: str
    label: str
    provider: str = ""
    model: str = ""
    temperature: Optional[float] = None
    purpose: str = ""


class AdvancedGenerationWorkflowEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    condition: str

    model_config = {"populate_by_name": True}


class AdvancedGenerationOrchestrationPlanResponse(BaseModel):
    workflow_id: str
    workflow_label: str
    mode_id: str = "advanced_generation"
    mode_label: str = "高级生成模式"
    enabled: bool = False
    profile_id: str = "short_drama"
    profile_label: str = "短剧"
    backend: str = "builtin_fallback"
    available: bool = False
    degraded: bool = True
    compiled: bool = False
    error: str = ""
    max_review_rounds: int = 2
    entrypoint: str = "writer"
    nodes: list[AdvancedGenerationWorkflowNode] = Field(default_factory=list)
    edges: list[AdvancedGenerationWorkflowEdge] = Field(default_factory=list)
    probe_trace: list[str] = Field(default_factory=list)
    routes: list[AdvancedGenerationRoutePreview] = Field(default_factory=list)


# ── 从 router 抽出的请求/响应 schemas ─────────────────────────

class SceneSuggestRequest(BaseModel):
    project_id: str = ""
    scene_content: str
    audience_axis: str = ""
    genre_main: str = ""
    episode_title: str = ""
    episode_summary: str = ""
    episode_conflict: str = ""
    episode_hook: str = ""
    segment_id: str = ""
    confirmed_content: str = ""
    relationship_guardrails: str = ""
    characters: list[dict[str, Any]] = Field(default_factory=list)
    previous_episode_briefs: list[dict[str, Any]] = Field(default_factory=list)
    episode_contract: dict[str, Any] = Field(default_factory=dict)
    issue_feedback: dict[str, Any] = Field(default_factory=dict)
    rule_profile: str = ""

class SceneSuggestResponse(BaseModel):
    suggestions: list[str]

class ScenePatchRequest(BaseModel):
    project_id: str = ""
    full_text: str
    selected_text: str
    instruction: str
    scene_header_style: Literal["bracket", "plain"] = "bracket"

class ScenePatchResponse(BaseModel):
    replacement: str

class TestingResumeQuery(BaseModel):
    workspace_path: str
    expected_total: int = 10

class TestingResumeResponse(BaseModel):
    workspace_path: str
    progress_file: str
    project_id: str = ""
    project_name: str = ""
    completed_episodes: list[int] = Field(default_factory=list)
    pending_episodes: list[int] = Field(default_factory=list)
    failed_episodes: list[int] = Field(default_factory=list)
    last_updated: str = ""
