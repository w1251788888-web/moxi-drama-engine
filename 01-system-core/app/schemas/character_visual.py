"""角色视觉档案 + 场景视觉档案 Schema"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────
# CharacterVisualBase
# ─────────────────────────────────────────────────────────


class CharacterVisualText(BaseModel):
    """角色视觉文本字段（结构化，编译器按字段拼装）"""
    age_look: str = ""             # 25-28 岁
    gender: str = ""               # 女/男
    face: str = ""                 # 鹅蛋脸，眉骨清晰，杏眼上扬...
    hair: str = ""                 # 黑色长直发及腰，齐刘海
    body: str = ""                 # 身高 168，瘦削
    skin: str = ""                 # 冷白皮
    default_outfit: str = ""       # 白色高领毛衣 + 米色风衣
    signature_props: str = ""      # 金属细框眼镜
    voice_tone: str = ""           # 偏低，平稳
    style_tags: str = ""           # 都市写实，冷色调


class OutfitVariant(BaseModel):
    id: str
    scene: str = ""        # 职场/居家/晚宴
    desc: str = ""


class CharacterVisualUpsert(BaseModel):
    """前端提交的视觉档案（创建/更新）"""
    character_id: str
    character_name: str = ""
    visual_text: CharacterVisualText = Field(default_factory=CharacterVisualText)
    outfit_variants: list[OutfitVariant] = Field(default_factory=list)
    negative_prompt: str = ""
    reference_images: list[str] = Field(default_factory=list)


class CharacterVisualGenerateRequest(BaseModel):
    """AI 一键生成视觉档案"""
    project_id: str
    character_id: str


class CharacterVisualLockRequest(BaseModel):
    confirm: bool = True


# ─────────────────────────────────────────────────────────
# SceneVisualBase
# ─────────────────────────────────────────────────────────


class SceneVisualUpsert(BaseModel):
    project_id: str
    scene_id: str
    episode: int = 0
    scene_name: str = ""
    environment: str = ""
    time_of_day: str = ""
    lighting: str = ""
    color_palette: str = ""
    props: str = ""
    atmosphere: str = ""


class SceneVisualGenerateRequest(BaseModel):
    project_id: str
    episode: int


# ─────────────────────────────────────────────────────────
# 渲染服务商配置（二期占位）
# ─────────────────────────────────────────────────────────


class RenderProviderUpsert(BaseModel):
    name: str                      # jimeng_image / kling_video / sora_video / ...
    provider_kind: str = "image"   # image / video / local
    api_key: str = ""
    endpoint: str = ""
    enabled: bool = False
    extra: dict = Field(default_factory=dict)


class RenderProviderTestResponse(BaseModel):
    ok: bool
    msg: str = ""
    latency_ms: int = 0
