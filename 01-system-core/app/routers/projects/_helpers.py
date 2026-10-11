"""项目 V2 工作区/版本辅助函数（从 projects_v2.py 抽出）。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.models.project_v2 import (
    ContributionLedger,
    Checkpoint,
    ContentVersion,
    Episode,
    GenerationJob,
    ModelProvider,
    ProjectV2,
    Scene,
)

from app.routers.projects._schemas import ProjectResponse, ProjectConfig
from app.services import workspace_service
from app.services.duration_profile_service import duration_profile_from_seconds

REPO_ROOT = workspace_service.REPO_ROOT
PROJECT_LIBRARY_ROOT = workspace_service.PROJECT_LIBRARY_ROOT
WORKSPACE_ROOT = workspace_service.WORKSPACE_ROOT
LEGACY_WORKSPACE_ROOT = workspace_service.LEGACY_WORKSPACE_ROOT

DEFAULT_ADVANCED_GENERATION_PROVIDERS = {
    "logic": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.25},
    "creative": {"provider": "kimi", "model": "kimi-k2.6", "temperature": 0.85},
    "review": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.0},
}


def _path_is_relative_to(path: Path, root: Path) -> bool:
    return workspace_service.path_is_relative_to(path, root)


def _safe_project_dir_name(project_name: str) -> str:
    """项目名只能作为单层目录名，避免通过名称穿越工作区根。"""
    return workspace_service.safe_project_dir_name(project_name)


def _workspace_delete_roots() -> tuple[Path, ...]:
    """允许项目工作区删除的根目录；保留旧中文目录兼容历史项目。"""
    roots = [WORKSPACE_ROOT]
    if LEGACY_WORKSPACE_ROOT != WORKSPACE_ROOT:
        roots.append(LEGACY_WORKSPACE_ROOT)
    return tuple(roots)


def _project_library_delete_roots() -> tuple[Path, ...]:
    """管理任务可清理的产物根，限制在项目库下。"""
    return (PROJECT_LIBRARY_ROOT,)


def _safe_rmtree(path: str | Path, *, allowed_roots: Iterable[Path]) -> bool:
    """只删除 allowed_roots 下的子目录，拒绝根目录本身和越界路径。"""
    return workspace_service.safe_rmtree(path, allowed_roots=allowed_roots)


def _rebased_release_workspace_path(project: ProjectV2) -> Path | None:
    """Map a project workspace saved under an older release to the current release root.

    Deployment uses immutable release directories. A project created before a new
    release can still have a DB workspace_path pointing at the old release. We only
    rebase paths that clearly belong to the project library and whose final folder
    matches this DB project's name.
    """
    raw_workspace = str(project.workspace_path or "").strip()
    project_name = str(project.name or "").strip()
    if not raw_workspace or not project_name:
        return None

    parts = Path(raw_workspace).expanduser().parts
    for index, part in enumerate(parts):
        if part != "03-project-library":
            continue
        if index + 2 >= len(parts):
            continue
        root_name = parts[index + 1]
        if root_name not in {"new-projects", "新建项目"}:
            continue
        relative_parts = parts[index + 2 :]
        if not relative_parts or relative_parts[-1] != project_name:
            return None
        target_root = WORKSPACE_ROOT if root_name == "new-projects" else LEGACY_WORKSPACE_ROOT
        return target_root.joinpath(*relative_parts)
    return None


def _ensure_rebased_project_workspace(project: ProjectV2, *, create: bool) -> Path | None:
    rebased = _rebased_release_workspace_path(project)
    if rebased is None:
        return None

    allowed_roots = _workspace_delete_roots()
    source = Path(project.workspace_path or "").expanduser()
    if not rebased.exists():
        if source.exists() and source.is_dir():
            rebased.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, rebased, dirs_exist_ok=True)
        elif create:
            rebased.mkdir(parents=True, exist_ok=True)

    workspace = workspace_service.ensure_project_workspace(
        rebased,
        allowed_roots=allowed_roots,
        create=create,
    )
    project.workspace_path = str(workspace)
    return workspace


def _get_workspace_path(project_name: str, owner_scope: Sequence[str] | None = None) -> Path:
    """获取项目工作区路径"""
    root = WORKSPACE_ROOT
    for part in owner_scope or ():
        root = root / workspace_service.safe_file_part(str(part))
    return root / _safe_project_dir_name(project_name)


def _ensure_project_workspace_path(project: ProjectV2, *, create: bool = True) -> Path:
    """Return a validated workspace path for an existing DB project."""
    try:
        return workspace_service.ensure_project_workspace(
            project.workspace_path or "",
            allowed_roots=_workspace_delete_roots(),
            create=create,
        )
    except workspace_service.WorkspaceBoundaryError:
        rebased = _ensure_rebased_project_workspace(project, create=create)
        if rebased is not None:
            return rebased
        raise


def _episode_dir_path(project: ProjectV2, episode_number: int, *, create: bool = True) -> Path:
    workspace = _ensure_project_workspace_path(project, create=create)
    return workspace_service.episode_dir(workspace, episode_number, create=create)


def _scene_version_file_path(
    project: ProjectV2,
    *,
    episode_number: int,
    scene_number: int,
    version_code: str,
) -> Path:
    workspace = _ensure_project_workspace_path(project, create=True)
    return workspace_service.scene_version_path(
        workspace,
        episode_number=episode_number,
        scene_number=scene_number,
        version_code=version_code,
    )


def _checkpoint_file_path(project: ProjectV2, checkpoint_code: str) -> Path:
    workspace = _ensure_project_workspace_path(project, create=True)
    return workspace_service.checkpoint_path(workspace, checkpoint_code)


def _generation_job_artifact_file_path(
    project: ProjectV2 | None,
    *,
    job_id: str,
    artifact_type: str,
    suffix: str,
) -> Path:
    workspace: Path | None = None
    if project and project.workspace_path:
        workspace = _ensure_project_workspace_path(project, create=True)
    return workspace_service.generation_job_artifact_path(
        workspace,
        job_id=job_id,
        artifact_type=artifact_type,
        suffix=suffix,
    )


def _load_workspace_index(index_root: Path) -> dict[str, Any]:
    index = {"projects": []}
    if not index_root.exists():
        return index

    try:
        raw_index = json.loads(index_root.read_text(encoding="utf-8"))
    except Exception:
        return index

    if isinstance(raw_index, dict):
        index = raw_index
        if not isinstance(index.get("projects"), list):
            index["projects"] = []
    elif isinstance(raw_index, list):
        index = {"projects": raw_index}
    return index


def _upsert_workspace_index_entry(
    *,
    workspace: Path,
    project_name: str,
    project_id: str = "",
    created_at: Optional[str] = None,
    status: str = "active",
) -> None:
    now = datetime.now().isoformat()
    index_root = workspace.parent / "_index.json"
    index = _load_workspace_index(index_root)

    project_entry = {
        "name": project_name,
        "path": str(workspace),
        "created": created_at or now,
        "last_active": now,
        "status": status or "active",
    }
    if project_id:
        project_entry["id"] = project_id

    retained: list[dict[str, Any]] = []
    for item in index.get("projects", []):
        if not isinstance(item, dict):
            continue
        same_project = (
            item.get("path") == str(workspace)
            or item.get("id") == project_id
            or item.get("name") == project_name
        )
        if same_project:
            project_entry["created"] = item.get("created") or project_entry["created"]
            continue
        retained.append(item)

    index["projects"] = retained + [project_entry]
    index_root.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_workspace_index_entry(
    *,
    workspace: str | Path | None,
    project_name: str = "",
    project_id: str = "",
) -> None:
    """Remove a deleted project from the workspace-level _index.json."""
    workspace_path = Path(workspace) if workspace else None
    index_parent = WORKSPACE_ROOT.parent
    if workspace_path:
        resolved_workspace = workspace_path.expanduser().resolve()
        for root in _workspace_delete_roots():
            resolved_root = root.expanduser().resolve()
            if resolved_workspace != resolved_root and _path_is_relative_to(resolved_workspace, resolved_root):
                index_parent = resolved_workspace.parent
                break
    index_root = index_parent / "_index.json"
    if not index_root.exists():
        return

    index = _load_workspace_index(index_root)
    workspace_text = str(workspace_path) if workspace_path else ""
    retained: list[dict[str, Any]] = []
    removed = False

    for item in index.get("projects", []):
        if not isinstance(item, dict):
            continue
        same_project = (
            (bool(project_id) and item.get("id") == project_id)
            or (bool(workspace_text) and item.get("path") == workspace_text)
            or (bool(project_name) and item.get("name") == project_name)
        )
        if same_project:
            removed = True
            continue
        retained.append(item)

    if removed:
        index["projects"] = retained
        index_root.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _init_workspace(
    project_name: str,
    config: dict,
    owner_scope: Sequence[str] | None = None,
) -> Path:
    """初始化项目工作区目录结构"""
    owner_scope_parts = tuple(str(part) for part in (owner_scope or ()) if str(part or "").strip())
    project_path = _get_workspace_path(project_name, owner_scope_parts)

    # 创建目录结构
    (project_path / "characters").mkdir(parents=True, exist_ok=True)
    (project_path / "episodes").mkdir(parents=True, exist_ok=True)
    (project_path / "materials").mkdir(parents=True, exist_ok=True)
    (project_path / "archive").mkdir(parents=True, exist_ok=True)
    (project_path / "checkpoints").mkdir(parents=True, exist_ok=True)

    # 创建项目索引文件
    project_data = {
        "name": project_name,
        "created_at": datetime.now().isoformat(),
        "config": config,
        "owner_scope": "/".join(owner_scope_parts),
        "progress": {
            "completed": 0,
            "in_progress": None,
            "last_episode": None
        },
        "characters": [],
        "state_cards": {
            "relationship_cards": [],
            "info_cards": [],
            "power_cards": [],
            "promise_cards": [],
            "locked_fact_cards": [],
        },
        "workflow_context": _default_workflow_context(),
        "canon_packet": {},
        "episode_memory_cards": [],
        "unresolved_hooks": [],
        "key_plots": []
    }

    index_file = project_path / "project.json"
    index_file.write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 更新全局索引
    _upsert_workspace_index_entry(
        workspace=project_path,
        project_name=project_name,
        created_at=project_data["created_at"],
        status="active",
    )

    return project_path


def _derive_word_count_range(episode_seconds: int) -> str:
    safe_seconds = max(30, min(600, int(episode_seconds or 90)))
    profile = duration_profile_from_seconds(safe_seconds)
    return f"{profile.min_chars}-{profile.max_chars}"


def _normalize_episode_count_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        count = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None
    return max(1, min(200, count))


def _recommend_classification_tracks(
    *,
    project_type: str,
    audience_axis: str,
    genre_main: str,
    genre_sub: str,
) -> tuple[str, str]:
    text = " ".join(
        part.strip()
        for part in [project_type, audience_axis, genre_main, genre_sub]
        if str(part or "").strip()
    )

    if "女频" in audience_axis:
        if any(token in text for token in ("豪门", "打脸", "虐渣", "订婚宴", "录音", "证据", "站队", "背叛")):
            return ("subgenre_female_face_slap", "sample_track_a_high_pressure_female")
        if any(token in text for token in ("危险关系", "督军", "少帅", "军阀", "家法", "规矩", "民国")):
            return ("subgenre_female_power_taming", "sample_track_b_power_taming")
        if any(token in text for token in ("先婚后爱", "错认", "误认", "替嫁", "错嫁", "婚配", "花轿", "盖头")):
            return ("subgenre_female_misrecognition", "sample_track_c_misrecognition_secret")
        return ("female_subgenres", "")

    if "男频" in audience_axis:
        return ("male_subgenres", "")

    if any(token in text for token in ("现实情感", "乡土", "亲情", "代际", "回乡", "送站", "上坟", "看病", "债务", "罚单")):
        return ("subgenre_hybrid_realistic_family", "sample_track_d_realistic_family")

    return ("hybrid_subgenres", "")


def _normalize_project_config_payload(
    config_dict: Optional[dict[str, Any]],
    *,
    project_type: str = "",
    audience_axis: str = "",
    genre_main: str = "",
    genre_sub: str = "",
) -> dict[str, Any]:
    payload = dict(config_dict or {})

    raw_seconds = payload.get("episode_seconds")
    raw_minutes = payload.get("episode_minutes")

    if isinstance(raw_seconds, (int, float)) and raw_seconds > 0:
        seconds = int(round(raw_seconds))
    elif isinstance(raw_minutes, (int, float)) and raw_minutes > 0:
        seconds = int(round(float(raw_minutes) * 60))
    else:
        seconds = 90

    seconds = max(30, min(600, seconds))
    payload["episode_seconds"] = seconds
    payload["episode_minutes"] = round(seconds / 60, 3)

    confirmed = _normalize_episode_count_value(payload.get("confirmed_total_episodes"))
    suggested = _normalize_episode_count_value(payload.get("suggested_total_episodes"))
    legacy = _normalize_episode_count_value(payload.get("total_episodes"))
    status = str(payload.get("episode_count_status") or "").strip()
    if not confirmed and status == "confirmed" and legacy:
        confirmed = legacy

    if confirmed:
        payload["confirmed_total_episodes"] = confirmed
        payload["suggested_total_episodes"] = suggested
        payload["total_episodes"] = confirmed
        payload["episode_count_status"] = "confirmed"
    elif legacy:
        payload["confirmed_total_episodes"] = None
        payload["suggested_total_episodes"] = suggested or legacy
        payload["total_episodes"] = legacy
        payload["episode_count_status"] = "legacy_needs_confirmation"
    else:
        payload["confirmed_total_episodes"] = None
        payload["suggested_total_episodes"] = suggested
        payload["total_episodes"] = None
        payload["episode_count_status"] = "unconfirmed"
    payload["episode_count_confirmation_source"] = str(payload.get("episode_count_confirmation_source") or "").strip()
    payload["episode_count_confirmed_at"] = str(payload.get("episode_count_confirmed_at") or "").strip()

    style = str(payload.get("scene_header_style") or "bracket").strip().lower()
    payload["scene_header_style"] = "plain" if style == "plain" else "bracket"

    word_count = str(payload.get("word_count_per_episode") or "").strip()
    if not word_count:
        payload["word_count_per_episode"] = _derive_word_count_range(seconds)

    payload["manga_mode"] = bool(payload.get("manga_mode", False))
    payload["premium_mode"] = bool(payload.get("premium_mode", False))
    payload["advanced_generation_mode"] = bool(payload.get("advanced_generation_mode", False))
    payload["advanced_generation_profile_id"] = str(payload.get("advanced_generation_profile_id") or "").strip()
    payload["advanced_generation_providers"] = (
        payload.get("advanced_generation_providers")
        if isinstance(payload.get("advanced_generation_providers"), dict)
        else {}
    )
    if payload["advanced_generation_mode"] and not payload["advanced_generation_providers"]:
        payload["advanced_generation_providers"] = json.loads(json.dumps(DEFAULT_ADVANCED_GENERATION_PROVIDERS))
    payload["advanced_generation_routes"] = (
        payload.get("advanced_generation_routes")
        if isinstance(payload.get("advanced_generation_routes"), dict)
        else {}
    )
    payload["generation_provider"] = str(payload.get("generation_provider") or "").strip()
    payload["generation_model"] = str(payload.get("generation_model") or "").strip()
    payload["rights_capture_enabled"] = bool(payload.get("rights_capture_enabled", True))

    recommended_subgenre, recommended_sample = _recommend_classification_tracks(
        project_type=str(project_type or ""),
        audience_axis=str(audience_axis or ""),
        genre_main=str(genre_main or ""),
        genre_sub=str(genre_sub or ""),
    )
    payload["subgenre_track"] = str(payload.get("subgenre_track") or "").strip() or recommended_subgenre
    payload["sample_track"] = str(payload.get("sample_track") or "").strip() or recommended_sample
    return payload


def _sync_workspace_project_index(project: ProjectV2) -> None:
    if not project.workspace_path:
        return
    workspace = workspace_service.ensure_project_workspace(
        project.workspace_path,
        allowed_roots=_workspace_delete_roots(),
        create=True,
    )

    now = datetime.now().isoformat()
    config = _normalize_project_config_payload(
        project.get_config(),
        project_type=project.project_type,
        audience_axis=project.audience_axis,
        genre_main=project.genre_main,
        genre_sub=project.genre_sub,
    )
    index_file = workspace / "project.json"
    project_data: dict[str, Any] = {}
    if index_file.exists():
        try:
            project_data = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            project_data = {}

    project_data.update({
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "project_type": project.project_type,
        "audience_axis": project.audience_axis,
        "genre_main": project.genre_main,
        "genre_sub": project.genre_sub,
        "total_episodes": project.total_episodes,
        "status": project.status,
        "created_by": project.created_by,
        "creation_mode": getattr(project, "creation_mode", "solo") or "solo",
        "rights_capture_enabled": bool(getattr(project, "rights_capture_enabled", True)),
        "updated_at": now,
        "config": config,
        "classification": {
            "subgenre_track": config.get("subgenre_track", ""),
            "sample_track": config.get("sample_track", ""),
        },
    })
    project_data["progress"] = {
        "completed": int(project.completed_episodes or 0),
        "in_progress": None if project.status == "completed" else int(project.current_episode or 1),
        "last_episode": int(project.current_episode or 1),
    }
    project_data.setdefault("characters", [])
    project_data.setdefault("state_cards", {
        "relationship_cards": [],
        "info_cards": [],
        "power_cards": [],
        "promise_cards": [],
        "locked_fact_cards": [],
    })
    project_data.setdefault("workflow_context", _default_workflow_context())
    project_data.setdefault("canon_packet", {})
    project_data.setdefault("episode_memory_cards", [])
    project_data.setdefault("unresolved_hooks", [])
    project_data.setdefault("key_plots", [])
    index_file.write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _upsert_workspace_index_entry(
        workspace=workspace,
        project_name=project.name,
        project_id=project.id,
        created_at=project.created_at.isoformat() if project.created_at else None,
        status=project.status or "active",
    )


def _actor_is_admin(actor: Any) -> bool:
    return bool(getattr(actor, "is_admin", False) or getattr(actor, "actor_type", "") == "admin")


def _actor_access_key_id(actor: Any) -> str:
    return str(getattr(actor, "access_key_id", "") or "").strip()


def _workspace_owner_scope_from_actor(actor: Any) -> tuple[str, ...]:
    """Return the filesystem owner scope for new projects.

    DB permission checks remain the source of truth. This scope only controls
    where newly-created project folders are placed so user data is not mixed in
    one flat workspace directory.
    """
    if _actor_is_admin(actor):
        return ("admin", "default")
    access_key_id = _actor_access_key_id(actor)
    if access_key_id:
        return ("users", access_key_id)
    return ("anonymous",)


def _project_owner_key_from_actor(actor: Any) -> str:
    """Return the DB owner key used for per-owner project uniqueness."""
    if _actor_is_admin(actor):
        return ""
    return _actor_access_key_id(actor)


def _stamp_project_owner_from_actor(project: ProjectV2, actor: Any) -> None:
    if _actor_is_admin(actor):
        return
    access_key_id = _actor_access_key_id(actor)
    if access_key_id:
        project.created_by = access_key_id


def _filter_projects_for_actor(query: Any, actor: Any) -> Any:
    if _actor_is_admin(actor):
        return query
    access_key_id = _actor_access_key_id(actor)
    if not access_key_id:
        return query.filter(ProjectV2.id == "__no_access__")
    try:
        from app.models.collaboration import ProjectMember
        member_project_ids = (
            query.session.query(ProjectMember.project_id)
            .filter(ProjectMember.access_key_id == access_key_id, ProjectMember.status == "active")
        )
        return query.filter(or_(ProjectV2.created_by == access_key_id, ProjectV2.id.in_(member_project_ids)))
    except Exception:
        return query.filter(ProjectV2.created_by == access_key_id)


def _ensure_project_actor_access(project: ProjectV2, actor: Any, db: Session | None = None) -> None:
    if _actor_is_admin(actor):
        return
    access_key_id = _actor_access_key_id(actor)
    if access_key_id and str(project.created_by or "") == access_key_id:
        return
    if access_key_id:
        try:
            from app.models.collaboration import ProjectMember

            owns_session = db is None
            if db is None:
                from app.database import SessionLocal
                db = SessionLocal()
            try:
                if db.query(ProjectMember).filter(
                    ProjectMember.project_id == project.id,
                    ProjectMember.access_key_id == access_key_id,
                    ProjectMember.status == "active",
                ).first():
                    return
            finally:
                if owns_session:
                    db.close()
        except Exception:
            pass
    raise HTTPException(status_code=403, detail="无权访问该项目")


def _get_project_for_actor_or_404(db: Session, project_id: str, actor: Any) -> ProjectV2:
    project = db.query(ProjectV2).filter(ProjectV2.id == str(project_id)).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    _ensure_project_actor_access(project, actor, db=db)
    return project


def _scene_has_written_content(scene: Scene) -> bool:
    return bool(str(scene.content or "").strip()) or int(scene.word_count or 0) > 0


def _calculate_episode_writing_progress(
    db: Session,
    episode: Episode,
    *,
    persist: bool = False,
) -> dict[str, Any]:
    scenes = (
        db.query(Scene)
        .filter(Scene.episode_id == episode.id)
        .order_by(Scene.scene_number)
        .all()
    )
    total_scenes = len(scenes)
    completed_scenes = sum(1 for scene in scenes if _scene_has_written_content(scene))
    is_completed = total_scenes > 0 and completed_scenes >= total_scenes
    has_progress = completed_scenes > 0

    status = episode.status or "draft"
    if is_completed:
        status = "completed"
    elif has_progress and status in {"", "draft", "planning"}:
        status = "writing"

    if persist:
        episode.total_scenes = total_scenes
        episode.completed_scenes = completed_scenes
        episode.status = status

    return {
        "total_scenes": total_scenes,
        "completed_scenes": completed_scenes,
        "is_completed": is_completed,
        "has_progress": has_progress,
        "status": status,
    }


def _calculate_project_writing_progress(
    db: Session,
    project: ProjectV2,
    *,
    persist: bool = False,
) -> dict[str, Any]:
    episodes = (
        db.query(Episode)
        .filter(Episode.project_id == project.id)
        .order_by(Episode.episode_number)
        .all()
    )
    completed_episodes = 0
    latest_active_episode = int(project.current_episode or 1)
    has_any_progress = False

    for episode in episodes:
        progress = _calculate_episode_writing_progress(db, episode, persist=persist)
        if progress["is_completed"]:
            completed_episodes += 1
        if progress["has_progress"]:
            has_any_progress = True
            latest_active_episode = max(latest_active_episode, int(episode.episode_number or 1))

    total_episodes = max(0, int(project.total_episodes or 0))
    completed_episodes = min(completed_episodes, total_episodes) if total_episodes else 0
    status = project.status or "planning"
    if total_episodes and completed_episodes >= total_episodes:
        status = "completed"
    elif has_any_progress and status == "planning":
        status = "active"

    if persist:
        project.completed_episodes = completed_episodes
        project.current_episode = latest_active_episode
        project.status = status

    return {
        "completed_episodes": completed_episodes,
        "current_episode": latest_active_episode,
        "status": status,
    }


def _build_project_response(project: ProjectV2, db: Session | None = None) -> ProjectResponse:
    config = _normalize_project_config_payload(project.get_config())
    progress = _calculate_project_writing_progress(db, project) if db is not None else {}
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        audience_axis=project.audience_axis,
        genre_main=project.genre_main,
        genre_sub=project.genre_sub,
        creation_mode=getattr(project, "creation_mode", "solo") or "solo",
        rights_capture_enabled=bool(getattr(project, "rights_capture_enabled", True)),
        total_episodes=project.total_episodes,
        completed_episodes=int(progress.get("completed_episodes", project.completed_episodes) or 0),
        current_episode=int(progress.get("current_episode", project.current_episode) or 1),
        status=str(progress.get("status", project.status) or "planning"),
        workspace_path=project.workspace_path,
        config=ProjectConfig(**config),
        created_at=project.created_at,
        updated_at=project.updated_at
    )


def _load_workspace_project_data(project: ProjectV2) -> dict[str, Any]:
    try:
        workspace = _ensure_project_workspace_path(project, create=False)
    except workspace_service.WorkspaceMissingError:
        return {}
    return workspace_service.read_project_json(workspace)


def _write_workspace_project_data(project: ProjectV2, data: dict[str, Any]) -> None:
    workspace = _ensure_project_workspace_path(project, create=True)
    workspace_service.write_project_json(
        workspace,
        data,
        allowed_roots=_workspace_delete_roots(),
        create=True,
    )


def _update_workspace_project_data_atomically(
    project: ProjectV2,
    updater: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    workspace = _ensure_project_workspace_path(project, create=True)
    return workspace_service.update_project_json_atomically(
        workspace,
        updater,
        allowed_roots=_workspace_delete_roots(),
        create=True,
    )


def _normalize_state_cards_payload(raw: Any) -> dict[str, list[dict[str, Any]]]:
    base = {
        "relationship_cards": [],
        "info_cards": [],
        "power_cards": [],
        "promise_cards": [],
        "locked_fact_cards": [],
    }
    if not isinstance(raw, dict):
        return base
    result: dict[str, list[dict[str, Any]]] = {}
    for key, default in base.items():
        value = raw.get(key)
        result[key] = value if isinstance(value, list) else list(default)
    return result


def _default_workflow_context() -> dict[str, Any]:
    return {
        "materials": [],
        "issue_feedback": {},
        "rule_profile": "",
        "world_rules": "",
        "golden_finger_rules": "",
        "conflict_plan": "",
        "quality_report": {},
        "compliance_report": {},
        "episode_novel_anchor": "",
        "rag_context": {},
        "series_simulation_packet": {},
        "rag_context_cards": [],
        "rag_evidence_log": [],
        "chat_brainstorm": {},
        "outline_state": {},
        "director_blueprint": {},
        "director_blueprints": {},
        "director_generation_trace": {},
        "script_segment_progress": {},
        "script_generation_failure_log": [],
        "manual_edit_context": {},
        "final_generation_contract": {},
        "core_generation_contract_hash": "",
        "rag_evidence_hash": "",
        "final_generation_contract_hash": "",
        "existing_script_opt_out": {},
    }


_DANGEROUS_AUTHORITY_KEYS = {
    "official",
    "is_confirmed",
    "saved_as_canon",
    "promoted_to_official",
    "main_chain_committed",
    "main_chain_committed_at",
    "downstream_generation_allowed",
    "confirmed",
    "canon",
}


def _strip_dangerous_authority_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_dangerous_authority_keys(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _strip_dangerous_authority_keys(nested)
            for key, nested in value.items()
            if str(key) not in _DANGEROUS_AUTHORITY_KEYS
        }
    return value


def _normalize_canon_packet(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    packet = {
        "premise": str(raw.get("premise") or "").strip(),
        "hard_constraints": _strip_dangerous_authority_keys(raw.get("hard_constraints")) if isinstance(raw.get("hard_constraints"), list) else [],
        "relationship_limits": _strip_dangerous_authority_keys(raw.get("relationship_limits")) if isinstance(raw.get("relationship_limits"), list) else [],
        "information_schedule": _strip_dangerous_authority_keys(raw.get("information_schedule")) if isinstance(raw.get("information_schedule"), list) else [],
        "locked_facts": _strip_dangerous_authority_keys(raw.get("locked_facts")) if isinstance(raw.get("locked_facts"), list) else [],
        "timeline_anchors": _strip_dangerous_authority_keys(raw.get("timeline_anchors")) if isinstance(raw.get("timeline_anchors"), list) else [],
        "last_updated_episode": int(raw.get("last_updated_episode") or 0) if str(raw.get("last_updated_episode") or "").strip() else 0,
        "notes": str(raw.get("notes") or "").strip(),
    }
    extras = {
        str(key): _strip_dangerous_authority_keys(value)
        for key, value in raw.items()
        if key not in packet and str(key) not in _DANGEROUS_AUTHORITY_KEYS
    }
    return {**packet, **extras}


def _normalize_episode_memory_cards(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cards: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            episode_no = int(item.get("episode_no") or item.get("ep") or 0)
        except Exception:
            episode_no = 0
        if episode_no <= 0:
            continue
        cards.append({
            "episode_no": episode_no,
            "title": str(item.get("title") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "opening_state": str(item.get("opening_state") or "").strip(),
            "ending_state": str(item.get("ending_state") or "").strip(),
            "relationship_delta": _strip_dangerous_authority_keys(item.get("relationship_delta")) if isinstance(item.get("relationship_delta"), list) else [],
            "information_delta": _strip_dangerous_authority_keys(item.get("information_delta")) if isinstance(item.get("information_delta"), list) else [],
            "power_delta": _strip_dangerous_authority_keys(item.get("power_delta")) if isinstance(item.get("power_delta"), list) else [],
            "unresolved_hooks": _strip_dangerous_authority_keys(item.get("unresolved_hooks")) if isinstance(item.get("unresolved_hooks"), list) else [],
            "spoiler_guard": _strip_dangerous_authority_keys(item.get("spoiler_guard")) if isinstance(item.get("spoiler_guard"), list) else [],
            "body_excerpt": str(item.get("body_excerpt") or item.get("actual_progress") or "").strip(),
            "quality_summary": str(item.get("quality_summary") or "").strip(),
        })
    cards.sort(key=lambda row: int(row.get("episode_no") or 0))
    return cards


_WORKFLOW_CONTEXT_DANGEROUS_AUTHORITY_KEYS = _DANGEROUS_AUTHORITY_KEYS

_WORKFLOW_CONTEXT_PENDING_KEYS = {
    "candidate_draft_needs_user_confirmation",
    "needs_user_confirmation",
    "needs_user_review",
    "pending_confirmation",
    "user_confirmation_required",
}

_WORKFLOW_CONTEXT_UNSAFE_STATUSES = {
    "candidate",
    "candidate_ready",
    "draft",
    "fallback",
    "local_fallback",
    "needs_user_review",
    "pending_confirmation",
    "review_required",
}

_WORKFLOW_CONTEXT_UNSAFE_SOURCE_MARKERS = (
    "candidate",
    "fallback",
    "legacy",
    "local_fallback",
    "research",
)


def _truthy_workflow_context_marker(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _workflow_context_item_needs_authority_sanitizer(raw: dict[str, Any]) -> bool:
    if "candidate_source" in raw:
        return True
    if _truthy_workflow_context_marker(raw.get("fallback")):
        return True
    if any(_truthy_workflow_context_marker(raw.get(key)) for key in _WORKFLOW_CONTEXT_PENDING_KEYS):
        return True

    status = str(raw.get("status") or raw.get("state") or "").strip().lower()
    if status in _WORKFLOW_CONTEXT_UNSAFE_STATUSES:
        return True

    for key in ("source", "source_type", "origin", "candidate_source"):
        source_value = str(raw.get(key) or "").strip().lower()
        if source_value and any(marker in source_value for marker in _WORKFLOW_CONTEXT_UNSAFE_SOURCE_MARKERS):
            return True
    return False


def _sanitize_workflow_context_authority_flags(value: Any, *, unsafe_scope: bool = False) -> Any:
    if isinstance(value, list):
        return [
            _sanitize_workflow_context_authority_flags(item, unsafe_scope=unsafe_scope)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    item_is_unsafe = unsafe_scope or _workflow_context_item_needs_authority_sanitizer(value)
    sanitized: dict[str, Any] = {}
    for key, nested_value in value.items():
        if item_is_unsafe and key in _WORKFLOW_CONTEXT_DANGEROUS_AUTHORITY_KEYS:
            continue
        sanitized[key] = _sanitize_workflow_context_authority_flags(
            nested_value,
            unsafe_scope=item_is_unsafe,
        )
    return sanitized


def _normalize_workflow_context(raw: Any) -> dict[str, Any]:
    base = _default_workflow_context()
    if not isinstance(raw, dict):
        return base
    base["materials"] = _sanitize_workflow_context_authority_flags(raw.get("materials")) if isinstance(raw.get("materials"), list) else []
    base["issue_feedback"] = _sanitize_workflow_context_authority_flags(raw.get("issue_feedback")) if isinstance(raw.get("issue_feedback"), dict) else {}
    for key in ("rule_profile", "world_rules", "golden_finger_rules", "conflict_plan", "episode_novel_anchor"):
        base[key] = str(raw.get(key) or "").strip()
    for key in (
        "quality_report",
        "compliance_report",
        "rag_context",
        "series_simulation_packet",
        "chat_brainstorm",
        "outline_state",
        "director_blueprint",
        "director_blueprints",
        "director_generation_trace",
        "script_segment_progress",
        "manual_edit_context",
        "final_generation_contract",
        "step_confirmation_overrides",
        "existing_script_opt_out",
    ):
        base[key] = _sanitize_workflow_context_authority_flags(raw.get(key)) if isinstance(raw.get(key), dict) else {}
    for key in ("core_generation_contract_hash", "rag_evidence_hash", "final_generation_contract_hash"):
        base[key] = str(raw.get(key) or "").strip()
    base["rag_context_cards"] = _sanitize_workflow_context_authority_flags(raw.get("rag_context_cards")) if isinstance(raw.get("rag_context_cards"), list) else []
    base["rag_evidence_log"] = _sanitize_workflow_context_authority_flags(raw.get("rag_evidence_log")) if isinstance(raw.get("rag_evidence_log"), list) else []
    base["script_generation_failure_log"] = _sanitize_workflow_context_authority_flags(raw.get("script_generation_failure_log")) if isinstance(raw.get("script_generation_failure_log"), list) else []
    return base


def _normalize_workflow_context_patch(raw: Any) -> dict[str, Any]:
    """Normalize a partial workflow_context patch without filling missing keys.

    This is important for merge writes: a small patch such as chat history must
    not reset rule_profile, RAG context, outline state, or other existing fields.
    """
    if not isinstance(raw, dict):
        return {}
    patch: dict[str, Any] = {}
    for key in ("materials", "rag_context_cards", "rag_evidence_log", "script_generation_failure_log"):
        if key in raw and isinstance(raw.get(key), list):
            patch[key] = _sanitize_workflow_context_authority_flags(raw[key])
    for key in (
        "issue_feedback",
        "quality_report",
        "compliance_report",
        "rag_context",
        "series_simulation_packet",
        "chat_brainstorm",
        "outline_state",
        "director_blueprint",
        "director_blueprints",
        "director_generation_trace",
        "script_segment_progress",
        "manual_edit_context",
        "final_generation_contract",
        "step_confirmation_overrides",
        "existing_script_opt_out",
    ):
        if key in raw and isinstance(raw.get(key), dict):
            patch[key] = _sanitize_workflow_context_authority_flags(raw[key])
    for key in (
        "rule_profile",
        "world_rules",
        "golden_finger_rules",
        "conflict_plan",
        "episode_novel_anchor",
        "core_generation_contract_hash",
        "rag_evidence_hash",
        "final_generation_contract_hash",
    ):
        if key in raw:
            patch[key] = str(raw.get(key) or "").strip()
    return patch


def _deep_merge_dict(dst: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge_dict(dst[key], value)
        else:
            dst[key] = value
    return dst


_LEGACY_CHAT_MIGRATION_SCOPE = "legacy-workflow-context"
_LEGACY_CHAT_MIGRATION_BASE = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = digits[remainder] + result
    return result


def _legacy_chat_hash(value: str) -> str:
    """Match the browser FNV-style hash over JavaScript UTF-16 code units."""
    hashed = 2_166_136_261
    encoded = value.encode("utf-16-le")
    for offset in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[offset:offset + 2], "little")
        hashed = ((hashed ^ code_unit) * 16_777_619) & 0xFFFFFFFF
    return _base36(hashed)


def _legacy_chat_message_id(index: int, role: str, content: str) -> str:
    seed = f"{_LEGACY_CHAT_MIGRATION_SCOPE}|{index}|{role}|{content}"
    return f"legacy-{_legacy_chat_hash(seed)}"


def _legacy_chat_message_created_at(index: int) -> str:
    return (_LEGACY_CHAT_MIGRATION_BASE + timedelta(seconds=index)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_chat_brainstorm_messages(raw: Any) -> list[dict[str, Any]]:
    """Keep only addressable chat messages; retain their original text exactly."""
    if not isinstance(raw, list):
        return []
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        message_id = item.get("id")
        role = item.get("role")
        content = item.get("content")
        created_at = item.get("created_at")
        if (
            role not in {"user", "ai"}
            or not isinstance(content, str)
            or not content.strip()
        ):
            continue
        normalized = {
            "id": message_id.strip() if isinstance(message_id, str) and message_id.strip() else _legacy_chat_message_id(index, role, content),
            "role": role,
            "content": content,
            "created_at": created_at.strip() if isinstance(created_at, str) and created_at.strip() else _legacy_chat_message_created_at(index),
        }
        previous = by_id.get(normalized["id"])
        if previous is None:
            by_id[normalized["id"]] = normalized
            continue
        if normalized["created_at"] > previous["created_at"]:
            by_id[normalized["id"]] = normalized
        elif normalized["created_at"] == previous["created_at"]:
            if len(normalized["content"]) > len(previous["content"]):
                by_id[normalized["id"]] = normalized
            elif len(normalized["content"]) == len(previous["content"]) and normalized["content"] > previous["content"]:
                by_id[normalized["id"]] = normalized
    return sorted(by_id.values(), key=lambda item: (item["created_at"], item["id"]))


def _normalize_chat_brainstorm_trace(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    created_at = raw.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    return {**raw, "created_at": created_at.strip()}


def _merge_chat_brainstorm(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge v2 chat state by immutable message id, never by replacing its array."""
    by_id = {
        item["id"]: item
        for item in _normalize_chat_brainstorm_messages(existing.get("messages"))
    }
    for item in _normalize_chat_brainstorm_messages(incoming.get("messages")):
        previous = by_id.get(item["id"])
        if previous is None:
            by_id[item["id"]] = item
            continue
        if item["created_at"] > previous["created_at"]:
            by_id[item["id"]] = item
        elif item["created_at"] == previous["created_at"]:
            if len(item["content"]) > len(previous["content"]):
                by_id[item["id"]] = item
            elif len(item["content"]) == len(previous["content"]) and item["content"] > previous["content"]:
                by_id[item["id"]] = item

    existing_trace = _normalize_chat_brainstorm_trace(existing.get("last_context_trace"))
    incoming_trace = _normalize_chat_brainstorm_trace(incoming.get("last_context_trace"))
    if incoming_trace and (not existing_trace or incoming_trace["created_at"] > existing_trace["created_at"]):
        trace = incoming_trace
    else:
        trace = existing_trace

    messages = sorted(by_id.values(), key=lambda item: (item["created_at"], item["id"]))
    timestamps = [
        value
        for value in (
            existing.get("updated_at"),
            incoming.get("updated_at"),
            *(item["created_at"] for item in messages),
            existing_trace.get("created_at") if existing_trace else None,
            incoming_trace.get("created_at") if incoming_trace else None,
        )
        if isinstance(value, str) and value.strip()
    ]
    merged: dict[str, Any] = {
        "schema_version": 2,
        "messages": messages,
        "updated_at": max(timestamps) if timestamps else "",
    }
    if trace:
        merged["last_context_trace"] = trace
    return merged


