"""
项目学习沉淀模型 - 实现工作流自进化 (OpenSpace 启发)

核心机制：
1. 人工修改/建议自动捕获 → 项目素材库 (AUTO-CAPTURE)
2. 任务结束分析 → 提取规则到类目总规则 (AUTO-IMPROVE)
3. 持续优化 → 提升效率，节省token (AUTO-LEARN)
"""
import enum
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, JSON, ForeignKey, Index, Boolean
from app.database import Base


class MaterialStatus(str, enum.Enum):
    """素材状态枚举"""
    CANDIDATE = "candidate"      # 候选：待验证
    AUTO_RECORDED = "auto_recorded"  # 自动记录：系统观察数据
    APPROVED = "approved"        # 已批准：高质量素材
    REJECTED = "rejected"        # 已拒绝：低质量
    PROMOTED = "promoted"        # 已提升：已提升到全局


class MaterialType(str, enum.Enum):
    """素材类型枚举"""
    SUCCESSFUL_HOOK = "successful_hook"
    CONFLICT_PATTERN = "conflict_pattern"
    CHARACTER_ARC = "character_arc"
    EMOTIONAL_BEATS = "emotional_beats"
    USER_EDIT = "user_edit"
    FIX_PATTERN = "fix_pattern"
    OBSERVED_HOOK = "observed_hook"
    OBSERVED_VALIDATION = "observed_validation"
    OBSERVED_EXPLOSION = "observed_explosion"
    OBSERVED_RESOLUTION = "observed_resolution"
    USER_IMPROVED_HOOK = "user_improved_hook"
    USER_IMPROVED_VALIDATION = "user_improved_validation"
    USER_IMPROVED_EXPLOSION = "user_improved_explosion"
    USER_IMPROVED_RESOLUTION = "user_improved_resolution"


class ProjectMaterial(Base):
    """项目级素材库 - 沉淀项目特定成功经验"""
    __tablename__ = "project_materials"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True)
    session_id = Column(String(36), nullable=True, index=True)

    # 素材类型
    material_type = Column(String(32), nullable=False, index=True)
    # - successful_hook: 成功的钩子段落
    # - conflict_pattern: 冲突模式
    # - character_arc: 人物弧光案例
    # - emotional_beats: 情绪节拍设计
    # - user_edit: 用户优秀修改
    # - fix_pattern: 修复模式

    # 来源信息 (不使用外键约束，避免导入顺序问题)
    source_segment_id = Column(String(36), nullable=True, index=True)
    source_step = Column(String(32))  # concept/characters/beat_sheet/script_draft
    source_episode = Column(Integer)

    # 内容
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)  # 实际内容/修改内容
    context = Column(Text)  # 上下文信息

    # 质量评估
    quality_score = Column(Float, default=0.0)  # 质量分 0-1
    user_rating = Column(Integer, default=0)  # 用户评分 1-5
    ai_score = Column(Float, default=0.0)  # AI评估分

    # 效果追踪
    token_saved = Column(Integer, default=0)  # 节省的token数
    iterations_saved = Column(Integer, default=0)  # 节省的迭代次数
    usage_count = Column(Integer, default=0)  # 被使用次数

    # 标签
    tags = Column(JSON, default=list)  # 标签列表
    genre_tags = Column(JSON, default=list)  # 题材标签
    mood_tags = Column(JSON, default=list)  # 情绪标签

    # 状态
    status = Column(String(20), default=MaterialStatus.CANDIDATE.value)
    promoted_to_global = Column(Boolean, default=False)  # 是否已提升到全局

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_project_material_type", "project_id", "material_type"),
        Index("idx_material_quality", "quality_score", "usage_count"),
    )


class UserEditRecord(Base):
    """用户编辑记录 - 捕获人工修改"""
    __tablename__ = "user_edit_records"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True)
    session_id = Column(String(36), nullable=True)

    # 编辑对象
    target_type = Column(String(32), nullable=False)  # segment/step_version/scene
    target_id = Column(String(36), nullable=False)

    # 编辑内容
    before_content = Column(Text)  # 修改前
    after_content = Column(Text)  # 修改后
    edit_diff = Column(Text)  # 差异（unified diff格式）

    # 编辑意图
    edit_reason = Column(Text)  # 用户填写的修改原因
    edit_category = Column(String(32))  # 分类： pacing/emotion/dialogue/structure

    # 质量评估
    improvement_score = Column(Float, default=0.0)  # 改进程度评分
    is_significant = Column(Boolean, default=False)  # 是否是重大改进

    # 是否已沉淀
    materialized = Column(Boolean, default=False)
    material_id = Column(String(36), ForeignKey("project_materials.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_edit_project", "project_id", "created_at"),
        Index("idx_edit_target", "target_type", "target_id"),
    )


