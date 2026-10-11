"""项目角色库 / 状态卡 / 工作流上下文 stores（从 projects_v2.py 抽出）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc
from pydantic import BaseModel, Field
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
    _get_project_for_actor_or_404,
    _get_next_checkpoint_code,
    _get_next_version_code,
    _get_workspace_path,
    _init_workspace,
    _load_workspace_project_data,
    _merge_episode_memory_cards,
    _merge_workflow_context_patch,
    _normalize_canon_packet,
    _normalize_episode_memory_cards,
    _normalize_project_config_payload,
    _normalize_state_cards_payload,
    _normalize_workflow_context,
    _normalize_workflow_context_patch,
    _recommend_classification_tracks,
    _sync_workspace_project_index,
    _update_contribution_ledger,
    _update_workspace_project_data_atomically,
)

router = APIRouter()  # 无 prefix；由 projects_v2.py 的主 router 加 prefix 聚合


def _sanitize_character_store_rows(rows: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
    """Drop obvious outline/prediction scaffolds before project characters are returned or saved."""
    if not isinstance(rows, list):
        return []

    import re

    from app.routers.projects.routes_generation import (
        _clean_outline_character_name,
        _outline_is_valid_character_name,
        _sanitize_outline_character_info,
    )

    def _is_valid_manual_character_name(name: str) -> bool:
        if _outline_is_valid_character_name(name):
            return True
        if not 2 <= len(name) <= 12:
            return False
        if not re.fullmatch(r"(?=.*[\u4e00-\u9fa5])[\u4e00-\u9fa5A-Za-z0-9·_]{2,12}", name):
            return False
        if re.search(
            r"角色|人物|关系|集纲|剧情|正文|原文|设定|模板|框架|旁观|真正|目标|站队|"
            r"被动|解释|主动|利益|发现|揭露|反派|配角|第[一二三四五六七八九十百\d]{1,4}(?:集|场)",
            name,
        ):
            return False
        return True

    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()
    text_fields = (
        "info",
        "background",
        "notes",
        "appearance",
        "personality",
        "motivation",
        "arc",
        "traits",
        "voice_style",
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _clean_outline_character_name(str(row.get("name") or ""))
        if not _is_valid_manual_character_name(name):
            continue
        if name in seen:
            continue
        item = dict(row)
        item["name"] = name
        for field in text_fields:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                item[field] = _sanitize_outline_character_info(value, name=name, limit=1200)
        relationships = item.get("relationships")
        if isinstance(relationships, list):
            clean_relationships = []
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                target_label = str(rel.get("targetName") or rel.get("target") or "")
                if target_label and not _outline_is_valid_character_name(target_label):
                    continue
                clean_relationships.append(rel)
            item["relationships"] = clean_relationships
        sanitized.append(item)
        seen.add(name)
    return sanitized


@router.get("/{project_id}/characters", response_model=CharacterStoreResponse, summary="获取项目角色库")
async def get_project_characters(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    project = _get_project_for_actor_or_404(db, project_id, actor)

    project_data = _load_workspace_project_data(project)
    characters = project_data.get("characters") if isinstance(project_data, dict) else []
    characters = _sanitize_character_store_rows(characters)
    return CharacterStoreResponse(characters=characters)


@router.put("/{project_id}/characters", response_model=CharacterStoreResponse, summary="保存项目角色库")
async def save_project_characters(
    project_id: str,
    req: CharacterStoreRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    project = _get_project_for_actor_or_404(db, project_id, actor)

    characters = _sanitize_character_store_rows(req.characters or [])

    def update_current_project_data(project_data: dict[str, Any]) -> dict[str, Any]:
        project_data.setdefault("name", project.name)
        project_data.setdefault("config", _normalize_project_config_payload(project.get_config()))
        project_data["characters"] = characters
        project_data["updated_at"] = datetime.now().isoformat()
        return project_data

    _update_workspace_project_data_atomically(project, update_current_project_data)

    project.updated_at = datetime.now()
    db.commit()
    db.refresh(project)
    return CharacterStoreResponse(characters=characters)


@router.get("/{project_id}/state-cards", response_model=StoryStateCardStoreResponse, summary="获取项目状态卡")
async def get_project_state_cards(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    project = _get_project_for_actor_or_404(db, project_id, actor)

    project_data = _load_workspace_project_data(project)
    cards = _normalize_state_cards_payload(project_data.get("state_cards") if isinstance(project_data, dict) else {})
    return StoryStateCardStoreResponse(**cards)


@router.put("/{project_id}/state-cards", response_model=StoryStateCardStoreResponse, summary="保存项目状态卡")
async def save_project_state_cards(
    project_id: str,
    req: StoryStateCardStoreRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    project = _get_project_for_actor_or_404(db, project_id, actor)

    state_cards = req.model_dump()

    def update_current_project_data(project_data: dict[str, Any]) -> dict[str, Any]:
        project_data.setdefault("name", project.name)
        project_data.setdefault("config", _normalize_project_config_payload(project.get_config()))
        project_data["state_cards"] = state_cards
        project_data["updated_at"] = datetime.now().isoformat()
        return project_data

    _update_workspace_project_data_atomically(project, update_current_project_data)

    project.updated_at = datetime.now()
    db.commit()
    db.refresh(project)
    return StoryStateCardStoreResponse(**req.model_dump())


@router.get("/{project_id}/workflow-context", response_model=ProjectWorkflowContextResponse, summary="获取项目生成工作流上下文")
async def get_project_workflow_context(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    project = _get_project_for_actor_or_404(db, project_id, actor)

    project_data = _load_workspace_project_data(project)
    workflow_context = _normalize_workflow_context(project_data.get("workflow_context") if isinstance(project_data, dict) else {})
    canon_packet = _normalize_canon_packet(project_data.get("canon_packet") if isinstance(project_data, dict) else {})
    episode_memory_cards = _normalize_episode_memory_cards(project_data.get("episode_memory_cards") if isinstance(project_data, dict) else [])
    return ProjectWorkflowContextResponse(
        workflow_context=workflow_context,
        canon_packet=canon_packet,
        episode_memory_cards=episode_memory_cards,
        updated_at=str(project_data.get("updated_at") or ""),
    )


@router.put("/{project_id}/workflow-context", response_model=ProjectWorkflowContextResponse, summary="保存项目生成工作流上下文")
async def save_project_workflow_context(
    project_id: str,
    req: ProjectWorkflowContextRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    project = _get_project_for_actor_or_404(db, project_id, actor)

    incoming_workflow_context = (
        _normalize_workflow_context_patch(req.workflow_context)
        if req.merge
        else _normalize_workflow_context(req.workflow_context)
    )
    incoming_canon = _normalize_canon_packet(req.canon_packet)

    def update_current_project_data(project_data: dict[str, Any]) -> dict[str, Any]:
        project_data.setdefault("name", project.name)
        project_data.setdefault("config", _normalize_project_config_payload(project.get_config()))
        existing_workflow_context = _normalize_workflow_context(project_data.get("workflow_context"))
        workflow_context = (
            _merge_workflow_context_patch(existing_workflow_context, incoming_workflow_context)
            if req.merge else incoming_workflow_context
        )
        existing_canon = _normalize_canon_packet(project_data.get("canon_packet"))
        canon_packet = _deep_merge_dict(existing_canon, incoming_canon) if req.merge else incoming_canon
        existing_memory_cards = _normalize_episode_memory_cards(project_data.get("episode_memory_cards"))
        episode_memory_cards = (
            _merge_episode_memory_cards(existing_memory_cards, req.episode_memory_cards)
            if req.merge else _normalize_episode_memory_cards(req.episode_memory_cards)
        )
        project_data["workflow_context"] = workflow_context
        project_data["canon_packet"] = canon_packet
        project_data["episode_memory_cards"] = episode_memory_cards
        project_data["updated_at"] = datetime.now().isoformat()
        return project_data

    project_data = _update_workspace_project_data_atomically(project, update_current_project_data)
    workflow_context = _normalize_workflow_context(project_data.get("workflow_context"))
    canon_packet = _normalize_canon_packet(project_data.get("canon_packet"))
    episode_memory_cards = _normalize_episode_memory_cards(project_data.get("episode_memory_cards"))

    project.updated_at = datetime.now()
    db.commit()
    db.refresh(project)

    return ProjectWorkflowContextResponse(
        workflow_context=workflow_context,
        canon_packet=canon_packet,
        episode_memory_cards=episode_memory_cards,
        updated_at=str(project_data.get("updated_at") or ""),
    )