def _merge_workflow_context_patch(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_copy = dict(existing)
    incoming_copy = dict(incoming)
    existing_chat = existing_copy.get("chat_brainstorm")
    incoming_chat = incoming_copy.get("chat_brainstorm")
    if isinstance(existing_chat, dict) or isinstance(incoming_chat, dict):
        existing_copy["chat_brainstorm"] = _merge_chat_brainstorm(
            existing_chat if isinstance(existing_chat, dict) else {},
            incoming_chat if isinstance(incoming_chat, dict) else {},
        )
        incoming_copy.pop("chat_brainstorm", None)
    merged = _deep_merge_dict(existing_copy, incoming_copy)
    for replace_key in ("manual_edit_context",):
        if replace_key in incoming and isinstance(incoming.get(replace_key), dict):
            merged[replace_key] = incoming[replace_key]
    return _sanitize_workflow_context_authority_flags(merged)


def _merge_episode_memory_cards(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {
        int(item.get("episode_no") or 0): item
        for item in _normalize_episode_memory_cards(existing)
        if int(item.get("episode_no") or 0) > 0
    }
    for item in _normalize_episode_memory_cards(incoming):
        merged[int(item["episode_no"])] = item
    return [merged[key] for key in sorted(merged.keys())]


def _calculate_diff(old_content: str, new_content: str) -> dict:
    """计算文本diff"""
    import difflib

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    sm = difflib.SequenceMatcher(None, old_lines, new_lines)

    added_chars = 0
    deleted_chars = 0
    added_lines = 0
    deleted_lines = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'insert':
            added_chars += sum(len(l) for l in new_lines[j1:j2])
            added_lines += j2 - j1
        elif tag == 'delete':
            deleted_chars += sum(len(l) for l in old_lines[i1:i2])
            deleted_lines += i2 - i1
        elif tag == 'replace':
            added_chars += sum(len(l) for l in new_lines[j1:j2])
            deleted_chars += sum(len(l) for l in old_lines[i1:i2])
            added_lines += j2 - j1
            deleted_lines += i2 - i1

    return {
        "added_chars": added_chars,
        "deleted_chars": deleted_chars,
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "net_change": added_chars - deleted_chars
    }


def _calculate_contribution_score(diff_stats: dict, editor_type: str) -> float:
    """计算贡献分"""
    weights = {
        "human": 1.0,
        "ai": 0.3,
        "skill_writer": 0.4,
        "skill_reviewer": 0.5
    }

    base_score = (
        diff_stats.get("added_chars", 0) * 0.5 +
        diff_stats.get("deleted_chars", 0) * 0.3
    )

    return base_score * weights.get(editor_type, 1.0)


def _get_next_version_code(db: Session, project_id: str, episode_number: int, scene_number: int = 0) -> str:
    """获取下一个版本号"""
    latest = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == scene_number
    ).order_by(desc(ContentVersion.version_code)).first()

    if not latest:
        return "v001"

    try:
        num = int(latest.version_code[1:])
        return f"v{num + 1:03d}"
    except:
        return "v001"


def _get_next_checkpoint_code(db: Session, project_id: str) -> str:
    """获取下一个断点编号"""
    latest = db.query(Checkpoint).filter(
        Checkpoint.project_id == project_id
    ).order_by(desc(Checkpoint.checkpoint_code)).first()

    if not latest:
        return "cp001"

    try:
        num = int(latest.checkpoint_code[2:])
        return f"cp{num + 1:03d}"
    except:
        return "cp001"


def _update_contribution_ledger(
    db: Session,
    project_id: str,
    editor_id: str,
    editor_name: str,
    editor_type: str,
    diff_stats: dict,
    contribution_score: float,
    version_id: str,
    episode_number: int,
    auto_commit: bool = True,
):
    """更新贡献账本"""
    ledger = db.query(ContributionLedger).filter(
        ContributionLedger.project_id == project_id,
        ContributionLedger.user_id == editor_id
    ).first()

    if not ledger:
        ledger = ContributionLedger(
            project_id=project_id,
            user_id=editor_id,
            user_name=editor_name
        )
        db.add(ledger)

    # 兼容历史空值记录，避免首次保存 AI 内容时在自增处崩溃。
    ledger.total_edits = int(ledger.total_edits or 0)
    ledger.words_added = int(ledger.words_added or 0)
    ledger.words_deleted = int(ledger.words_deleted or 0)
    ledger.ai_generations_accepted = int(ledger.ai_generations_accepted or 0)
    ledger.ai_generations_modified = int(ledger.ai_generations_modified or 0)
    ledger.base_score = float(ledger.base_score or 0)
    ledger.ai_collaboration_bonus = float(ledger.ai_collaboration_bonus or 0)
    ledger.final_score = float(ledger.final_score or 0)

    # 更新基础统计
    ledger.total_edits += 1
    ledger.words_added += diff_stats.get("added_chars", 0)
    ledger.words_deleted += diff_stats.get("deleted_chars", 0)

    # 更新AI协作统计
    if editor_type == "ai":
        ledger.ai_generations_accepted += 1

    # 更新基础分
    ledger.base_score += contribution_score

    # 计算AI协作奖励（接受AI内容后人工修改）
    if editor_type == "human" and ledger.ai_generations_accepted > 0:
        ledger.ai_collaboration_bonus = min(
            ledger.ai_generations_modified * 5,
            ledger.base_score * 0.2  # 最高为基础分的20%
        )

    ledger.final_score = ledger.base_score + ledger.ai_collaboration_bonus
    ledger.add_version_id(version_id)

    if auto_commit:
        db.commit()
    else:
        db.flush()
