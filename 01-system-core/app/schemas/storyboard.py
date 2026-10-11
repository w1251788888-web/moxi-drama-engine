"""分镜与提示词 Pydantic Schema

ShotSpec：单镜的结构化规格（参考 VideoDirectorGPT / DirectorLLM / StoryMem 输入格式合并）
PromptPack：编译后输出
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────
# ShotSpec
# ─────────────────────────────────────────────────────────


BeatRole = Literal["establish", "setup", "conflict", "reaction", "reveal", "transition", "payoff"]
ShotSize = Literal["ELS", "LS", "MS", "MCU", "CU", "ECU"]   # 远/全/中/中近/特写/大特写
CameraAngle = Literal["eye", "high", "low", "over_shoulder", "top", "dutch"]
CameraMovement = Literal[
    "static", "push_in", "pull_out", "pan_left", "pan_right",
    "tilt_up", "tilt_down", "tracking", "handheld", "crane", "zoom_in", "zoom_out"
]


class ShotCamera(BaseModel):
    shot_size: ShotSize = "MS"
    angle: CameraAngle = "eye"
    movement: CameraMovement = "static"
    lens_mm: Optional[int] = None        # DirectorLLM 启发：35/50/85
    notes: str = ""                      # 自由文本补充


class ShotEntityAction(BaseModel):
    """每个出场角色的动作/表情"""
    character_id: str
    outfit_variant_id: Optional[str] = None  # 指向 CharacterVisualBase.outfit_variants[i].id
    action: str = ""
    expression: str = ""


class ShotDelta(BaseModel):
    """本镜独有的微调描述（不重复角色/场景基底信息）"""
    framing: str = ""           # 镜中倒影 / 三分构图 / 对称
    lighting_delta: str = ""    # 手机冷光打脸 / 逆光剪影
    mood: str = ""              # 压抑 / 紧张 / 暧昧
    extra: str = ""             # 杂项自由文本


class ShotAudioHint(BaseModel):
    sfx: str = ""        # 雨滴/呼吸声/电梯提示音
    bgm_mood: str = ""   # 紧张 pad / 低频心跳
    voice_mood: str = "" # 低声/急促/平稳


class ShotSpec(BaseModel):
    """分镜单镜规格"""
    shot_id: str
    scene_id: str = ""
    order: int = 0
    duration_sec: float = Field(default=3.0, ge=0.5, le=15.0)
    beat_role: BeatRole = "setup"

    # 出场角色（必填，编译器按 ID 拉基底）
    entities: list[ShotEntityAction] = Field(default_factory=list)

    # 场景引用（指向 SceneVisualBase.scene_id；空字符串表示自由场景）
    scene_ref: str = ""

    # 镜头语言
    camera: ShotCamera = Field(default_factory=ShotCamera)

    # 镜头独有信息
    shot_delta: ShotDelta = Field(default_factory=ShotDelta)

    # 台词提示
    dialogue: str = ""

    # 音频提示
    audio: ShotAudioHint = Field(default_factory=ShotAudioHint)

    # StoryMem / ConsistI2V 风格的前镜锚定（二期渲染用）
    anchor_frame_ref: str = ""

    # 评分（多候选时用）
    score: Optional[float] = None
    score_reason: str = ""


# ─────────────────────────────────────────────────────────
# 路由请求/响应
# ─────────────────────────────────────────────────────────


class StoryboardPlanRequest(BaseModel):
    project_id: str
    episode: int
    session_id: Optional[str] = None     # 缺省时使用 project_id
    target_shot_count: int = Field(default=14, ge=4, le=40)
    enable_multi_candidate: bool = True   # 关键镜头多候选


class StoryboardPlanResponse(BaseModel):
    ok: bool = True
    project_id: str
    episode: int
    shots: list[dict]    # 每个镜头的 to_dict()
    rag_used: bool = False
    elapsed_ms: int = 0
    msg: str = ""


class CompileRequest(BaseModel):
    shot_id: str
    platforms: list[str] = Field(default_factory=lambda: ["jimeng", "kling", "hailuo", "sora", "generic"])


class CompileBatchRequest(BaseModel):
    project_id: str
    episode: int
    platforms: list[str] = Field(default_factory=lambda: ["jimeng", "kling", "hailuo", "sora", "generic"])


class PromptPack(BaseModel):
    platform: str
    prompt_text: str
    negative_prompt: str = ""
    params: dict = Field(default_factory=dict)


class CompileResponse(BaseModel):
    ok: bool = True
    shot_id: str
    packs: list[PromptPack]
    msg: str = ""


class EligibilityResponse(BaseModel):
    eligible: bool
    reason: str = ""           # no_script / not_confirmed / stale / no_locked_characters / ok
    detail: str = ""
    confirmed_version: str = ""
    missing_locked_characters: list[str] = Field(default_factory=list)


class RegenerateShotRequest(BaseModel):
    shot_id: str
    pick_candidate_idx: Optional[int] = None  # 不传则重新生成
