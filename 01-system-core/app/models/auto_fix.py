"""
AUTO-FIX 自动修复系统 — OpenSpace 启发
"""
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, JSON, ForeignKey, Index
from app.database import Base


class FailurePattern(Base):
    """失败模式定义库"""
    __tablename__ = "failure_patterns"

    id = Column(String(36), primary_key=True)
    pattern_code = Column(String(32), nullable=False, unique=True)  # 如：WORD_COUNT_INSUFFICIENT
    pattern_name = Column(String(64), nullable=False)  # 如：字数不足
    description = Column(Text)  # 模式描述
    detection_logic = Column(Text)  # 检测逻辑（JSON 序列化）

    # 修复策略
    fix_strategy_code = Column(String(32), nullable=False)  # 关联修复策略
    default_priority = Column(Integer, default=5)  # 1-10，越高越优先

    # 统计
    total_triggered = Column(Integer, default=0)
    total_fixed = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)  # 修复成功率

    # 元数据
    project_type = Column(String(32), default="all")  # 适用项目类型
    segment_type = Column(String(16), default="all")  # 适用段落类型
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class FixStrategy(Base):
    """修复策略库"""
    __tablename__ = "fix_strategies"

    id = Column(String(36), primary_key=True)
    strategy_code = Column(String(32), nullable=False, unique=True)
    strategy_name = Column(String(64), nullable=False)
    description = Column(Text)

    # 策略参数模板
    param_template = Column(JSON, default=dict)  # 如：{"expand_ratio": 1.3, "focus": "description"}

    # 提示词模板
    system_prompt = Column(Text)  # 系统提示词
    user_prompt_template = Column(Text)  # 用户提示词模板

    # 统计
    total_applied = Column(Integer, default=0)
    total_success = Column(Integer, default=0)
    avg_iterations = Column(Float, default=0.0)  # 平均需要几次迭代
    success_rate = Column(Float, default=0.0)

    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)


class AutoFixRecord(Base):
    """自动修复执行记录"""
    __tablename__ = "auto_fix_records"

    id = Column(String(36), primary_key=True)

    # 关联信息
    segment_id = Column(String(36), ForeignKey("episode_segments.id"), nullable=False)
    step_version_id = Column(String(36), ForeignKey("step_versions.id"))
    pattern_id = Column(String(36), ForeignKey("failure_patterns.id"))
    strategy_id = Column(String(36), ForeignKey("fix_strategies.id"))

    # 执行详情
    failure_type = Column(String(32), nullable=False)  # 失败类型代码
    failure_detail = Column(Text)  # 失败详情（验证结果）
    before_content = Column(Text)  # 修复前内容
    after_content = Column(Text)  # 修复后内容
    fix_params = Column(JSON, default=dict)  # 实际使用的参数

    # 结果
    status = Column(String(16), default="pending")  # pending/success/failed/aborted
    iterations = Column(Integer, default=0)  # 迭代次数
    final_score = Column(Float, default=0.0)  # 最终验证分数

    # 反馈
    user_rating = Column(Integer, nullable=True)  # 用户评分 1-5
    user_feedback = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    # 索引
    __table_args__ = (
        Index("idx_fix_segment", "segment_id"),
        Index("idx_fix_pattern", "pattern_id"),
        Index("idx_fix_status", "status"),
    )


class SuccessPattern(Base):
    """成功模式库 — 从高质量修复中提取"""
    __tablename__ = "success_patterns"

    id = Column(String(36), primary_key=True)

    # 来源
    source_segment_id = Column(String(36), ForeignKey("episode_segments.id"))
    source_project_type = Column(String(32))

    # 模式特征
    segment_type = Column(String(16))  # hook/validation/explosion/resolution
    pattern_features = Column(JSON)  # 结构特征：{"avg_sentence_length": 25, "opening_type": "conflict"}

    # 内容模板（匿名化）
    template_structure = Column(Text)  # 结构模板
    key_elements = Column(JSON)  # 关键元素列表

    # 使用统计
    usage_count = Column(Integer, default=0)
    avg_score = Column(Float, default=0.0)

    # 质量标记
    is_curated = Column(Integer, default=0)  # 是否人工精选
    rating = Column(Float, default=0.0)  # 综合评分

    created_at = Column(DateTime, default=datetime.now)


class SegmentMetrics(Base):
    """段落性能指标 — 数据驱动优化"""
    __tablename__ = "segment_metrics"

    id = Column(String(36), primary_key=True)
    segment_id = Column(String(36), ForeignKey("episode_segments.id"), unique=True)

    # 生成指标
    total_generations = Column(Integer, default=0)
    total_refactors = Column(Integer, default=0)
    avg_generation_time = Column(Float, default=0.0)  # 秒
    avg_refactor_time = Column(Float, default=0.0)

    # 质量指标
    avg_validation_score = Column(Float, default=0.0)
    pass_rate = Column(Float, default=0.0)  # 一次通过率
    auto_fix_rate = Column(Float, default=0.0)  # 需要自动修复的比例

    # 失败模式分布
    failure_distribution = Column(JSON, default=dict)  # {"WORD_COUNT": 5, "MISSING_CONFLICT": 2}

    # 时间维度
    first_generation_at = Column(DateTime)
    last_generation_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 索引优化（复合索引支持常见查询场景）
    __table_args__ = (
        Index("idx_metrics_segment", "segment_id"),
        Index("idx_metrics_scores", "avg_validation_score", "pass_rate"),
        Index("idx_metrics_updated", "updated_at"),
    )
