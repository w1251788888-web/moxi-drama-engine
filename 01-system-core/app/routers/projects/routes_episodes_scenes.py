"""集 / 场 / 版本 / 回滚（从 projects_v2.py 抽出）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
import difflib
import hashlib
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.models.project_v2 import (
    Checkpoint,
    ContentVersion,
    ContributionLedger,
    Episode,
    GenerationJob,
    ModelProvider,
    ProjectV2,
    Scene,
)
from app.models.collaboration import ProjectPermission

from app.routers.projects._schemas import (
    CharacterStoreRequest,
    CharacterStoreResponse,
    ContentSaveRequest,
    ContributionResponse,
    DiffResponse,
    EpisodeCreateRequest,
    EpisodeResponse,
    GenerationRequest,
    GenerationResponse,
    GenerationResult,
    ModelProviderRequest,
    ProjectConfig,
    ProjectConfigPatch,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    ProjectWorkflowContextRequest,
    ProjectWorkflowContextResponse,
    SceneCreateRequest,
    SceneResponse,
    StoryStateCardStoreRequest,
    StoryStateCardStoreResponse,
    VersionResponse,
)
from app.routers.projects._helpers import (
    REPO_ROOT,
    WORKSPACE_ROOT,
    _build_project_response,
    _calculate_contribution_score,
    _calculate_diff,
    _default_workflow_context,
    _deep_merge_dict,
    _derive_word_count_range,
    _checkpoint_file_path,
    _calculate_episode_writing_progress,
    _calculate_project_writing_progress,
    _episode_dir_path,
    _get_project_for_actor_or_404,
    _get_next_checkpoint_code,
    _get_next_version_code,
    _get_workspace_path,
    _init_workspace,
    _load_workspace_project_data,
    _merge_episode_memory_cards,
    _normalize_canon_packet,
    _normalize_project_config_payload,
    _normalize_state_cards_payload,
    _recommend_classification_tracks,
    _scene_version_file_path,
    _safe_rmtree,
    _sync_workspace_project_index,
    _update_contribution_ledger,
    _update_workspace_project_data_atomically,
    _workspace_delete_roots,
)
from app.services.compliance_scan_service import mark_episode_compliance_stale
from app.services.c19_178_safe_label_gate import C19178GateBlocked, assert_c19_178_runtime_gate
from app.services.evidence_event_service import record_evidence_event
from app.services.lightweight_learning_service import LightweightLearningService
from app.services.project_access_policy import get_active_member, is_project_owner_or_admin, require_project_permission
from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

router = APIRouter()  # 无 prefix；由 projects_v2.py 的主 router 加 prefix 聚合

C19_178_GENERATED_EDITOR_TYPES = {"ai", "skill_writer", "skill_reviewer"}


def _has_explicit_episode_close_edit_permission(
    db: Session,
    project: ProjectV2,
    actor: ProjectAccessActor,
    episode_number: int,
) -> bool:
    if is_project_owner_or_admin(project, actor):
        return True
    member = get_active_member(db, project.id, actor)
    if member is None:
        return False
    if member.role in {"showrunner", "owner"}:
        return True
    rows = db.query(ProjectPermission).filter(
        ProjectPermission.project_id == project.id,
        ProjectPermission.member_id == member.id,
    ).all()
    has_edit_permission = False
    has_approval_permission = False
    for row in rows:
        if row.scope_type == "project":
            scope_matches = True
        elif row.scope_type == "episode" and (not row.scope_id or row.scope_id == str(episode_number)):
            scope_matches = True
        else:
            scope_matches = False
        if not scope_matches:
            continue
        if row.permission in {"edit", "write", "manage", "manage_content"}:
            has_edit_permission = True
        if row.permission in {"approve", "manage", "manage_content", "manage_legal"}:
            has_approval_permission = True
    return has_edit_permission and has_approval_permission


def _requires_c19_178_materialization_gate(req: ContentSaveRequest) -> bool:
    editor_type = str(req.editor_type or "").strip().lower()
    return bool(req.c19_178_materialization) or editor_type in C19_178_GENERATED_EDITOR_TYPES


def _assert_c19_178_materialization_gate(db: Session, project: ProjectV2) -> None:
    try:
        assert_c19_178_runtime_gate(db, project=project, target_path="materialization")
    except C19178GateBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.decision.reason_code) from exc


def _build_episode_response(db: Session, episode: Episode) -> EpisodeResponse:
    progress = _calculate_episode_writing_progress(db, episode)
    return EpisodeResponse(
        id=episode.id,
        episode_number=episode.episode_number,
        title=episode.title,
        summary=episode.summary,
        status=progress["status"],
        total_scenes=progress["total_scenes"],
        completed_scenes=progress["completed_scenes"],
        quality_score=episode.quality_score,
        current_version=episode.current_version,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
    )


def _build_scene_response(scene: Scene) -> SceneResponse:
    content = scene.content or ""
    return SceneResponse(
        id=scene.id,
        scene_number=scene.scene_number,
        scene_code=scene.scene_code,
        time=scene.time,
        location_type=scene.location_type,
        location_name=scene.location_name,
        content=content,
        content_preview=content[:200] + "..." if len(content) > 200 else content,
        word_count=scene.word_count,
        status=scene.status,
        primary_author=scene.primary_author,
        ai_generated=scene.ai_generated,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )

@router.post("/{project_id}/episodes", response_model=EpisodeResponse, summary="创建集")
async def create_episode(
    project_id: str,
    req: EpisodeCreateRequest,
    episode_number: Optional[int] = None,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """创建新集，如不指定集数，自动递增"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "edit")

    # 确定集数
    if episode_number is None:
        latest = db.query(Episode).filter(
            Episode.project_id == project_id
        ).order_by(desc(Episode.episode_number)).first()
        episode_number = (latest.episode_number + 1) if latest else 1

    # 检查是否已存在
    existing = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"第{episode_number}集已存在")

    # 创建工作区目录
    try:
        episode_dir = _episode_dir_path(project, episode_number, create=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    (episode_dir / "scenes").mkdir(exist_ok=True)

    episode = Episode(
        project_id=project_id,
        episode_number=episode_number,
        title=req.title,
        summary=req.summary,
        status=req.status
    )

    db.add(episode)
    db.commit()
    db.refresh(episode)

    return _build_episode_response(db, episode)


@router.get("/{project_id}/episodes", summary="列出所有集")
async def list_episodes(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """列出项目的所有集"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    episodes = db.query(Episode).filter(
        Episode.project_id == project_id
    ).order_by(Episode.episode_number).all()

    return [_build_episode_response(db, e) for e in episodes]


@router.get("/{project_id}/episodes/{episode_number}", response_model=EpisodeResponse, summary="获取集详情")
async def get_episode(
    project_id: str,
    episode_number: int,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取集详情"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view", scope_type="episode", scope_id=str(episode_number))
    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()

    if not episode:
        raise HTTPException(status_code=404, detail="集不存在")

    return _build_episode_response(db, episode)


@router.delete("/{project_id}/episodes/{episode_number}", summary="删除单集")
async def delete_episode(
    project_id: str,
    episode_number: int,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """删除单集及其场景、版本、生成任务和工作区文件。"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "manage", scope_type="episode", scope_id=str(episode_number))
    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()
    if not episode:
        raise HTTPException(status_code=404, detail="集不存在")

    scene_count = db.query(Scene).filter(Scene.episode_id == episode.id).count()
    db.query(Scene).filter(Scene.episode_id == episode.id).delete(synchronize_session=False)
    db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
    ).delete(synchronize_session=False)
    db.query(Checkpoint).filter(
        Checkpoint.project_id == project_id,
        Checkpoint.episode_number == episode_number,
    ).delete(synchronize_session=False)
    db.query(GenerationJob).filter(
        GenerationJob.project_id == project_id,
        GenerationJob.episode_number == episode_number,
    ).delete(synchronize_session=False)
    db.delete(episode)
    db.flush()

    try:
        episode_dir = _episode_dir_path(project, episode_number, create=False)
        _safe_rmtree(episode_dir, allowed_roots=_workspace_delete_roots())
    except Exception:
        # 数据库是主事实源；文件夹清理失败不阻断删除。
        pass

    def update_current_project_data(project_data: dict[str, Any]) -> dict[str, Any]:
        workflow_context = project_data.get("workflow_context")
        if isinstance(workflow_context, dict):
            updated_workflow_context = dict(workflow_context)
            progress = updated_workflow_context.get("script_segment_progress")
            if isinstance(progress, dict):
                updated_progress = dict(progress)
                updated_progress.pop(str(episode_number), None)
                updated_progress.pop(episode_number, None)
                updated_workflow_context["script_segment_progress"] = updated_progress
            project_data["workflow_context"] = updated_workflow_context

        memory_cards = project_data.get("episode_memory_cards")
        if isinstance(memory_cards, list):
            def is_deleted_episode_card(card: Any) -> bool:
                if not isinstance(card, dict):
                    return False
                try:
                    return int(card.get("episode_no") or card.get("ep") or 0) == int(episode_number)
                except (TypeError, ValueError):
                    return False

            project_data["episode_memory_cards"] = [card for card in memory_cards if not is_deleted_episode_card(card)]
        project_data["updated_at"] = datetime.now().isoformat()
        return project_data

    _update_workspace_project_data_atomically(project, update_current_project_data)

    remaining = db.query(Episode).filter(Episode.project_id == project_id).order_by(Episode.episode_number).all()
    project.current_episode = remaining[0].episode_number if remaining else 1
    project.updated_at = datetime.now()
    _calculate_project_writing_progress(db, project, persist=True)
    db.commit()
    _sync_workspace_project_index(project)
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type="episode_deleted",
        target_type="episode",
        target_id=str(episode_number),
        summary=f"删除第{episode_number}集",
        metadata={"episode_number": episode_number, "deleted_scenes": scene_count},
        commit=True,
    )
    return {"ok": True, "episode_number": episode_number, "deleted_scenes": scene_count}


