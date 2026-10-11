"""项目贡献度（从 projects_v2.py 抽出）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc
from pydantic import BaseModel, Field
import hashlib
from uuid import UUID
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
    _normalize_canon_packet,
    _normalize_episode_memory_cards,
    _normalize_project_config_payload,
    _normalize_state_cards_payload,
    _normalize_workflow_context,
    _recommend_classification_tracks,
    _sync_workspace_project_index,
    _update_contribution_ledger,
    _write_workspace_project_data,
)

router = APIRouter()  # 无 prefix；由 projects_v2.py 的主 router 加 prefix 聚合

@router.get("/{project_id}/contributions", summary="获取项目贡献度统计")
async def get_contributions(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取项目的贡献度排行榜"""
    _get_project_for_actor_or_404(db, project_id, actor)
    ledgers = db.query(ContributionLedger).filter(
        ContributionLedger.project_id == project_id
    ).order_by(desc(ContributionLedger.final_score)).all()

    total_score = sum(l.final_score for l in ledgers) or 1

    return [ContributionResponse(
        user_id=l.user_id,
        user_name=l.user_name,
        episodes_touched=l.episodes_touched,
        scenes_written=l.scenes_written,
        total_edits=l.total_edits,
        words_added=l.words_added,
        words_deleted=l.words_deleted,
        ai_generations_accepted=l.ai_generations_accepted,
        ai_generations_modified=l.ai_generations_modified,
        base_score=l.base_score,
        ai_collaboration_bonus=l.ai_collaboration_bonus,
        final_score=l.final_score,
        percentage=round(l.final_score / total_score * 100, 1)
    ) for l in ledgers]


@router.get("/{project_id}/contributions/heatmap", summary="获取贡献热力图")
async def get_contribution_heatmap(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db)
):
    """获取集级别的贡献热力图数据"""
    project = _get_project_for_actor_or_404(db, project_id, actor)

    # 获取所有版本
    versions = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id
    ).all()

    # 按集聚合
    episode_contributions = {}
    for v in versions:
        ep = v.episode_number
        if ep not in episode_contributions:
            episode_contributions[ep] = {}

        editor = v.editor_name or v.editor_id or "unknown"
        if editor not in episode_contributions[ep]:
            episode_contributions[ep][editor] = 0
        episode_contributions[ep][editor] += v.contribution_score

    # 生成热力图数据
    heatmap = []
    for ep_num in range(1, project.total_episodes + 1):
        contributors = episode_contributions.get(ep_num, {})
        total = sum(contributors.values()) or 1

        heatmap.append({
            "episode": ep_num,
            "contributors": [
                {"name": name, "percentage": round(score / total * 100, 1)}
                for name, score in contributors.items()
            ],
            "main_contributor": max(contributors, key=contributors.get) if contributors else None,
            "intensity": min(sum(contributors.values()) / 100, 1.0)  # 0-1热度值
        })

    return heatmap

