"""
项目模型 v2 - 适配Skill化架构和状态外置管理
"""
import uuid
import json
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, Numeric, Index, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON

from app.database import Base


class ProjectV2(Base):
    """项目主表（轻量索引，详细状态存文件系统）"""
    __tablename__ = "project_v2"
    __table_args__ = (
        Index("ix_project_v2_owner_name", "created_by", "name", unique=True),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, default="")

    # 项目配置（从pipeline.toml继承）
    config = Column(Text, default="{}")  # JSON字符串

    # 项目类型
    project_type = Column(String(50), default="")  # 漫剧-男频/真人短剧-女频/小说IP改编...
    audience_axis = Column(String(20), default="")  # 男频/女频/混合
    genre_main = Column(String(50), default="")
    genre_sub = Column(String(50), default="")

    # 进度统计
    total_episodes = Column(Integer, default=0)
    completed_episodes = Column(Integer, default=0)
    current_episode = Column(Integer, default=1)
    status = Column(String(20), default="planning")  # planning/active/completed/archived
    creation_mode = Column(String(20), default="solo")  # solo/collab
    rights_capture_enabled = Column(Boolean, default=True)

    # 工作区路径（外置状态根目录）
    workspace_path = Column(String(500), default="")

    # 创建/更新时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    created_by = Column(String(36), default="")  # 创建者ID

    def get_config(self):
        """解析配置JSON"""
        try:
            return json.loads(self.config) if self.config else {}
        except:
            return {}

    def set_config(self, config_dict):
        """设置配置JSON"""
        self.config = json.dumps(config_dict, ensure_ascii=False)


class Episode(Base):
    """集状态表（快速查询索引）"""
    __tablename__ = "episode"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True, nullable=False)
    episode_number = Column(Integer, nullable=False)

    # 集状态
    status = Column(String(20), default="draft")  # draft/writing/review/completed
    title = Column(String(200), default="")
    summary = Column(Text, default="")  # 集摘要（用于后续集上下文）

    # 场景统计
    total_scenes = Column(Integer, default=0)
    completed_scenes = Column(Integer, default=0)

    # 质检状态
    quality_score = Column(Float, default=0)  # 质检总分
    quality_status = Column(String(20), default="pending")  # pending/passed/failed
    compliance_status = Column(String(20), default="pending")  # 合规状态

    # 版本追踪
    current_version = Column(String(20), default="v000")  # 当前最新版本
    draft_path = Column(String(500), default="")  # 草稿文件路径

    # 元数据
    meta_data = Column(Text, default="{}")  # 扩展信息JSON
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def get_metadata(self):
        try:
            return json.loads(self.meta_data) if self.meta_data else {}
        except:
            return {}

    def set_metadata(self, meta_dict):
        self.meta_data = json.dumps(meta_dict, ensure_ascii=False)


