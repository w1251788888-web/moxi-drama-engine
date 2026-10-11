"""高级生成模式的创作形态配置骨架。"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.services.short_drama_advanced_generation_profiles import (
    ADVANCED_GENERATION_PROFILES,
    PROFILE_RULE_FILES,
    PROFILE_SYSTEM_PROMPTS,
)

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


logger = logging.getLogger(__name__)

MODE_ID = "advanced_generation"
MODE_LABEL = "高级生成模式"

LOGIC_STEPS = {
    "director_blueprint",
    "project_init_check",
    "market_check",
    "concept",
    "episode_outlines",
}
CREATIVE_STEPS = {
    "characters",
    "beat_sheet",
    "scene_list",
    "script_draft",
    "storyboard",
}
REVIEW_STEPS = {
    "quality_check",
    "narrative_consistency",
    "compliance_check",
}

ROLE_LABELS = {
    "logic": "逻辑规划",
    "creative": "创作执行",
    "review": "质量评审",
}

ROLE_DEFAULT_TEMPERATURE = {
    "logic": 0.25,
    "creative": 0.85,
    "review": 0.0,
}


@dataclass(frozen=True)
class StepGenerationRoute:
    """高级生成模式下，单个步骤实际使用的模型路由。"""

    enabled: bool
    step_id: str
    role: str
    role_label: str
    generation_kwargs: dict[str, str]
    temperature: float | None
    reason: str


def list_advanced_generation_profiles() -> list[dict[str, Any]]:
    """返回所有高级生成模式的创作形态。"""
    return deepcopy(ADVANCED_GENERATION_PROFILES)


def get_advanced_generation_profile(profile_id: str) -> dict[str, Any]:
    """按 id 返回单个创作形态；找不到时抛 ValueError。"""
    normalized_id = str(profile_id or "").strip()
    for profile in ADVANCED_GENERATION_PROFILES:
        if profile["id"] == normalized_id:
            return deepcopy(profile)
    raise ValueError(f"未知高级生成模式: {normalized_id}")


def match_advanced_generation_profile(project_type: str) -> dict[str, Any]:
    """根据项目类型文字匹配创作形态；匹配不到时回到短剧。"""
    text = str(project_type or "").strip()
    if not text:
        return get_advanced_generation_profile("short_drama")
    for profile in ADVANCED_GENERATION_PROFILES:
        aliases = [str(item) for item in profile.get("project_type_aliases") or []]
        if any(alias and alias in text for alias in aliases):
            return deepcopy(profile)
    return get_advanced_generation_profile("short_drama")


def rules_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "02-creation-rules" / "core-rules"


def _profile_from_id_or_project_type(profile_id: str = "", project_type: str = "") -> dict[str, Any]:
    if str(profile_id or "").strip():
        return get_advanced_generation_profile(str(profile_id).strip())
    return match_advanced_generation_profile(project_type)


def generation_system_prompt_for_profile(profile_id: str) -> str:
    """返回某种创作形态的通用生成系统提示。"""
    profile = _profile_from_id_or_project_type(profile_id)
    return PROFILE_SYSTEM_PROMPTS.get(str(profile.get("id") or ""), PROFILE_SYSTEM_PROMPTS["short_drama"])


def _load_profile_rule(profile_id: str) -> str:
    file_name = PROFILE_RULE_FILES.get(profile_id, "")
    if not file_name:
        return ""
    try:
        path = rules_dir() / file_name
        return path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        logger.warning("profile rule file unavailable: profile_id=%s file=%s error=%s", profile_id, file_name, exc)
        return ""


def build_profile_generation_prompt(
    project: dict[str, Any],
    *,
    job_type: str,
    episode_number: int = 1,
    scene_number: int | None = None,
) -> str:
    """按创作形态构建项目级通用生成提示。"""
    config = project.get("config") if isinstance(project.get("config"), dict) else {}
    profile = _profile_from_id_or_project_type(
        str(config.get("advanced_generation_profile_id") or ""),
        str(project.get("project_type") or ""),
    )
    profile_id = str(profile.get("id") or "short_drama")
    rule_text = _load_profile_rule(profile_id)

    parts = [
        f"# 项目：{project.get('name') or '未命名项目'}",
        f"创作形态：{profile.get('label') or '短剧'}",
        f"类型：{project.get('project_type') or ''}",
        f"受众：{project.get('audience_axis') or ''}",
        f"题材：{project.get('genre_main') or ''} / {project.get('genre_sub') or ''}",
    ]
    description = str(project.get("description") or "").strip()
    if description:
        parts.append(f"## 项目描述\n{description}")
    if rule_text:
        parts.append(f"## {profile.get('label')}创作规则\n{rule_text[:3600]}")

    if profile_id == "stage_play":
        scene_label = f"第{scene_number}场" if scene_number else "当前场次"
        parts.append(f"## 任务\n请生成话剧{scene_label}内容，包含场景说明、人物调度、对白和舞台动作。")
    elif profile_id == "film":
        scene_label = f"第{scene_number}场" if scene_number else "当前场景"
        parts.append(f"## 任务\n请生成影视剧{scene_label}内容，包含场景标题、动作描写、对白和可拍摄提示。")
    elif profile_id == "long_series":
        parts.append(f"## 任务\n请生成长剧/系列剧第{episode_number}集内容，兼顾人物弧光、伏笔和连续性。")
    else:
        parts.append(f"## 任务\n请创作第{episode_number}集")
        if scene_number:
            parts.append(f"第{scene_number}场")

    parts.append(f"任务类型：{job_type}")
    return "\n\n".join(part for part in parts if str(part).strip())


def _project_config(metadata: dict[str, Any]) -> dict[str, Any]:
    project = metadata.get("project") if isinstance(metadata, dict) else {}
    if not isinstance(project, dict):
        return {}
    config = project.get("config") if isinstance(project.get("config"), dict) else {}
    merged = dict(project)
    merged.update(config)
    return merged


def advanced_generation_enabled(metadata: dict[str, Any]) -> bool:
    """判断当前项目是否开启高级生成模式。"""
    config = _project_config(metadata)
    if str(config.get("generation_mode") or "").strip() == MODE_ID:
        return True
    return bool(config.get("advanced_generation_mode"))


def step_role(step_id: str) -> str:
    """把写作步骤映射到高级生成模式角色。"""
    normalized = str(step_id or "").strip()
    if normalized in REVIEW_STEPS:
        return "review"
    if normalized in CREATIVE_STEPS:
        return "creative"
    return "logic"


def _clean_model_route(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, Any] = {}
    provider = str(raw.get("provider") or "").strip()
    model = str(raw.get("model") or "").strip()
    if provider:
        cleaned["provider"] = provider
    if model:
        cleaned["model"] = model
    if raw.get("temperature") is not None:
        try:
            cleaned["temperature"] = float(raw.get("temperature"))
        except Exception:
            pass
    return cleaned


def _configured_route(config: dict[str, Any], step_id: str, role: str) -> dict[str, Any]:
    step_routes = config.get("advanced_generation_routes")
    if isinstance(step_routes, dict):
        route = _clean_model_route(step_routes.get(step_id))
        if route:
            return route

    role_routes = config.get("advanced_generation_providers")
    if isinstance(role_routes, dict):
        route = _clean_model_route(role_routes.get(role))
        if route:
            return route
    return {}


def resolve_step_generation_route(
    step_id: str,
    metadata: dict[str, Any],
    base_generation_kwargs: dict[str, Any] | None = None,
    current_temperature: float | None = None,
) -> StepGenerationRoute:
    """根据项目配置，为单个步骤解析高级生成模型路由。"""
    base_kwargs = {
        key: str(value).strip()
        for key, value in (base_generation_kwargs or {}).items()
        if key in {"provider", "model"} and str(value or "").strip()
    }
    role = step_role(step_id)
    if not advanced_generation_enabled(metadata):
        return StepGenerationRoute(
            enabled=False,
            step_id=str(step_id or "").strip(),
            role=role,
            role_label=ROLE_LABELS.get(role, role),
            generation_kwargs=base_kwargs,
            temperature=current_temperature,
            reason="未开启高级生成模式，沿用项目模型。",
        )

    config = _project_config(metadata)
    configured = _configured_route(config, str(step_id or "").strip(), role)
    generation_kwargs = dict(base_kwargs)
    for key in ("provider", "model"):
        if configured.get(key):
            generation_kwargs[key] = str(configured[key])

    temperature = current_temperature
    if configured.get("temperature") is not None:
        temperature = float(configured["temperature"])
    elif temperature is None:
        temperature = ROLE_DEFAULT_TEMPERATURE.get(role)

    return StepGenerationRoute(
        enabled=True,
        step_id=str(step_id or "").strip(),
        role=role,
        role_label=ROLE_LABELS.get(role, role),
        generation_kwargs=generation_kwargs,
        temperature=temperature,
        reason=f"高级生成模式：{ROLE_LABELS.get(role, role)}步骤使用{role}路由。",
    )


def build_advanced_generation_plan(
    metadata: dict[str, Any],
    base_generation_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回高级生成模式的步骤路由预览，不触发 LLM 调用。"""
    profile = match_advanced_generation_profile(str((_project_config(metadata).get("project_type") or "")))
    step_ids = [str(item.get("id") or "").strip() for item in profile.get("workflow_steps") or []]
    routes = []
    for step_id in [item for item in step_ids if item]:
        route = resolve_step_generation_route(step_id, metadata, base_generation_kwargs)
        routes.append({
            "step_id": route.step_id,
            "role": route.role,
            "role_label": route.role_label,
            "provider": route.generation_kwargs.get("provider", ""),
            "model": route.generation_kwargs.get("model", ""),
            "temperature": route.temperature,
            "reason": route.reason,
        })
    return {
        "mode_id": MODE_ID,
        "mode_label": MODE_LABEL,
        "enabled": advanced_generation_enabled(metadata),
        "profile_id": profile.get("id", "short_drama"),
        "profile_label": profile.get("label", "短剧"),
        "routes": routes,
    }