# ============================================================
# 场景管理API
# ============================================================

@router.post("/{project_id}/episodes/{episode_number}/scenes", response_model=SceneResponse, summary="创建场景")
async def create_scene(
    project_id: str,
    episode_number: int,
    req: SceneCreateRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """创建新场景"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "edit", scope_type="episode", scope_id=str(episode_number))
    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()

    if not episode:
        raise HTTPException(status_code=404, detail="集不存在")
    if episode.status == "completed":
        require_project_permission(db, project, actor, "approve", scope_type="episode", scope_id=str(episode_number))

    for _attempt in range(5):
        latest = db.query(Scene).filter(
            Scene.episode_id == episode.id
        ).order_by(desc(Scene.scene_number)).first()
        scene_number = (latest.scene_number + 1) if latest else 1
        scene_code = f"{episode_number}-{scene_number}"

        scene = Scene(
            episode_id=episode.id,
            scene_number=scene_number,
            scene_code=scene_code,
            time=req.time,
            location_type=req.location_type,
            location_name=req.location_name,
            content=req.content,
            word_count=len(req.content)
        )

        db.add(scene)
        episode.total_scenes += 1

        try:
            db.commit()
            db.refresh(scene)
            return _build_scene_response(scene)
        except IntegrityError:
            db.rollback()
            episode = db.query(Episode).filter(
                Episode.project_id == project_id,
                Episode.episode_number == episode_number
            ).first()
            if not episode:
                raise HTTPException(status_code=404, detail="集不存在")

    raise HTTPException(status_code=409, detail="场景编号冲突，请重试")


@router.get("/{project_id}/scenes", summary="按集批量列出场景")
async def list_scenes_batch(
    project_id: str,
    episode_numbers: str = Query("", description="逗号分隔的集数，最多 20 个"),
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    """批量读取多集场景，用于前端后台预热，避免大项目打开时串行 N 次请求。"""
    requested: list[int] = []
    seen: set[int] = set()
    for raw in str(episode_numbers or "").split(","):
        try:
            ep_num = int(raw.strip())
        except Exception:
            continue
        if ep_num <= 0 or ep_num in seen:
            continue
        requested.append(ep_num)
        seen.add(ep_num)
        if len(requested) >= 20:
            break

    if not requested:
        return {}

    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")

    rows = (
        db.query(Episode.episode_number, Scene)
        .join(Scene, Scene.episode_id == Episode.id)
        .filter(
            Episode.project_id == project_id,
            Episode.episode_number.in_(requested),
        )
        .order_by(Episode.episode_number, Scene.scene_number)
        .all()
    )

    result: dict[str, list[SceneResponse]] = {str(ep_num): [] for ep_num in requested}
    for episode_number, scene in rows:
        result.setdefault(str(episode_number), []).append(_build_scene_response(scene))
    return result


@router.get("/{project_id}/episodes/{episode_number}/scenes", summary="列出场景")
async def list_scenes(
    project_id: str,
    episode_number: int,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """列出集的所有场景"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view", scope_type="episode", scope_id=str(episode_number))
    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()

    if not episode:
        raise HTTPException(status_code=404, detail="集不存在")

    scenes = db.query(Scene).filter(
        Scene.episode_id == episode.id
    ).order_by(Scene.scene_number).all()

    return [_build_scene_response(s) for s in scenes]


