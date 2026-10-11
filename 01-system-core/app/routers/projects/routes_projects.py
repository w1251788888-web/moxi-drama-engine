"""项目 CRUD + 模型提供商（从 projects_v2.py 抽出）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
import hashlib
from uuid import UUID
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_admin, verify_project_actor
from app.database import get_db
from app.models.collaboration import ProjectInvite, ProjectMember, ProjectPermission
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
    _filter_projects_for_actor,
    _get_project_for_actor_or_404,
    _get_next_checkpoint_code,
    _get_next_version_code,
    _get_workspace_path,
    _init_workspace,
    _load_workspace_project_data,
    _merge_episode_memory_cards,
    _normalize_canon_packet,
    _normalize_episode_memory_cards,
    _normalize_project_config_payload,
    _normalize_state_cards_payload,
    _project_owner_key_from_actor,
    _normalize_workflow_context,
    _recommend_classification_tracks,
    _remove_workspace_index_entry,
    _safe_rmtree,
    _stamp_project_owner_from_actor,
    _sync_workspace_project_index,
    _workspace_owner_scope_from_actor,
    _update_contribution_ledger,
    _workspace_delete_roots,
    _write_workspace_project_data,
)
from app.services.evidence_event_service import record_evidence_event
from app.services.project_access_policy import require_project_permission
from app.services.project_invite_service import ensure_owner_member

router = APIRouter()  # 无 prefix；由 projects_v2.py 的主 router 加 prefix 聚合


def _coerce_legacy_direct_actor(actor: object, legacy_admin_flag: bool | None) -> ProjectAccessActor:
    """兼容旧测试/脚本直接调用路由函数时传入的 `_` 管理员标记。"""
    if isinstance(actor, ProjectAccessActor):
        return actor
    if legacy_admin_flag is True:
        return ProjectAccessActor(actor_type="admin")
    raise HTTPException(status_code=403, detail="请先登录管理员后台或前台用户账号")


def _promote_request_total_episodes_to_confirmed(
    config: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """把本次请求里用户明确提交的旧集数字段升级为已确认集数。"""
    payload = dict(config or {})
    if (
        payload.get("confirmed_total_episodes") is None
        and payload.get("total_episodes") is not None
    ):
        payload["confirmed_total_episodes"] = payload["total_episodes"]
        payload["episode_count_status"] = "confirmed"
        payload["episode_count_confirmation_source"] = (
            payload.get("episode_count_confirmation_source") or source
        )
        payload["episode_count_confirmed_at"] = (
            payload.get("episode_count_confirmed_at") or datetime.now().isoformat()
        )
    return payload


@router.post("/", response_model=ProjectResponse, summary="创建项目")
async def create_project(
    req: ProjectCreateRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """创建新项目，初始化工作区"""
    # 项目名只在同一账号 / 同一密钥下唯一；不同用户可创建同名项目。
    owner_key = _project_owner_key_from_actor(actor)
    existing = (
        db.query(ProjectV2)
        .filter(ProjectV2.name == req.name, ProjectV2.created_by == owner_key)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="当前账号下项目名称已存在")

    # 初始化工作区
    config_dict = _normalize_project_config_payload(
        _promote_request_total_episodes_to_confirmed(
            req.config.model_dump(),
            source="project_create_request",
        ),
        project_type=req.project_type,
        audience_axis=req.audience_axis,
        genre_main=req.genre_main,
        genre_sub=req.genre_sub,
    )
    workspace_path = _init_workspace(
        req.name,
        config_dict,
        owner_scope=_workspace_owner_scope_from_actor(actor),
    )

    # 创建数据库记录
    project = ProjectV2(
        name=req.name,
        description=req.description,
        project_type=req.project_type,
        audience_axis=req.audience_axis,
        genre_main=req.genre_main,
        genre_sub=req.genre_sub,
        creation_mode="collab" if req.creation_mode == "collab" else "solo",
        rights_capture_enabled=True,
        total_episodes=int(config_dict.get("confirmed_total_episodes") or 0),
        workspace_path=str(workspace_path)
    )
    _stamp_project_owner_from_actor(project, actor)
    project.set_config(config_dict)

    db.add(project)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="当前账号下项目名称已存在") from exc
    db.refresh(project)
    ensure_owner_member(db, project_id=project.id, actor=actor, legal_identity="sole_creator" if project.creation_mode == "solo" else "showrunner")
    record_evidence_event(
        db,
        project_id=project.id,
        actor=actor,
        event_type="project_created",
        target_type="project",
        target_id=project.id,
        summary=f"创建{'多人协作' if project.creation_mode == 'collab' else '独立完成'}项目",
        metadata={"creation_mode": project.creation_mode, "rights_capture_enabled": True},
        commit=True,
    )
    _sync_workspace_project_index(project)

    return _build_project_response(project, db=db)


@router.get("/", summary="列出所有项目")
async def list_projects(
    limit: int = 50,
    offset: int = 0,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """列出项目，按更新时间倒序"""
    query = _filter_projects_for_actor(db.query(ProjectV2), actor)
    projects = query.order_by(
        desc(ProjectV2.updated_at)
    ).offset(offset).limit(limit).all()

    return [_build_project_response(p, db=db) for p in projects]


@router.get("/model-providers", summary="列出模型提供商")
async def list_model_providers(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """列出所有模型提供商"""
    providers = db.query(ModelProvider).all()

    return [{
        "id": p.id,
        "name": p.name,
        "provider_type": p.provider_type,
        "base_url": p.base_url,
        "default_model": p.default_model,
        "models": p.get_models(),
        "is_active": p.is_active,
        "is_default": p.is_default,
        "rate_limit_rpm": p.rate_limit_rpm,
        "rate_limit_tpm": p.rate_limit_tpm,
        "input_cost_cny_per_1k": float(p.input_cost_cny_per_1k or 0),
        "output_cost_cny_per_1k": float(p.output_cost_cny_per_1k or 0),
        "billing_multiplier": float(p.billing_multiplier or 0),
        "minimum_actual_cost_cny": float(p.minimum_actual_cost_cny or 0),
    } for p in providers]


@router.get("/{project_id}", response_model=ProjectResponse, summary="获取项目详情")
async def get_project(
    project_id: UUID,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取项目详情"""
    project = _get_project_for_actor_or_404(db, str(project_id), actor)
    require_project_permission(db, project, actor, "view")

    return _build_project_response(project, db=db)


