"""Yjs 协同编辑技术验证服务。

Yjs 主要运行在前端。这里不把它变成后端强依赖，只负责：
- 检查前端是否声明了 Yjs 相关依赖；
- 给出协同文档/传输层接入计划；
- 缺依赖时明确降级到现有 REST autosave 主链路。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import config


FEATURE_ID = "yjs_collaboration"
FEATURE_LABEL = "Yjs 协同编辑"
REQUIRED_DEPENDENCIES = ("yjs",)
TRANSPORT_DEPENDENCIES = ("y-websocket", "y-webrtc")


def get_yjs_collaboration_status(package_json_path: Path | None = None) -> dict[str, Any]:
    """返回 Yjs 协同能力状态。"""
    package_path = package_json_path or _default_package_json_path()
    deps = _read_frontend_dependencies(package_path)
    required_present = [name for name in REQUIRED_DEPENDENCIES if name in deps]
    missing_required = [name for name in REQUIRED_DEPENDENCIES if name not in deps]
    transports = [name for name in TRANSPORT_DEPENDENCIES if name in deps]
    available = not missing_required and bool(transports)
    if not missing_required and not transports:
        missing_required = ["y-websocket 或 y-webrtc"]

    return {
        "feature_id": FEATURE_ID,
        "feature_label": FEATURE_LABEL,
        "available": available,
        "backend": "yjs_client_ready" if available else "rest_autosave_fallback",
        "degraded": not available,
        "package_json": str(package_path),
        "dependencies": {name: deps[name] for name in sorted(deps) if _is_yjs_dependency(name)},
        "missing_dependencies": missing_required,
        "transport": transports[0] if transports else "",
        "fallback": "现有 project scene save / workflow-context / state-cards REST autosave",
        "error": "" if available else f"missing frontend dependencies: {', '.join(missing_required)}",
    }


def build_yjs_collaboration_plan(package_json_path: Path | None = None) -> dict[str, Any]:
    """返回协同编辑接入计划；不启动真实协同服务。"""
    status = get_yjs_collaboration_status(package_json_path)
    return {
        **status,
        "entrypoint": "script_scene_editor",
        "documents": [
            {
                "id": "scene_content",
                "label": "场景正文",
                "ydoc_key": "project:{project_id}:episode:{episode_number}:scene:{scene_number}:content",
                "fallback_api": "POST /api/v2/projects/{project_id}/episodes/{episode_number}/scenes/{scene_number}/save",
                "conflict_policy": "Y.Text 增量合并；降级时以 REST 保存版本链为准",
            },
            {
                "id": "workflow_context",
                "label": "工作流上下文",
                "ydoc_key": "project:{project_id}:workflow-context",
                "fallback_api": "PUT /api/v2/projects/{project_id}/workflow-context",
                "conflict_policy": "Y.Map 分区合并；降级时继续使用服务端 merge",
            },
            {
                "id": "state_cards",
                "label": "状态卡",
                "ydoc_key": "project:{project_id}:state-cards",
                "fallback_api": "PUT /api/v2/projects/{project_id}/state-cards",
                "conflict_policy": "按 card id 合并；降级时保持当前卡片整体保存",
            },
        ],
        "presence": {
            "enabled_when_available": True,
            "fields": ["user_id", "display_name", "cursor", "selection", "active_scene"],
            "fallback": "单人编辑模式，不显示在线游标",
        },
        "acceptance_gates": [
            "不安装 Yjs 时主链路保存、导出、刷新读取必须继续通过",
            "安装 Yjs 与传输依赖后状态接口必须显示 yjs_client_ready",
            "协同编辑正式接入前必须保留 REST autosave 作为兜底路径",
        ],
    }


def _default_package_json_path() -> Path:
    return Path(config.base_dir) / "webui" / "package.json"


def _read_frontend_dependencies(package_path: Path) -> dict[str, str]:
    try:
        raw = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    deps: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        values = raw.get(section)
        if isinstance(values, dict):
            for name, version in values.items():
                deps[str(name)] = str(version)
    return deps


def _is_yjs_dependency(name: str) -> bool:
    return name == "yjs" or name.startswith("y-")