class Scene(Base):
    """场景状态表"""
    __tablename__ = "scene"
    __table_args__ = (
        UniqueConstraint("episode_id", "scene_number", name="uq_scene_episode_number"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    episode_id = Column(String(36), index=True, nullable=False)
    scene_number = Column(Integer, nullable=False)

    # 场景标识
    scene_code = Column(String(50), default="")  # 如 "13-3" 表示第13集第3场

    # 场景头信息
    time = Column(String(50), default="")  # 日/夜/晨/昏
    location_type = Column(String(20), default="")  # 内/外
    location_name = Column(String(200), default="")

    # 内容
    content = Column(Text, default="")  # 完整内容（可选，也可只存文件路径）
    content_path = Column(String(500), default="")  # 内容文件路径

    # 场景状态
    status = Column(String(20), default="draft")  # draft/writing/completed/reviewing
    word_count = Column(Integer, default=0)

    # 贡献追踪（简化存储，详细记录在版本表）
    primary_author = Column(String(36), default="")  # 主要作者
    ai_generated = Column(Boolean, default=False)  # 是否AI生成
    ai_modified = Column(Boolean, default=False)  # 是否人工修改过AI生成内容

    # 关联检查点
    checkpoint_id = Column(String(36), default="")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ContentVersion(Base):
    """内容版本历史表（精细到场景级）"""
    __tablename__ = "content_version"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 版本归属
    project_id = Column(String(36), index=True, nullable=False)
    episode_number = Column(Integer, nullable=False)
    scene_number = Column(Integer, default=0)  # 0表示整集版本

    # 版本标识
    version_code = Column(String(20), nullable=False)  # v001, v002...
    parent_version = Column(String(20), default="")  # 父版本

    # 编辑者信息
    editor_type = Column(String(20), default="human")  # human/ai/skill_writer/skill_reviewer
    editor_id = Column(String(36), default="")  # user_id 或 skill_name
    editor_name = Column(String(100), default="")

    # 内容存储
    content_path = Column(String(500), default="")  # 内容文件路径
    content_hash = Column(String(64), default="")  # SHA256哈希

    # 变更统计
    diff_stats = Column(Text, default="{}")  # JSON: {"added": 120, "deleted": 45}
    contribution_score = Column(Float, default=0)

    # 关联检查点
    checkpoint_id = Column(String(36), default="")
    change_note = Column(String(500), default="")  # 变更说明

    # 时间戳
    created_at = Column(DateTime, default=datetime.now)

    def get_diff_stats(self):
        try:
            return json.loads(self.diff_stats) if self.diff_stats else {}
        except:
            return {}

    def set_diff_stats(self, stats_dict):
        self.diff_stats = json.dumps(stats_dict, ensure_ascii=False)


class ContributionLedger(Base):
    """贡献度账本（聚合统计）"""
    __tablename__ = "contribution_ledger"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True, nullable=False)
    user_id = Column(String(36), index=True, nullable=False)
    user_name = Column(String(100), default="")

    # 基础统计
    episodes_touched = Column(Integer, default=0)  # 参与集数
    scenes_written = Column(Integer, default=0)    # 编写场景数
    total_edits = Column(Integer, default=0)       # 总编辑次数

    # 字数统计
    words_added = Column(Integer, default=0)
    words_deleted = Column(Integer, default=0)

    # AI协作统计
    ai_generations_accepted = Column(Integer, default=0)
    ai_generations_modified = Column(Integer, default=0)
    ai_generations_rejected = Column(Integer, default=0)

    # Skill调用统计
    skill_invocations = Column(Text, default="{}")  # JSON: {"writer": 10, "reviewer": 5}

    # 加权贡献分
    base_score = Column(Float, default=0)
    ai_collaboration_bonus = Column(Float, default=0)  # 有效协作奖励
    final_score = Column(Float, default=0)

    # 版本记录ID列表（JSON数组）
    version_ids = Column(Text, default="[]")

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def get_skill_invocations(self):
        try:
            return json.loads(self.skill_invocations) if self.skill_invocations else {}
        except:
            return {}

    def set_skill_invocations(self, invocations_dict):
        self.skill_invocations = json.dumps(invocations_dict, ensure_ascii=False)

    def get_version_ids(self):
        try:
            return json.loads(self.version_ids) if self.version_ids else []
        except:
            return []

    def add_version_id(self, version_id):
        ids = self.get_version_ids()
        ids.append(version_id)
        self.version_ids = json.dumps(ids, ensure_ascii=False)


class Checkpoint(Base):
    """工作断点表"""
    __tablename__ = "checkpoint"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True, nullable=False)

    # 断点标识
    checkpoint_code = Column(String(20), nullable=False)  # cp001, cp002...

    # 关联内容
    episode_number = Column(Integer, default=0)
    scene_number = Column(Integer, default=0)

    # 断点数据路径
    data_path = Column(String(500), default="")  # JSON文件路径

    # 断点说明
    note = Column(String(500), default="")
    tags = Column(Text, default="[]")  # JSON数组

    # 是否自动创建
    auto_created = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.now)
    created_by = Column(String(36), default="")

    def get_tags(self):
        try:
            return json.loads(self.tags) if self.tags else []
        except:
            return []

    def set_tags(self, tags_list):
        self.tags = json.dumps(tags_list, ensure_ascii=False)


class ModelProvider(Base):
    """模型提供商配置表（支持多模型灵活切换）"""
    __tablename__ = "model_provider"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 提供商信息
    name = Column(String(100), nullable=False, unique=True)  # 显示名称
    provider_type = Column(String(50), nullable=False)  # openai/claude/anthropic/custom

    # API配置
    base_url = Column(String(500), default="")
    api_key = Column(String(500), default="")  # 加密存储
    api_key_encrypted = Column(Boolean, default=False)

    # 默认模型
    default_model = Column(String(100), default="")

    # 支持模型列表（JSON数组）
    models = Column(Text, default="[]")

    # 状态
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)  # 是否为默认提供商

    # 速率限制
    rate_limit_rpm = Column(Integer, default=60)  # 每分钟请求数
    rate_limit_tpm = Column(Integer, default=60000)  # 每分钟token数
    input_cost_cny_per_1k = Column(Numeric(12, 6), default=0.002)
    output_cost_cny_per_1k = Column(Numeric(12, 6), default=0.008)
    billing_multiplier = Column(Numeric(8, 2), default=5)
    minimum_actual_cost_cny = Column(Numeric(12, 4), default=0.01)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def get_models(self):
        try:
            return json.loads(self.models) if self.models else []
        except:
            return []

    def set_models(self, models_list):
        self.models = json.dumps(models_list, ensure_ascii=False)


class GenerationJob(Base):
    """AI生成任务表（异步任务追踪）"""
    __tablename__ = "generation_job"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), index=True, nullable=False)

    # 任务类型
    job_type = Column(String(50), default="")  # scene_draft/episode_outline/...
    episode_number = Column(Integer, default=0)
    scene_number = Column(Integer, default=0)

    # 使用的模型
    provider_id = Column(String(36), default="")
    model_name = Column(String(100), default="")

    # 任务状态
    status = Column(String(20), default="pending")  # pending/running/completed/failed/cancelled
    progress = Column(Integer, default=0)  # 0-100

    # 输入输出
    prompt_path = Column(String(500), default="")  # 提示词文件路径
    result_path = Column(String(500), default="")  # 结果文件路径
    error_message = Column(Text, default="")
    gate_warning = Column(Text, default="")

    # 统计
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), default="")
