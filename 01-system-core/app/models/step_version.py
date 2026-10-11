"""步骤版本管理模型

实现版本树机制：每个步骤支持多版本并存、对比、合并、回退
基于gstack的Git-like版本管理思想
"""
from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.database import Base


class StepVersion(Base):
    """步骤版本节点

    每个步骤的每次生成/修改都创建一个版本节点，形成版本树结构。
    支持线性升级和分叉（Fork）两种模式。
    """
    __tablename__ = "step_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("task.id"), nullable=False, index=True)
    step_id = Column(String(32), nullable=False, index=True)  # concept, characters, etc.

    # 版本号：v1.0, v1.1, v2.0, etc.
    version_number = Column(String(16), nullable=False)

    # 父版本ID（分叉用）
    parent_version_id = Column(String(36), ForeignKey("step_versions.id"), nullable=True)

    # 内容指纹（检测变更）
    content_hash = Column(String(64), nullable=False)

    # 实际内容（JSON存储）
    context_output = Column(Text, default="")
    full_output = Column(Text, default="")

    # 变更类型：ai_generated / manual_edit / merged / forked
    change_type = Column(String(16), nullable=False, default="ai_generated")

    # 变更描述
    change_log = Column(Text, default="")

    # 生成此版本使用的提示词和输入摘要
    prompt_file = Column(String(128), default="")
    input_summary = Column(Text, default="")

    # 是否当前激活版本
    is_current = Column(Integer, default=0)  # 0=false, 1=true

    # 剧本"确认保存"机制（用于触发分镜生成 + RAG 写入）
    is_confirmed = Column(Integer, default=0)              # 0=draft, 1=confirmed
    confirmed_at = Column(DateTime, nullable=True)
    rag_doc_ids = Column(Text, default="{}")               # JSON: {summary, scene_cards[], beats[]}

    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(16), default="ai")  # user / ai / system

    # 关联关系
    session = relationship("Task", foreign_keys=[session_id])
    parent = relationship("StepVersion", remote_side=[id], backref="children")

    __table_args__ = (
        Index("ix_step_versions_session_step", "session_id", "step_id"),
        Index("ix_step_versions_current", "session_id", "step_id", "is_current"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "version_number": self.version_number,
            "parent_version_id": self.parent_version_id,
            "content_hash": self.content_hash,
            "context_output": self.context_output,
            "full_output": self.full_output,
            "change_type": self.change_type,
            "change_log": self.change_log,
            "prompt_file": self.prompt_file,
            "input_summary": self.input_summary,
            "is_current": bool(self.is_current),
            "is_confirmed": bool(self.is_confirmed),
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "rag_doc_ids": json.loads(self.rag_doc_ids or "{}"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
        }

    @staticmethod
    def compute_content_hash(context: str, full: str) -> str:
        """计算内容指纹"""
        content = f"{context or ''}::{full or ''}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class StepDependency(Base):
    """步骤间依赖关系

    记录步骤间的依赖关系，支持跨步骤回流检测。
    当上游步骤变更时，自动标记下游需要同步。
    """
    __tablename__ = "step_dependencies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("task.id"), nullable=False, index=True)

    # 上游步骤
    upstream_step = Column(String(32), nullable=False)
    upstream_version_id = Column(String(36), ForeignKey("step_versions.id"), nullable=False)

    # 下游步骤
    downstream_step = Column(String(32), nullable=False)
    downstream_version_id = Column(String(36), ForeignKey("step_versions.id"), nullable=False)

    # 依赖类型：hard（必须同步）/ soft（建议同步）
    dependency_type = Column(String(8), default="hard")

    # 同步状态：synced / pending / conflict
    sync_status = Column(String(16), default="synced")

    # 同步建议说明
    sync_suggestion = Column(Text, default="")

    # 受影响的内容范围（JSON数组）
    affected_scope = Column(Text, default="[]")  # e.g., ["episode_3", "episode_5"]

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联关系
    session = relationship("Task", foreign_keys=[session_id])
    upstream_version = relationship("StepVersion", foreign_keys=[upstream_version_id])
    downstream_version = relationship("StepVersion", foreign_keys=[downstream_version_id])

    __table_args__ = (
        Index("ix_step_deps_session", "session_id"),
        Index("ix_step_deps_upstream", "upstream_step", "upstream_version_id"),
        Index("ix_step_deps_downstream", "downstream_step", "downstream_version_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "upstream_step": self.upstream_step,
            "upstream_version_id": self.upstream_version_id,
            "downstream_step": self.downstream_step,
            "downstream_version_id": self.downstream_version_id,
            "dependency_type": self.dependency_type,
            "sync_status": self.sync_status,
            "sync_suggestion": self.sync_suggestion,
            "affected_scope": json.loads(self.affected_scope or "[]"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DynamicRule(Base):
    """动态规则注入

    支持四层规则体系：
    1. global - 全局规则（所有项目共享）
    2. project - 项目规则（当前会话）
    3. step - 步骤规则（仅当前步骤）
    4. once - 单次规则（仅下一次生成）
    """
    __tablename__ = "dynamic_rules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("task.id"), nullable=True, index=True)

    # 规则内容
    content = Column(Text, nullable=False)

    # 规则层级：global / project / step / once
    scope = Column(String(16), nullable=False, default="step")

    # 目标步骤（scope=step时必填）
    target_step = Column(String(32), nullable=True)

    # 目标集数（可选）
    target_episode = Column(Integer, nullable=True)

    # 生效方式：immediate / next_generation
    apply_timing = Column(String(16), default="next_generation")

    # 已应用的版本列表（防止重复应用）
    applied_version_ids = Column(Text, default="[]")

    # 是否激活
    is_active = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(16), default="user")  # user / ai / system

    # 关联关系
    session = relationship("Task", foreign_keys=[session_id])

    __table_args__ = (
        Index("ix_dynamic_rules_session", "session_id"),
        Index("ix_dynamic_rules_scope", "scope", "target_step"),
        Index("ix_dynamic_rules_active", "session_id", "is_active"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "content": self.content,
            "scope": self.scope,
            "target_step": self.target_step,
            "target_episode": self.target_episode,
            "apply_timing": self.apply_timing,
            "applied_version_ids": json.loads(self.applied_version_ids or "[]"),
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
        }

    def mark_applied(self, version_id: str):
        """标记规则已应用到某个版本"""
        applied = json.loads(self.applied_version_ids or "[]")
        if version_id not in applied:
            applied.append(version_id)
            self.applied_version_ids = json.dumps(applied)


class StepReview(Base):
    """步骤评审记录

    实现生成→评审→修正→再生成的循环。
    每个版本可以有多个评审记录。
    """
    __tablename__ = "step_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version_id = Column(String(36), ForeignKey("step_versions.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("task.id"), nullable=False, index=True)

    # 评审类型：auto（AI自动评审）/ manual（人工评审）
    review_type = Column(String(16), default="auto")

    # 评审结果：pass / needs_fix / reject
    verdict = Column(String(16), nullable=False)

    # 评分（可选）
    score = Column(Integer, nullable=True)

    # 评审意见
    comments = Column(Text, default="")

    # 具体问题列表（JSON）
    issues = Column(Text, default="[]")
    # e.g., [{"field": "character_name", "issue": "缺少口头禅", "suggestion": "补充口头禅"}]

    # 建议的重写提示
    rewrite_hint = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_by = Column(String(16), default="ai")

    # 关联关系
    version = relationship("StepVersion", foreign_keys=[version_id])
    session = relationship("Task", foreign_keys=[session_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version_id": self.version_id,
            "session_id": self.session_id,
            "review_type": self.review_type,
            "verdict": self.verdict,
            "score": self.score,
            "comments": self.comments,
            "issues": json.loads(self.issues or "[]"),
            "rewrite_hint": self.rewrite_hint,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_by": self.reviewed_by,
        }