@router.post("/{project_id}/episodes/{episode_number}/scenes/{scene_number}/save",
             response_model=VersionResponse, summary="保存场景内容")
async def save_scene_content(
    project_id: str,
    episode_number: int,
    scene_number: int,
    req: ContentSaveRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """保存场景内容，自动创建版本记录"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "edit", scope_type="episode", scope_id=str(episode_number))

    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()
    if not episode:
        raise HTTPException(status_code=404, detail="集不存在")
    if episode.status == "completed":
        require_project_permission(db, project, actor, "approve", scope_type="episode", scope_id=str(episode_number))

    scene = db.query(Scene).filter(
        Scene.episode_id == episode.id,
        Scene.scene_number == scene_number
    ).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    if _requires_c19_178_materialization_gate(req):
        _assert_c19_178_materialization_gate(db, project)

    # 获取旧内容用于计算diff
    old_content = scene.content or ""

    # 计算diff
    diff_stats = _calculate_diff(old_content, req.content)

    # 计算贡献分
    contribution_score = _calculate_contribution_score(diff_stats, req.editor_type)

    # 生成版本号
    version_code = _get_next_version_code(db, project_id, episode_number, scene_number)

    # 保存内容到文件
    try:
        scene_file = _scene_version_file_path(
            project,
            episode_number=episode_number,
            scene_number=scene_number,
            version_code=version_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    scene_file_written = False
    checkpoint_file: Path | None = None
    checkpoint_file_written = False
    try:
        scene_file.write_text(req.content, encoding="utf-8")
        scene_file_written = True

        # 创建版本记录
        version = ContentVersion(
            project_id=project_id,
            episode_number=episode_number,
            scene_number=scene_number,
            version_code=version_code,
            parent_version=episode.current_version,
            editor_type=req.editor_type,
            editor_id=req.editor_id,
            editor_name=req.editor_name,
            content_path=str(scene_file),
            content_hash=hashlib.sha256(req.content.encode()).hexdigest(),
            diff_stats=json.dumps(diff_stats, ensure_ascii=False),
            contribution_score=contribution_score,
            change_note=req.change_note
        )

        db.add(version)

        # 更新场景
        scene.content = req.content
        scene.word_count = len(req.content)
        scene.status = "completed" if req.editor_type == "human" else "draft"
        scene.primary_author = req.editor_id if req.editor_type == "human" else scene.primary_author
        scene.ai_generated = req.editor_type in ["ai", "skill_writer"]
        scene.ai_modified = req.editor_type == "human" and scene.ai_generated

        # 更新集的当前版本
        episode.current_version = version_code
        episode.updated_at = datetime.now()
        _calculate_project_writing_progress(db, project, persist=True)

        # 更新项目进度
        project.updated_at = datetime.now()
        db.flush()

        # 更新贡献账本、合规状态、证据事件，和正文版本一起落库。
        _update_contribution_ledger(
            db, project_id, req.editor_id, req.editor_name, req.editor_type,
            diff_stats, contribution_score, version.id, episode_number,
            auto_commit=False,
        )
        mark_episode_compliance_stale(db, project_id, episode_number)
        record_evidence_event(
            db,
            project_id=project_id,
            actor=actor,
            event_type="script_content_saved",
            target_type="scene",
            target_id=f"{episode_number}:{scene_number}",
            content_version_id=version.id,
            content_hash=version.content_hash,
            summary=req.change_note or f"保存第{episode_number}集第{scene_number}场",
            metadata={
                "episode_number": episode_number,
                "scene_number": scene_number,
                "editor_type": req.editor_type,
                "diff_stats": diff_stats,
            },
            commit=False,
        )
        manual_evidence_id = ""
        manual_evidence = req.manual_edit_evidence if isinstance(req.manual_edit_evidence, dict) else {}
        if req.editor_type == "human" and manual_evidence:
            manual_evidence_id = LightweightLearningService(db).record_manual_edit_evidence(
                project_id=project_id,
                episode_no=episode_number,
                scene_no=scene_number,
                saved_content=req.content,
                evidence={
                    **manual_evidence,
                    "change_note": req.change_note,
                },
                commit=False,
            )
            if manual_evidence_id:
                record_evidence_event(
                    db,
                    project_id=project_id,
                    actor=actor,
                    event_type="user_edit_candidate_evidence_recorded",
                    target_type="scene",
                    target_id=f"{episode_number}:{scene_number}",
                    content_version_id=version.id,
                    content_hash=version.content_hash,
                    summary="用户改稿已进入候选证据池，等待人工复核。",
                    metadata={
                        "episode_number": episode_number,
                        "scene_number": scene_number,
                        "manual_evidence_id": manual_evidence_id,
                        "review_policy": "candidate_only_needs_human_review",
                    },
                    commit=False,
                )

        # 创建检查点（如果请求）
        if req.create_checkpoint:
            checkpoint_code = _get_next_checkpoint_code(db, project_id)
            try:
                checkpoint_file = _checkpoint_file_path(project, checkpoint_code)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            checkpoint_data = {
                "project_id": project_id,
                "episode_number": episode_number,
                "scene_number": scene_number,
                "version_id": version.id,
                "content_path": str(scene_file),
                "editor": req.editor_name,
                "note": req.change_note or f"保存场景{scene_number}",
                "created_at": datetime.now().isoformat()
            }
            checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")
            checkpoint_file_written = True

            checkpoint = Checkpoint(
                project_id=project_id,
                checkpoint_code=checkpoint_code,
                episode_number=episode_number,
                scene_number=scene_number,
                data_path=str(checkpoint_file),
                note=req.change_note or f"保存场景{scene_number}",
                created_by=req.editor_id
            )
            db.add(checkpoint)

        db.commit()
        db.refresh(version)
    except HTTPException:
        db.rollback()
        if checkpoint_file_written and checkpoint_file:
            checkpoint_file.unlink(missing_ok=True)
        if scene_file_written:
            scene_file.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        if checkpoint_file_written and checkpoint_file:
            checkpoint_file.unlink(missing_ok=True)
        if scene_file_written:
            scene_file.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"保存场景失败: {exc}") from exc

    _sync_workspace_project_index(project)

    return VersionResponse(
        id=version.id,
        version_code=version.version_code,
        parent_version=version.parent_version,
        editor_type=version.editor_type,
        editor_name=version.editor_name,
        diff_stats=diff_stats,
        contribution_score=version.contribution_score,
        change_note=version.change_note,
        created_at=version.created_at
    )


@router.post(
    "/{project_id}/episodes/{episode_number}/draft-completion/close",
    summary="完成本集草稿保存收口",
)
async def close_episode_draft_completion(
    project_id: str,
    episode_number: int,
    scene_number: int = Query(1, ge=1),
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    """后端幂等裁决四段完成证据，只写草稿保存收口，不锁稿。"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    if not _has_explicit_episode_close_edit_permission(db, project, actor, episode_number):
        raise HTTPException(status_code=403, detail="完成本集草稿保存收口需要编辑和内容管理权限")
    return complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
        actor=actor,
    )