def resolve_testing_generation_route(
    req: "TestingScriptRequest",
    step_id: str,
    current_temperature: float | None = None,
) -> StepGenerationRoute:
    """为剧本写作页请求解析单模型/多模型路由。"""
    metadata = {
        "project": {
            "project_type": str(getattr(req, "project_type", "") or ""),
            "config": {
                "advanced_generation_mode": bool(getattr(req, "advanced_generation_mode", False)),
                "advanced_generation_providers": getattr(req, "advanced_generation_providers", {}) or {},
                "advanced_generation_routes": getattr(req, "advanced_generation_routes", {}) or {},
            },
        }
    }
    base_generation_kwargs = {}
    provider = str(getattr(req, "generation_provider", "") or "").strip()
    model = str(getattr(req, "generation_model", "") or "").strip()
    if provider:
        base_generation_kwargs["provider"] = provider
    if model:
        base_generation_kwargs["model"] = model
    return resolve_step_generation_route(
        step_id,
        metadata,
        base_generation_kwargs,
        current_temperature,
    )


def apply_testing_generation_route(
    req: "TestingScriptRequest",
    step_id: str,
    current_temperature: float | None = None,
) -> tuple["TestingScriptRequest", StepGenerationRoute]:
    """返回带目标模型字段的请求副本，供写作/评审各走各的链路。"""
    route = resolve_testing_generation_route(req, step_id, current_temperature)
    if not route.enabled:
        return req, route
    updates: dict[str, Any] = {}
    provider = route.generation_kwargs.get("provider")
    model = route.generation_kwargs.get("model")
    if provider:
        updates["generation_provider"] = provider
    if model:
        updates["generation_model"] = model
    if route.temperature is not None:
        updates["temperature"] = route.temperature
    return req.model_copy(update=updates), route