@router.put("/{project_id}", response_model=ProjectResponse, summary="更新项目配置")
async def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
    _: bool | None = None,
):
    """更新项目基础信息与规则配置"""
    actor = _coerce_legacy_direct_actor(actor, _)
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "manage")

    if req.description is not None:
        project.description = req.description
    if req.project_type is not None:
        project.project_type = req.project_type
    if req.audience_axis is not None:
        project.audience_axis = req.audience_axis
    if req.genre_main is not None:
        project.genre_main = req.genre_main
    if req.genre_sub is not None:
        project.genre_sub = req.genre_sub
    if req.creation_mode is not None:
        project.creation_mode = "collab" if req.creation_mode == "collab" else "solo"

    if req.config is not None:
        current_config = _normalize_project_config_payload(
            project.get_config(),
            project_type=project.project_type,
            audience_axis=project.audience_axis,
            genre_main=project.genre_main,
            genre_sub=project.genre_sub,
        )
        incoming_config = _promote_request_total_episodes_to_confirmed(
            req.config.model_dump(exclude_none=True),
            source="project_settings_update",
        )
        merged_config = _normalize_project_config_payload(
            {**current_config, **incoming_config},
            project_type=project.project_type,
            audience_axis=project.audience_axis,
            genre_main=project.genre_main,
            genre_sub=project.genre_sub,
        )
        project.total_episodes = int(merged_config.get("confirmed_total_episodes") or 0)
        project.set_config(merged_config)
    else:
        refreshed_config = _normalize_project_config_payload(
            project.get_config(),
            project_type=project.project_type,
            audience_axis=project.audience_axis,
            genre_main=project.genre_main,
            genre_sub=project.genre_sub,
        )
        project.total_episodes = int(refreshed_config.get("confirmed_total_episodes") or 0)
        project.set_config(refreshed_config)

    db.commit()
    db.refresh(project)
    _sync_workspace_project_index(project)
    return _build_project_response(project, db=db)

@router.delete("/{project_id}", summary="删除项目")
async def delete_project(
    project_id: str,
    delete_workspace: bool = False,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
    _: bool | None = None,
):
    """删除项目，可选同时删除工作区文件"""
    actor = _coerce_legacy_direct_actor(actor, _)
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "manage")

    # 删除工作区
    if delete_workspace and project.workspace_path:
        try:
            _safe_rmtree(project.workspace_path, allowed_roots=_workspace_delete_roots())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    _remove_workspace_index_entry(
        workspace=project.workspace_path,
        project_name=project.name,
        project_id=project.id,
    )

    # 删除数据库记录
    episode_ids = [
        row[0]
        for row in db.query(Episode.id).filter(Episode.project_id == project_id).all()
    ]
    if episode_ids:
        db.query(Scene).filter(Scene.episode_id.in_(episode_ids)).delete(synchronize_session=False)
    db.query(Episode).filter(Episode.project_id == project_id).delete(synchronize_session=False)
    db.query(ContentVersion).filter(ContentVersion.project_id == project_id).delete()
    db.query(ContributionLedger).filter(ContributionLedger.project_id == project_id).delete()
    db.query(Checkpoint).filter(Checkpoint.project_id == project_id).delete()
    db.query(GenerationJob).filter(GenerationJob.project_id == project_id).delete()
    db.query(ProjectPermission).filter(ProjectPermission.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectInvite).filter(ProjectInvite.project_id == project_id).delete(synchronize_session=False)

    db.delete(project)
    db.commit()

    return {"message": "项目已删除"}


# ============================================================
# 模型提供商：增 / 设默认
# ============================================================

@router.post("/model-providers", summary="添加模型提供商")
async def add_model_provider(
    req: ModelProviderRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """添加新的模型提供商"""
    provider = ModelProvider(
        name=req.name,
        provider_type=req.provider_type,
        base_url=req.base_url,
        api_key=req.api_key,  # TODO: 加密存储
        default_model=req.default_model,
        rate_limit_rpm=req.rate_limit_rpm,
        rate_limit_tpm=req.rate_limit_tpm,
        input_cost_cny_per_1k=req.input_cost_cny_per_1k,
        output_cost_cny_per_1k=req.output_cost_cny_per_1k,
        billing_multiplier=req.billing_multiplier,
        minimum_actual_cost_cny=req.minimum_actual_cost_cny,
    )
    provider.set_models(req.models)

    db.add(provider)
    db.commit()
    db.refresh(provider)

    return {"id": provider.id, "message": "提供商已添加"}


@router.post("/model-providers/{provider_id}/set-default", summary="设为默认提供商")
async def set_default_provider(
    provider_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """设置默认模型提供商"""
    # 清除其他默认
    db.query(ModelProvider).update({ModelProvider.is_default: False})

    provider = db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="提供商不存在")

    provider.is_default = True
    db.commit()

    return {"message": "默认提供商已更新"}
