"""
问题清单只读路由
"""
from __future__ import annotations

from datetime import datetime as dt
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services import issue_feedback_service

router = APIRouter(prefix="/issues", tags=["Issue"])


class IssueResponse(BaseModel):
    id: str
    task_id: str
    sub_task_id: Optional[str] = None
    issue_key: str
    title: str
    category_path: str
    scope_level: str
    status: str
    severity: str
    symptom: str = ""
    root_cause: str = ""
    evidence: List[Any] = Field(default_factory=list)
    trigger_rounds: List[int] = Field(default_factory=list)
    negative_prompt_hint: str = ""
    review_check_hint: str = ""
    retrieval_hint: dict = Field(default_factory=dict)
    occurrence_count: int
    last_seen_at: Optional[dt] = None
    created_at: Optional[dt] = None
    updated_at: Optional[dt] = None


@router.get("", response_model=List[IssueResponse], summary="查看问题清单")
async def list_issues(
    task_id: Optional[str] = None,
    category_path: Optional[str] = None,
    scope_level: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    items = issue_feedback_service.list_issue_records(
        db,
        task_id=task_id,
        category_path=category_path,
        scope_level=scope_level,
        status=status,
        limit=limit,
    )
    return [issue_feedback_service.issue_to_dict(item) for item in items]


@router.get("/{issue_id}", response_model=IssueResponse, summary="查看问题详情")
async def get_issue(
    issue_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    item = issue_feedback_service.get_issue_record(db, issue_id)
    if not item:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    return issue_feedback_service.issue_to_dict(item)
