"""项目 V2 Pydantic schemas（从 projects_v2.py 抽出）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    """项目配置"""
    total_episodes: Optional[int] = Field(default=None, ge=1, le=200)
    confirmed_total_episodes: Optional[int] = Field(default=None, ge=1, le=200)
    suggested_total_episodes: Optional[int] = Field(default=None, ge=1, le=200)
    episode_count_status: str = "unconfirmed"
    episode_count_confirmation_source: str = ""
    episode_count_confirmed_at: str = ""
    word_count_per_episode: str = "1000-1550"
    scene_header_style: str = "bracket"  # bracket/plain
    episode_seconds: int = Field(default=90, ge=30, le=600)
    episode_minutes: float = Field(default=1.5, ge=0.5, le=10)
    manga_mode: bool = False
    premium_mode: bool = False
    advanced_generation_mode: bool = False
    advanced_generation_profile_id: str = ""
    advanced_generation_providers: dict[str, Any] = Field(default_factory=dict)
    advanced_generation_routes: dict[str, Any] = Field(default_factory=dict)
    subgenre_track: str = ""
    sample_track: str = ""
    generation_provider: str = ""
    generation_model: str = ""
    rights_capture_enabled: bool = True


class ProjectConfigPatch(BaseModel):
    """项目配置增量更新"""
    total_episodes: Optional[int] = Field(default=None, ge=1, le=200)
    confirmed_total_episodes: Optional[int] = Field(default=None, ge=1, le=200)
    suggested_total_episodes: Optional[int] = Field(default=None, ge=1, le=200)
    episode_count_status: Optional[str] = None
    episode_count_confirmation_source: Optional[str] = None
    episode_count_confirmed_at: Optional[str] = None
    word_count_per_episode: Optional[str] = None
    scene_header_style: Optional[str] = None
    episode_seconds: Optional[int] = Field(default=None, ge=30, le=600)
    episode_minutes: Optional[float] = Field(default=None, ge=0.5, le=10)
    manga_mode: Optional[bool] = None
    premium_mode: Optional[bool] = None
    advanced_generation_mode: Optional[bool] = None
    advanced_generation_profile_id: Optional[str] = None
    advanced_generation_providers: Optional[dict[str, Any]] = None
    advanced_generation_routes: Optional[dict[str, Any]] = None
    subgenre_track: Optional[str] = None
    sample_track: Optional[str] = None
    generation_provider: Optional[str] = None
    generation_model: Optional[str] = None
    rights_capture_enabled: Optional[bool] = None


class ProjectCreateRequest(BaseModel):
    """创建项目请求"""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    project_type: str = "真人短剧-男频"  # 漫剧-男频/真人短剧-女频/小说IP改编...
    audience_axis: str = "男频"  # 男频/女频/混合
    genre_main: str = "都市"
    genre_sub: str = "逆袭"
    creation_mode: str = "solo"
    config: ProjectConfig = Field(default_factory=ProjectConfig)


class ProjectUpdateRequest(BaseModel):
    """更新项目请求"""
    description: Optional[str] = None
    project_type: Optional[str] = None
    audience_axis: Optional[str] = None
    genre_main: Optional[str] = None
    genre_sub: Optional[str] = None
    creation_mode: Optional[str] = None
    config: Optional[ProjectConfigPatch] = None


class ProjectResponse(BaseModel):
    """项目响应"""
    id: str
    name: str
    description: str
    project_type: str
    audience_axis: str
    genre_main: str
    genre_sub: str
    creation_mode: str = "solo"
    rights_capture_enabled: bool = True
    total_episodes: int
    completed_episodes: int
    current_episode: int
    status: str
    workspace_path: str
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    created_at: datetime
    updated_at: datetime


class CharacterStoreRequest(BaseModel):
    characters: list[dict[str, Any]] = Field(default_factory=list)


class CharacterStoreResponse(BaseModel):
    characters: list[dict[str, Any]] = Field(default_factory=list)


class StoryStateCardStoreRequest(BaseModel):
    relationship_cards: list[dict[str, Any]] = Field(default_factory=list)
    info_cards: list[dict[str, Any]] = Field(default_factory=list)
    power_cards: list[dict[str, Any]] = Field(default_factory=list)
    promise_cards: list[dict[str, Any]] = Field(default_factory=list)
    locked_fact_cards: list[dict[str, Any]] = Field(default_factory=list)


class StoryStateCardStoreResponse(StoryStateCardStoreRequest):
    pass


class ProjectWorkflowContextRequest(BaseModel):
    workflow_context: dict[str, Any] = Field(default_factory=dict)
    canon_packet: dict[str, Any] = Field(default_factory=dict)
    episode_memory_cards: list[dict[str, Any]] = Field(default_factory=list)
    merge: bool = True


class ProjectWorkflowContextResponse(BaseModel):
    workflow_context: dict[str, Any] = Field(default_factory=dict)
    canon_packet: dict[str, Any] = Field(default_factory=dict)
    episode_memory_cards: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: str = ""


class EpisodeCreateRequest(BaseModel):
    """创建/更新集请求"""
    title: str = ""
    summary: str = ""
    status: str = "draft"


class EpisodeResponse(BaseModel):
    """集响应"""
    id: str
    episode_number: int
    title: str
    summary: str
    status: str
    total_scenes: int
    completed_scenes: int
    quality_score: float
    current_version: str
    created_at: datetime
    updated_at: datetime


class SceneCreateRequest(BaseModel):
    """创建场景请求"""
    time: str = "日"  # 日/夜/晨/昏
    location_type: str = "内"  # 内/外
    location_name: str = ""
    content: str = ""


class SceneResponse(BaseModel):
    """场景响应"""
    id: str
    scene_number: int
    scene_code: str
    time: str
    location_type: str
    location_name: str
    content: str
    content_preview: str
    word_count: int
    status: str
    primary_author: str
    ai_generated: bool
    created_at: datetime
    updated_at: datetime


class ContentSaveRequest(BaseModel):
    """保存内容请求"""
    content: str
    editor_type: str = "human"  # human/ai/skill_writer/skill_reviewer
    editor_id: str = ""
    editor_name: str = ""
    change_note: str = ""
    create_checkpoint: bool = True
    c19_178_materialization: bool = False
    manual_edit_evidence: dict[str, Any] = Field(default_factory=dict)


class VersionResponse(BaseModel):
    """版本响应"""
    id: str
    version_code: str
    parent_version: str
    editor_type: str
    editor_name: str
    diff_stats: dict
    contribution_score: float
    change_note: str
    created_at: datetime


class DiffResponse(BaseModel):
    """Diff响应"""
    old_version: str
    new_version: str
    added_lines: list
    deleted_lines: list
    modified_blocks: list
    stats: dict


class ContributionResponse(BaseModel):
    """贡献度响应"""
    user_id: str
    user_name: str
    episodes_touched: int
    scenes_written: int
    total_edits: int
    words_added: int
    words_deleted: int
    ai_generations_accepted: int
    ai_generations_modified: int
    base_score: float
    ai_collaboration_bonus: float
    final_score: float
    percentage: float


class ModelProviderRequest(BaseModel):
    """模型提供商请求"""
    name: str
    provider_type: str  # openai/claude/anthropic/custom
    base_url: str
    api_key: str
    default_model: str
    models: list[str] = Field(default_factory=list)
    rate_limit_rpm: int = 60
    rate_limit_tpm: int = 60000
    input_cost_cny_per_1k: float = 0.002
    output_cost_cny_per_1k: float = 0.008
    billing_multiplier: float = 5
    minimum_actual_cost_cny: float = 0.01


class GenerationRequest(BaseModel):
    """AI生成请求"""
    job_type: str  # scene_draft/episode_outline/continuation/revision
    episode_number: int
    scene_number: Optional[int] = None
    provider_id: Optional[str] = None  # 如不指定，使用默认提供商
    model_name: Optional[str] = None
    prompt_override: Optional[str] = None  # 自定义提示词
    temperature: float = 0.7
    extra_params: dict = Field(default_factory=dict)


class GenerationResponse(BaseModel):
    """生成任务响应"""
    job_id: str
    status: str
    message: str


class GenerationResult(BaseModel):
    """生成结果"""
    job_id: str
    status: str
    content: Optional[str] = None
    progress: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    error_message: Optional[str] = None
    gate_warning: str = ""