# ============================================================
# 版本与Diff API
# ============================================================

@router.get("/{project_id}/episodes/{episode_number}/scenes/{scene_number}/versions",
            summary="获取场景版本历史")
async def list_scene_versions(
    project_id: str,
    episode_number: int,
    scene_number: int,
    limit: int = 20,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取场景的所有版本"""
    _get_project_for_actor_or_404(db, project_id, actor)
    versions = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == scene_number
    ).order_by(desc(ContentVersion.created_at)).limit(limit).all()

    return [VersionResponse(
        id=v.id,
        version_code=v.version_code,
        parent_version=v.parent_version,
        editor_type=v.editor_type,
        editor_name=v.editor_name,
        diff_stats=v.get_diff_stats(),
        contribution_score=v.contribution_score,
        change_note=v.change_note,
        created_at=v.created_at
    ) for v in versions]


@router.get("/{project_id}/versions/{version_id}/diff", response_model=DiffResponse, summary="获取版本diff")
async def get_version_diff(
    project_id: str,
    version_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取指定版本与父版本的diff"""
    _get_project_for_actor_or_404(db, project_id, actor)
    version = db.query(ContentVersion).filter(
        ContentVersion.id == version_id,
        ContentVersion.project_id == project_id
    ).first()

    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    # 读取当前版本内容
    current_content = Path(version.content_path).read_text(encoding="utf-8") if Path(version.content_path).exists() else ""

    # 读取父版本内容
    old_content = ""
    if version.parent_version:
        parent = db.query(ContentVersion).filter(
            ContentVersion.project_id == project_id,
            ContentVersion.episode_number == version.episode_number,
            ContentVersion.scene_number == version.scene_number,
            ContentVersion.version_code == version.parent_version
        ).first()
        if parent and Path(parent.content_path).exists():
            old_content = Path(parent.content_path).read_text(encoding="utf-8")

    # 计算diff
    diff_stats = _calculate_diff(old_content, current_content)

    return DiffResponse(
        old_version=version.parent_version or "none",
        new_version=version.version_code,
        added_lines=[],  # 简化版，可扩展
        deleted_lines=[],
        modified_blocks=[],
        stats=diff_stats
    )


@router.post("/{project_id}/episodes/{episode_number}/scenes/{scene_number}/restore",
             response_model=SceneResponse, summary="恢复到指定版本")
async def restore_version(
    project_id: str,
    episode_number: int,
    scene_number: int,
    version_code: str,
    editor_id: str = "",
    editor_name: str = "",
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """恢复到指定版本，创建新版本记录"""
    project = _get_project_for_actor_or_404(db, project_id, actor)
    version = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == scene_number,
        ContentVersion.version_code == version_code
    ).first()

    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    restored_from_generated_version = str(version.editor_type or "").strip().lower() in C19_178_GENERATED_EDITOR_TYPES
    if restored_from_generated_version:
        _assert_c19_178_materialization_gate(db, project)

    # 读取版本内容（content_path 可能为空或文件已丢失）
    content_path_raw = version.content_path or ""
    if content_path_raw:
        try:
            cp = Path(content_path_raw)
            content = cp.read_text(encoding="utf-8") if cp.exists() else ""
        except Exception:
            content = ""
    else:
        content = ""

    # 创建保存请求
    save_req = ContentSaveRequest(
        content=content,
        editor_type="human",
        editor_id=editor_id,
        editor_name=editor_name or "系统",
        change_note=f"恢复到版本{version_code}",
        create_checkpoint=True,
        c19_178_materialization=restored_from_generated_version,
    )

    # 先走统一保存逻辑创建新版本（直接调用，跳过依赖注入）
    try:
        await save_scene_content(
            project_id, episode_number, scene_number, save_req, actor, db
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"恢复版本时保存失败：{exc}")

    # 再返回当前场景最新快照，保持与前端 SceneResponse 约定一致
    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number
    ).first()
    scene = db.query(Scene).filter(
        Scene.episode_id == episode.id,
        Scene.scene_number == scene_number
    ).first() if episode else None
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    return SceneResponse(
        id=scene.id,
        scene_number=scene.scene_number,
        scene_code=scene.scene_code,
        time=scene.time,
        location_type=scene.location_type,
        location_name=scene.location_name,
        content=scene.content or "",
        content_preview=scene.content[:200] + "..." if scene.content and len(scene.content) > 200 else (scene.content or ""),
        word_count=scene.word_count,
        status=scene.status,
        primary_author=scene.primary_author,
        ai_generated=scene.ai_generated,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
    )


# ============================================================
# 贡献度API
# ============================================================
