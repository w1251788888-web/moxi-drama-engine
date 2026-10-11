"""
任务路由 — 任务和模块的 CRUD
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime as dt

from app.database import get_db
from app.auth.dependencies import get_current_agent, verify_admin, require_role
from app.services import task_service
from app.services.market_workflow_service import (
    create_custom_short_drama_lab_task as create_custom_lab_task,
)
from app.models.agent import Agent


router = APIRouter(prefix="/tasks", tags=["Task"])


# ============================================================
# 请求/响应模型
# ============================================================

class TaskCreateRequest(BaseModel):
    name: str = Field(..., description="任务名称")
    description: str = Field("", description="任务描述")
    type: str = Field("once", description="类型: once/recurring")


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    type: str
    status: str
    created_at: Optional[dt] = None
    updated_at: Optional[dt] = None

class TaskStatusRequest(BaseModel):
    status: str = Field(..., description="状态: planning/active/in_progress/completed/archived/cancelled")


class TaskUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="任务名称")
    description: Optional[str] = Field(None, description="任务描述")


class ModuleCreateRequest(BaseModel):
    name: str = Field(..., description="模块名称")
    description: str = Field("", description="模块描述")


class ModuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    name: str
    description: str


class AutoMarketTaskRequest(BaseModel):
    task_name: Optional[str] = Field(None, description="任务名称，留空则使用默认")
    task_description: Optional[str] = Field(None, description="任务描述，留空则使用默认")
    type: str = Field("once", description="类型: once/recurring")


class ShortDramaLabTaskRequest(BaseModel):
    task_name: Optional[str] = Field(None, description="实验任务名称")
    task_description: Optional[str] = Field(None, description="实验任务描述")


class CustomShortDramaLabTaskRequest(BaseModel):
    doc_path: str = Field(..., description="本地 docx 原稿路径")
    task_name: Optional[str] = Field(None, description="实验任务名称")
    task_description: Optional[str] = Field(None, description="实验任务描述")


class ExecuteShortDramaLabResponse(BaseModel):
    task_id: str
    status: str
    artifact_path: str
    final_summary: str
    rounds: List[dict] = Field(default_factory=list)


# ============================================================
# 任务路由
# ============================================================

@router.post("", response_model=TaskResponse, summary="创建任务")
async def create_task(
    req: TaskCreateRequest,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """规划师创建任务"""
    try:
        task = task_service.create_task(db, req.name, req.description, req.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.post("/market-demo", response_model=TaskResponse, summary="一键创建短剧市场验证任务")
async def create_market_demo_task(
    req: AutoMarketTaskRequest = AutoMarketTaskRequest(),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """创建短剧市场验证任务，自动生成模块和子任务"""
    from app.services.market_workflow_service import create_market_validation_task

    try:
        result = create_market_validation_task(db)
        task = result["task"]
        if req.task_name:
            task.name = req.task_name
        if req.task_description:
            task.description = req.task_description
        task.type = req.type
        db.commit()
        db.refresh(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.post("/short-drama-lab", response_model=TaskResponse, summary="一键创建短剧市场对标实验任务")
async def create_short_drama_lab_task(
    req: ShortDramaLabTaskRequest = ShortDramaLabTaskRequest(),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """创建市场行情驱动的短剧写作逻辑实验任务"""
    from app.services.market_workflow_service import create_short_drama_lab_task as create_lab_task

    try:
        result = create_lab_task(db, task_name=req.task_name, task_description=req.task_description)
        task = result["task"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.post("/short-drama-lab/custom", response_model=TaskResponse, summary="创建定制短剧市场对标实验任务")
async def create_custom_short_drama_lab_task(
    req: CustomShortDramaLabTaskRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """基于用户原稿创建定制短剧实验任务"""
    try:
        result = create_custom_lab_task(
            db,
            doc_path=req.doc_path,
            task_name=req.task_name,
            task_description=req.task_description,
        )
        task = result["task"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.post("/{task_id}/execute-short-drama-lab", response_model=ExecuteShortDramaLabResponse, summary="执行短剧市场对标实验任务")
async def execute_short_drama_lab_task(
    task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """执行短剧实验闭环，完成轮次评审并导出验收结果"""
    from app.services.market_workflow_service import execute_short_drama_lab_task as execute_lab_task

    try:
        result = execute_lab_task(db, task_id)
        task = result["task"]
        metadata = getattr(task, "metadata", None)
        if metadata is None:
            import json
            metadata = json.loads(task.metadata_json) if getattr(task, "metadata_json", "") else {}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExecuteShortDramaLabResponse(
        task_id=task.id,
        status=task.status,
        artifact_path=result["artifact_path"],
        final_summary=metadata.get("final_summary", ""),
        rounds=result.get("rounds", []),
    )


@router.get("", summary="查看任务列表")
async def list_tasks(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 0,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    查看所有任务，可按状态过滤。
    - page_size=0（默认）: 返回全部
    - page_size>0: 分页返回
    """
    from app.services.pagination import paginate
    query = db.query(task_service.Task)
    if status:
        query = query.filter(task_service.Task.status == status)
    query = query.order_by(task_service.Task.created_at.desc())
    return paginate(query, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskResponse, summary="查看任务详情")
async def get_task(
    task_id: str,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """获取单个任务详情"""
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.put("/{task_id}/status", response_model=TaskResponse, summary="更新任务状态")
async def update_task_status(
    task_id: str,
    req: TaskStatusRequest,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """更新任务状态（如 planning → active）"""
    try:
        task = task_service.update_task_status(db, task_id, req.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.put("/{task_id}", response_model=TaskResponse, summary="编辑任务")
async def update_task(
    task_id: str,
    req: TaskUpdateRequest,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """编辑任务名称/描述（仅 planning/active 状态可编辑）"""
    try:
        task = task_service.update_task(db, task_id, name=req.name, description=req.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.post("/{task_id}/cancel", response_model=TaskResponse, summary="取消任务")
async def cancel_task(
    task_id: str,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """取消任务（已完成/已归档/已取消的不能取消）"""
    try:
        task = task_service.cancel_task(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


# ============================================================
# 模块路由（挂在 /tasks/{task_id}/modules 下）
# ============================================================

@router.post("/{task_id}/modules", response_model=ModuleResponse, summary="创建模块")
async def create_module(
    task_id: str,
    req: ModuleCreateRequest,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """在任务下创建模块"""
    try:
        module = task_service.create_module(db, task_id, req.name, req.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return module


@router.get("/{task_id}/modules", response_model=List[ModuleResponse], summary="查看模块列表")
async def list_modules(
    task_id: str,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """查看任务下的所有模块"""
    return task_service.list_modules(db, task_id)
