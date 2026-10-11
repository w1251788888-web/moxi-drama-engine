"""角色视觉档案 + 场景视觉档案

CharacterVisualBase：每个角色一份视觉身份基底，锁定后供分镜编译复用。
SceneVisualBase：每个场景的环境/光色基底，简化版（不做 lock 机制）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, Index

from app.database import Base


class CharacterVisualBase(Base):
    """角色视觉身份基底

    visual_text 存所有文字字段（face/hair/body/skin/default_outfit/...）
    reference_images / id_embedding_path / lora_weights_path 为二期预留
    """
    __tablename__ = "character_visual_bases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    character_id = Column(String(64), nullable=False, index=True)   # 关联到角色叙事档案
    character_name = Column(String(128), default="")

    # 一期主用：纯文本视觉描述（JSON：age_look/gender/face/hair/body/skin/default_outfit/signature_props/voice_tone/style_tags）
    visual_text = Column(Text, default="{}")

    # 服装变体：[{id, scene, desc}]
    outfit_variants = Column(Text, default="[]")

    # 角色级负面词
    negative_prompt = Column(Text, default="")

    # 二期预留字段
    reference_images = Column(Text, default="[]")        # JSON: [url, ...]
    id_embedding_path = Column(String(512), default="")  # PuLID/PhotoMaker 预计算 embedding 文件路径
    lora_weights_path = Column(String(512), default="")  # 主角专属轻量 LoRA 权重路径
    lora_trigger_word = Column(String(64), default="")
    lora_training_status = Column(String(16), default="not_trained")  # not_trained/training/done/failed

    # 锁定状态
    is_locked = Column(Boolean, default=False)
    locked_at = Column(DateTime, nullable=True)

    # RAG 文档ID（锁定时写入 character_{id} 数据集）
    rag_doc_id = Column(String(64), default="")

    # 版本（修改时递增，编译时记录快照）
    version = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_char_visual_project_char", "project_id", "character_id", unique=True),
    )

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "character_id": self.character_id,
            "character_name": self.character_name or "",
            "visual_text": json.loads(self.visual_text or "{}"),
            "outfit_variants": json.loads(self.outfit_variants or "[]"),
            "negative_prompt": self.negative_prompt or "",
            "reference_images": json.loads(self.reference_images or "[]"),
            "id_embedding_path": self.id_embedding_path or "",
            "lora_weights_path": self.lora_weights_path or "",
            "lora_trigger_word": self.lora_trigger_word or "",
            "lora_training_status": self.lora_training_status or "not_trained",
            "is_locked": bool(self.is_locked),
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "rag_doc_id": self.rag_doc_id or "",
            "version": self.version or 1,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SceneVisualBase(Base):
    """场景视觉基底（简化版，无 lock）"""
    __tablename__ = "scene_visual_bases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    scene_id = Column(String(64), nullable=False)
    episode = Column(Integer, default=0)
    scene_name = Column(String(128), default="")

    environment = Column(Text, default="")        # 雨夜写字楼电梯
    time_of_day = Column(String(32), default="")  # 夜/晨/午
    lighting = Column(Text, default="")           # 冷蓝霓虹 + 反光地面
    color_palette = Column(Text, default="")      # 冷色系 高对比
    props = Column(Text, default="")
    atmosphere = Column(Text, default="")         # 压抑、悬疑

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_scene_visual_project_scene", "project_id", "scene_id", unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "episode": self.episode,
            "scene_name": self.scene_name or "",
            "environment": self.environment or "",
            "time_of_day": self.time_of_day or "",
            "lighting": self.lighting or "",
            "color_palette": self.color_palette or "",
            "props": self.props or "",
            "atmosphere": self.atmosphere or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
