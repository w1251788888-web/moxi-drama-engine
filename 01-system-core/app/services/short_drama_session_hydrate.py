"""会话写作元数据 hydrate（从 short_drama_writing.py 抽出）。

1 个函数：

- hydrate_session_project_runtime_context：把 ProjectV2 行 + workspace/project.json 的运行时字段
  补回 metadata["project"]，让后续 prompt 装配能直接用。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.project_v2 import ProjectV2
from app.services import workspace_service


def hydrate_session_project_runtime_context(
    db: Session, metadata: dict[str, Any]
) -> dict[str, Any]:
    """把 ProjectV2 行 + workspace/project.json 的运行时字段补回 metadata。"""
    project = metadata.get("project") or {}
    if not isinstance(project, dict):
        return metadata

    project_id = str(project.get("project_id") or project.get("id") or "").strip()
    if not project_id:
        return metadata

    db_project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
    if not db_project:
        return metadata

    project["project_type"] = project.get("project_type") or db_project.project_type
    project["audience_axis"] = project.get("audience_axis") or db_project.audience_axis
    project["genre_main"] = project.get("genre_main") or db_project.genre_main
    project["genre_sub"] = project.get("genre_sub") or db_project.genre_sub
    project["episode_count"] = project.get("episode_count") or db_project.total_episodes
    config_payload = db_project.get_config()
    if isinstance(config_payload, dict):
        project["config"] = config_payload
        project["episode_minutes"] = project.get("episode_minutes") or config_payload.get("episode_minutes")
        project["scene_header_style"] = project.get("scene_header_style") or config_payload.get("scene_header_style")
        project["word_count_per_episode"] = project.get("word_count_per_episode") or config_payload.get("word_count_per_episode")

    try:
        workspace = workspace_service.ensure_project_workspace(
            db_project.workspace_path or "",
            allowed_roots=workspace_service.project_workspace_roots(),
            create=False,
        )
    except workspace_service.WorkspaceError:
        workspace = None

    if workspace:
        payload = workspace_service.read_project_json(workspace)
        project["state_cards"] = payload.get("state_cards") or project.get("state_cards") or {}
        project["characters"] = payload.get("characters") or project.get("characters") or []
        # 把项目级 workflow_context（含大纲编辑器"已确认进入主链"的 outline_state）补进 metadata，
        # 供 build_base_template_vars 的"编辑器→剧本"桥接使用；项目级=多人协作共享。
        workflow_ctx = payload.get("workflow_context")
        if isinstance(workflow_ctx, dict) and workflow_ctx:
            existing_ctx = metadata.get("workflow_context")
            if isinstance(existing_ctx, dict):
                merged_ctx = dict(existing_ctx)
                merged_ctx.update(workflow_ctx)
                metadata["workflow_context"] = merged_ctx
            else:
                metadata["workflow_context"] = workflow_ctx

    metadata["project"] = project
    return metadata