class RuleExtractionJob(Base):
    """规则提取任务 - 任务结束后自动执行"""
    __tablename__ = "rule_extraction_jobs"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True)

    # 任务状态
    status = Column(String(20), default="pending")  # pending/running/completed/failed

    # 输入数据
    total_materials = Column(Integer, default=0)
    selected_materials = Column(JSON, default=list)  # 入选的素材ID列表

    # 提取结果
    extracted_rules = Column(JSON, default=list)  # 提取的规则列表
    suggested_rule_content = Column(Text)  # 建议的规则内容
    confidence_score = Column(Float, default=0.0)  # 置信度

    # 应用状态
    applied_to_rule_id = Column(String(36), ForeignKey("rule.id"), nullable=True)
    apply_status = Column(String(20), default="pending")  # pending/approved/rejected

    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)


class WorkflowEfficiencyMetrics(Base):
    """工作流效率指标 - 追踪Token消耗和效率"""
    __tablename__ = "workflow_efficiency_metrics"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=False, index=True)

    # 时间维度
    date = Column(DateTime, nullable=False, index=True)  # 统计日期
    period = Column(String(20), default="daily")  # daily/weekly/monthly

    # Token消耗
    prompt_tokens_total = Column(Integer, default=0)
    completion_tokens_total = Column(Integer, default=0)
    tokens_per_segment = Column(Float, default=0.0)  # 平均每段消耗

    # 效率指标
    segments_generated = Column(Integer, default=0)
    auto_fix_triggered = Column(Integer, default=0)  # 触发修复次数
    auto_fix_success = Column(Integer, default=0)  # 修复成功次数
    manual_edits = Column(Integer, default=0)  # 人工修改次数

    # 节省统计（与基准对比）
    token_saved = Column(Integer, default=0)  # 相比基准节省的token
    time_saved_minutes = Column(Float, default=0.0)  # 节省的时间

    # 学习效果
    material_applied_count = Column(Integer, default=0)  # 应用素材次数
    rule_effectiveness = Column(Float, default=0.0)  # 规则有效性评分

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_efficiency_project_date", "project_id", "date"),
    )


class LearningInsight(Base):
    """学习洞察 - 系统发现的模式和洞察"""
    __tablename__ = "learning_insights"

    id = Column(String(36), primary_key=True)

    # 洞察类型
    insight_type = Column(String(32), nullable=False, index=True)
    # - pattern: 发现的模式
    # - warning: 警告信号
    # - suggestion: 改进建议
    # - efficiency: 效率洞察

    # 适用范围
    scope = Column(String(20), default="project")  # project/genre/global
    project_id = Column(String(36), nullable=True)
    genre_tags = Column(JSON, default=list)  # 适用的题材

    # 内容
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    evidence = Column(JSON, default=list)  # 支持证据

    # 统计
    occurrence_count = Column(Integer, default=0)  # 出现次数
    confidence = Column(Float, default=0.0)  # 置信度 0-1

    # 状态
    status = Column(String(20), default="active")  # active/resolved/ignored

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PromptOptimizationCache(Base):
    """提示词优化缓存 - 存储优化后的提示词"""
    __tablename__ = "prompt_optimization_cache"

    id = Column(String(36), primary_key=True)

    # 缓存键
    context_hash = Column(String(64), nullable=False, unique=True)  # 上下文哈希

    # 原始vs优化
    original_prompt = Column(Text, nullable=False)
    optimized_prompt = Column(Text, nullable=False)

    # 优化信息
    optimization_type = Column(String(32))  # material_injection/rule_compression/example_few_shot
    materials_injected = Column(JSON, default=list)  # 注入的素材ID
    rules_applied = Column(JSON, default=list)  # 应用的规则ID

    # 效果
    token_reduction = Column(Float, default=0.0)  # token减少比例
    quality_improvement = Column(Float, default=0.0)  # 质量提升

    # 使用统计
    hit_count = Column(Integer, default=0)
    last_hit_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=True)  # 过期时间
