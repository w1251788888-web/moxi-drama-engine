"""
规则质量控制模型 - 防止规则污染

核心机制：
1. 分层规则体系（项目级/类目级/全局级）
2. 规则效果追踪（A/B测试风格）
3. 自动降级机制（效果差的规则自动下线）
4. 人工审核关卡（关键层级必须人工确认）
"""
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, JSON, ForeignKey, Index
from app.database import Base
import enum


class RuleLevel(str, enum.Enum):
    """规则层级"""
    PROJECT = "project"      # 项目级：仅当前项目有效
    GENRE = "genre"          # 类目级：同题材项目共享
    GLOBAL = "global"        # 全局级：所有项目生效


class RuleStatus(str, enum.Enum):
    """规则状态"""
    CANDIDATE = "candidate"      # 候选：待验证
    EXPERIMENT = "experiment"    # 实验：A/B测试中
    APPROVED = "approved"        # 已批准：正式生效
    DEGRADED = "degraded"        # 已降级：效果差，暂停使用
    ARCHIVED = "archived"        # 已归档：废弃


class RuleEffectivenessRecord(Base):
    """规则效果追踪记录 - A/B测试风格"""
    __tablename__ = "rule_effectiveness_records"

    id = Column(String(36), primary_key=True)
    rule_id = Column(String(36), ForeignKey("rule.id"), nullable=False, index=True)

    # 测试分组
    experiment_group = Column(String(20), default="control")  # control/treatment

    # 应用场景
    project_id = Column(String(36), ForeignKey("task.id"), nullable=True)
    genre_tags = Column(JSON, default=list)
    segment_type = Column(String(16))  # hook/validation/explosion/resolution

    # 效果指标
    applications_count = Column(Integer, default=0)  # 应用次数
    success_count = Column(Integer, default=0)       # 成功次数（验证通过）
    failure_count = Column(Integer, default=0)       # 失败次数

    # 质量指标
    avg_validation_score = Column(Float, default=0.0)  # 平均验证分数
    avg_generation_time = Column(Float, default=0.0)   # 平均生成时间
    token_efficiency = Column(Float, default=0.0)      # token效率（越高越好）

    # 用户反馈
    user_override_count = Column(Integer, default=0)   # 用户覆盖次数（说明规则有问题）
    user_rating_avg = Column(Float, default=0.0)       # 用户评分

    # 统计时间窗口
    date = Column(DateTime, nullable=False, index=True)
    period = Column(String(20), default="daily")  # daily/weekly/monthly

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_effectiveness_rule_date", "rule_id", "date"),
        Index("idx_effectiveness_experiment", "rule_id", "experiment_group"),
    )


class RulePromotionPath(Base):
    """规则晋升路径 - 记录规则从项目级到全局级的晋升历程"""
    __tablename__ = "rule_promotion_paths"

    id = Column(String(36), primary_key=True)
    rule_id = Column(String(36), ForeignKey("rule.id"), nullable=False, index=True)

    # 当前层级
    current_level = Column(String(20), default=RuleLevel.PROJECT)
    target_level = Column(String(20), nullable=False)

    # 晋升条件检查
    project_usage_count = Column(Integer, default=0)      # 项目使用次数
    cross_project_validation = Column(Integer, default=0)  # 跨项目验证次数
    avg_effectiveness_score = Column(Float, default=0.0)   # 平均效果分

    # 晋升要求（动态计算）
    requirements = Column(JSON, default=dict)  # {"min_usage": 10, "min_success_rate": 0.8}

    # 状态
    status = Column(String(20), default="pending")  # pending/ready/promoted/rejected
    promoted_at = Column(DateTime, nullable=True)
    promoted_by = Column(String(36), nullable=True)  # 谁批准的晋升

    # 拒绝原因
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class RuleConflictDetection(Base):
    """规则冲突检测 - 检测新规则是否与现有规则冲突"""
    __tablename__ = "rule_conflict_detections"

    id = Column(String(36), primary_key=True)
    new_rule_id = Column(String(36), ForeignKey("rule.id"), nullable=False)
    existing_rule_id = Column(String(36), ForeignKey("rule.id"), nullable=False)

    # 冲突类型
    conflict_type = Column(String(32))  # contradiction/duplicate/overlap

    # 冲突描述
    conflict_description = Column(Text)
    conflicting_keywords = Column(JSON, default=list)
    severity = Column(String(20), default="medium")  # low/medium/high/critical

    # 处理状态
    status = Column(String(20), default="pending")  # pending/resolved/ignored
    resolution = Column(String(20), nullable=True)  # merge/replace/exclude
    resolved_by = Column(String(36), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_conflict_new", "new_rule_id"),
        Index("idx_conflict_existing", "existing_rule_id"),
    )


class GenreRulePool(Base):
    """类目规则池 - 同题材项目共享的规则库"""
    __tablename__ = "genre_rule_pools"

    id = Column(String(36), primary_key=True)

    # 类目定义
    genre_main = Column(String(50), nullable=False, index=True)   # 男频逆袭
    genre_sub = Column(String(50), nullable=False, index=True)    # 校园系统装X

    # 关联规则
    rule_id = Column(String(36), ForeignKey("rule.id"), nullable=False)

    # 该类目下的效果
    genre_effectiveness_score = Column(Float, default=0.0)
    genre_usage_count = Column(Integer, default=0)
    genre_success_rate = Column(Float, default=0.0)

    # 贡献项目（哪些项目贡献了这条规则）
    contributing_projects = Column(JSON, default=list)

    # 状态
    status = Column(String(20), default="active")  # active/suspended

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_genre_pool", "genre_main", "genre_sub", "rule_id"),
    )


class RuleGuardrail(Base):
    """规则护栏 - 防止规则污染的全局配置"""
    __tablename__ = "rule_guardrails"

    id = Column(String(36), primary_key=True)

    # 晋升门槛配置
    project_to_genre_min_usage = Column(Integer, default=5)          # 项目级晋升类目级：最少使用次数
    project_to_genre_min_success_rate = Column(Float, default=0.75)  # 项目级晋升类目级：最低成功率
    project_to_genre_min_confidence = Column(Float, default=0.8)     # 项目级晋升类目级：最低置信度

    genre_to_global_min_usage = Column(Integer, default=20)          # 类目级晋升全局级
    genre_to_global_min_success_rate = Column(Float, default=0.8)
    genre_to_global_min_projects = Column(Integer, default=3)        # 至少3个项目验证

    # 降级触发条件
    degrade_threshold_success_rate = Column(Float, default=0.5)      # 成功率低于50%触发降级
    degrade_threshold_overrides = Column(Integer, default=5)         # 用户覆盖5次以上触发降级
    degrade_min_samples = Column(Integer, default=10)                # 至少10个样本才触发

    # 冲突检测配置
    conflict_detection_enabled = Column(Integer, default=1)
    conflict_severity_threshold = Column(String(20), default="medium")

    # 人工审核配置
    require_approval_for_genre = Column(Integer, default=1)          # 晋升类目级需要人工审核
    require_approval_for_global = Column(Integer, default=1)         # 晋升全局级需要人工审核

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    updated_by = Column(String(36), nullable=True)
