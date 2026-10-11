"""分镜与提示词模型

设计要点：
- Shot：分镜单镜，spec_json 存完整 ShotSpec（结构化），candidates_json 存多候选池
- ShotPrompt：每个镜头按平台编译出的提示词缓存（避免重复调用 LLM）
- RenderProviderConfig：图片/视频/本地模型 服务商的 API Key 与 endpoint 配置（二期占位）
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, Index, ForeignKey

from app.database import Base


class Shot(Base):
    """分镜镜头"""
    __tablename__ = "shots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    episode = Column(Integer, nullable=False, index=True)
    scene_id = Column(String(64), default="")
    shot_order = Column(Integer, nullable=False, default=0)

    spec_json = Column(Text, default="{}")          # ShotSpec 完整序列化
    candidates_json = Column(Text, default="[]")    # 多候选池（仅关键镜头）
    selected_candidate_idx = Column(Integer, default=0)

    # 角色基底变更后标黄，提示用户手动重编译
    is_stale = Column(Boolean, default=False)

    # 生成时使用的 RAG 上下文摘要（便于追溯）
    rag_context_snapshot = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_shots_project_episode", "project_id", "episode"),
        Index("ix_shots_order", "project_id", "episode", "shot_order"),
    )

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "episode": self.episode,
            "scene_id": self.scene_id,
            "shot_order": self.shot_order,
            "spec": json.loads(self.spec_json or "{}"),
            "candidates": json.loads(self.candidates_json or "[]"),
            "selected_candidate_idx": self.selected_candidate_idx,
            "is_stale": bool(self.is_stale),
            "rag_context_snapshot": self.rag_context_snapshot or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ShotPrompt(Base):
    """单镜头按平台编译的提示词缓存"""
    __tablename__ = "shot_prompts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shot_id = Column(String(36), ForeignKey("shots.id"), nullable=False, index=True)
    platform = Column(String(32), nullable=False, index=True)  # jimeng/kling/hailuo/sora/generic

    prompt_text = Column(Text, default="")
    negative_prompt = Column(Text, default="")
    params_json = Column(Text, default="{}")       # 平台特定参数（duration/aspect_ratio/seed_policy）

    # 编译时引用的角色基底版本快照（变更检测用）
    base_version_snapshot = Column(Text, default="{}")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_shot_prompts_shot_platform", "shot_id", "platform", unique=True),
    )

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "shot_id": self.shot_id,
            "platform": self.platform,
            "prompt_text": self.prompt_text or "",
            "negative_prompt": self.negative_prompt or "",
            "params": json.loads(self.params_json or "{}"),
            "base_version_snapshot": json.loads(self.base_version_snapshot or "{}"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RenderProviderConfig(Base):
    """渲染服务商配置（二期占位：图片/视频/本地模型）

    一期只做配置存储 + 连通测试，不做真实渲染调用。
    """
    __tablename__ = "render_provider_configs"

    name = Column(String(32), primary_key=True)         # jimeng_image / kling_video / ...
    provider_kind = Column(String(16), default="image")  # image / video / local
    api_key = Column(Text, default="")                  # 加密留待二期，一期明文
    endpoint = Column(String(256), default="")
    enabled = Column(Boolean, default=False)
    extra_json = Column(Text, default="{}")             # 预留参数（region/model_version/...）
    last_test_at = Column(DateTime, nullable=True)
    last_test_ok = Column(Boolean, default=False)
    last_test_msg = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, *, redact_key: bool = True) -> dict:
        import json
        key_display = ""
        if self.api_key:
            key_display = "****" + self.api_key[-4:] if redact_key and len(self.api_key) > 4 else self.api_key
        return {
            "name": self.name,
            "provider_kind": self.provider_kind,
            "api_key": key_display,
            "endpoint": self.endpoint or "",
            "enabled": bool(self.enabled),
            "extra": json.loads(self.extra_json or "{}"),
            "last_test_at": self.last_test_at.isoformat() if self.last_test_at else None,
            "last_test_ok": bool(self.last_test_ok),
            "last_test_msg": self.last_test_msg or "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
