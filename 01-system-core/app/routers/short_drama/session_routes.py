"""测试页 “启动上下文 / 素材推荐 / 素材选择 / 历史问题刷新” 4 个写作会话路由
（从 short_drama_writing.py 抽出）。

4 个 endpoint：

- GET  /sessions/{task_id}/startup-context        —— 拉新项目启动上下文（推荐素材 + 检查清单）
- POST /sessions/{task_id}/materials/recommend    —— 自动推荐素材
- POST /sessions/{task_id}/materials/select       —— 手动选择素材
- POST /sessions/{task_id}/issue-feedback/refresh —— 刷新历史问题反馈

主 router 用 include_router 聚合，URL 不变。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.models.material_item import MaterialItem
from app.schemas.short_drama_writing import (
    IssueFeedbackRefreshRequest,
    IssueFeedbackRefreshResponse,
    MaterialSelectionRequest,
    MaterialSelectionResponse,
    StartupChecklistItem,
    StartupContextResponse,
)
from app.services.issue_feedback_service import build_issue_feedback_snapshot
from app.services.material_library_service import (
    material_to_dict,
    select_project_materials,
)
from app.services.short_drama_session_metadata import (
    build_startup_checklist,
    get_session_task,
    now_iso,
    save_metadata,
)
from app.services.short_drama_step_prompts import (
    build_startup_context,
    derive_category_path,
)


router = APIRouter()  # 由主 router 加 prefix


@router.get(
    "/sessions/{task_id}/startup-context",
    response_model=StartupContextResponse,
    summary="获取新项目启动上下文",
)
async def get_startup_context(
    task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    _, metadata = get_session_task(db, task_id)
    category_path = derive_category_path(metadata)
    recommended_materials = select_project_materials(
        db,
        content_type=str((metadata.get("project") or {}).get("project_type") or "短剧"),
        project_tags=[
            str((metadata.get("project") or {}).get("genre_main") or "").strip(),
            str((metadata.get("project") or {}).get("genre_sub") or "").strip(),
        ],
        limit=3,
        issue_feedback=metadata.get("issue_feedback") or {},
        category_path=category_path,
    )
    return build_startup_context(metadata, recommended_materials=recommended_materials)


@router.post(
    "/sessions/{task_id}/materials/recommend",
    response_model=MaterialSelectionResponse,
    summary="为写作会话推荐素材",
)
async def recommend_materials(
    task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    task, metadata = get_session_task(db, task_id)
    project = metadata.get("project") or {}
    issue_feedback = metadata.get("issue_feedback") or {}
    category_path = derive_category_path(metadata)
    project_tags = [
        str(project.get("genre_main") or "").strip(),
        str(project.get("genre_sub") or "").strip(),
        str(project.get("audience_axis") or "").strip(),
    ]
    materials = select_project_materials(
        db,
        content_type=str(project.get("project_type") or "短剧"),
        project_tags=[tag for tag in project_tags if tag],
        limit=3,
        issue_feedback=issue_feedback,
        category_path=category_path,
    )
    metadata["materials"] = materials
    metadata["updated_at"] = now_iso()
    build_startup_checklist(metadata)
    save_metadata(db, task, metadata)
    return MaterialSelectionResponse(materials=materials, count=len(materials))


@router.post(
    "/sessions/{task_id}/materials/select",
    response_model=MaterialSelectionResponse,
    summary="手动选择写作会话素材",
)
async def select_materials(
    task_id: str,
    req: MaterialSelectionRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    task, metadata = get_session_task(db, task_id)
    material_ids = [str(item).strip() for item in req.material_ids if str(item).strip()]
    if not material_ids:
        metadata["materials"] = []
        metadata["updated_at"] = now_iso()
        build_startup_checklist(metadata)
        save_metadata(db, task, metadata)
        return MaterialSelectionResponse(materials=[], count=0)

    items = db.query(MaterialItem).filter(MaterialItem.id.in_(material_ids)).all()
    materials_by_id = {item.id: material_to_dict(item) for item in items}
    selected = [materials_by_id[item_id] for item_id in material_ids if item_id in materials_by_id]
    metadata["materials"] = selected
    metadata["updated_at"] = now_iso()
    build_startup_checklist(metadata)
    save_metadata(db, task, metadata)
    return MaterialSelectionResponse(materials=selected, count=len(selected))


@router.post(
    "/sessions/{task_id}/issue-feedback/refresh",
    response_model=IssueFeedbackRefreshResponse,
    summary="刷新写作会话历史问题反馈",
)
async def refresh_issue_feedback(
    task_id: str,
    req: IssueFeedbackRefreshRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    task, metadata = get_session_task(db, task_id)
    category_path = str(req.category_path or derive_category_path(metadata)).strip() or "当前赛道"
    snapshot = build_issue_feedback_snapshot(db, category_path)
    open_issues = snapshot.get("open_issues") or []
    issue_feedback = {
        **snapshot,
        "category_path": category_path,
        "negative_prompt_hints": [
            str(item.get("negative_prompt_hint") or "").strip()
            for item in open_issues
            if isinstance(item, dict) and str(item.get("negative_prompt_hint") or "").strip()
        ],
        "review_focus": [
            str(item.get("review_check_hint") or item.get("title") or "").strip()
            for item in open_issues
            if isinstance(item, dict) and str(item.get("review_check_hint") or item.get("title") or "").strip()
        ],
    }
    metadata["issue_feedback"] = issue_feedback
    metadata["updated_at"] = now_iso()
    checklist = build_startup_checklist(metadata)
    save_metadata(db, task, metadata)
    return IssueFeedbackRefreshResponse(
        issue_feedback=issue_feedback,
        startup_checklist=[StartupChecklistItem(**item) for item in checklist],
    )
