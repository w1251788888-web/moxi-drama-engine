"""
子任务路由 — CRUD + 状态操作
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from typing import Any, Optional, List
from datetime import datetime as dt

from app.database import get_db
from app.auth.dependencies import get_current_agent, verify_admin, require_role
from app.services import sub_task_service
from app.models.agent import Agent
from app.models.sub_task import SubTask


router = APIRouter(prefix="/sub-tasks", tags=["SubTask"])


# ============================================================
# 请求/响应模型
# ============================================================

class SubTaskCreateRequest(BaseModel):
    task_id: str = Field(..., description="所属任务 ID")
    name: str = Field(..., description="子任务名称")
    description: str = Field("", description="具体内容")
    deliverable: str = Field("", description="交付物描述")
    acceptance: str = Field("", description="验收标准")
    priority: str = Field("medium", description="优先级: high/medium/low")
    module_id: Optional[str] = Field(None, description="所属模块 ID（可选）")
    assigned_agent: Optional[str] = Field(None, description="指派 Agent ID（可选）")
    type: str = Field("once", description="类型: once/recurring")
    metadata: Optional[dict[str, Any]] = Field(None, description="扩展元数据（可声明项目写回目标）")


class SubTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    module_id: Optional[str]
    name: str
    description: str
    deliverable: str
    acceptance: str
    type: str
    status: str
    priority: str
    assigned_agent: Optional[str]
    current_session_id: Optional[str]
    rework_count: int
    created_at: Optional[dt] = None
    updated_at: Optional[dt] = None
    completed_at: Optional[dt] = None

class ClaimRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="OpenClaw 会话 ID")


class StartRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="OpenClaw 会话 ID")


class SubmitRequest(BaseModel):
    deliverable: Optional[str] = Field(None, description="本次提交的交付物摘要")
    output_content: Optional[str] = Field(None, description="本次提交的正文内容，可供审查通过后写回项目")
    project_writeback: Optional[dict[str, Any]] = Field(None, description="项目写回目标与参数")


class ReworkRequest(BaseModel):
    rework_agent: Optional[str] = Field(None, description="返工指派的 Agent ID（可选，不填则原 Agent）")


class ReassignRequest(BaseModel):
    agent_id: str = Field(..., description="新分配的 Agent ID")


class SubTaskUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="子任务名称")
    description: Optional[str] = Field(None, description="具体内容")
    deliverable: Optional[str] = Field(None, description="交付物描述")
    acceptance: Optional[str] = Field(None, description="验收标准")
    priority: Optional[str] = Field(None, description="优先级: high/medium/low")


# ============================================================
# CRUD
# ============================================================

@router.post("", response_model=SubTaskResponse, summary="创建子任务")
async def create_sub_task(
    req: SubTaskCreateRequest,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """规划师创建子任务"""
    try:
        sub_task = sub_task_service.create_sub_task(
            db,
            task_id=req.task_id,
            name=req.name,
            description=req.description,
            deliverable=req.deliverable,
            acceptance=req.acceptance,
            priority=req.priority,
            module_id=req.module_id,
            assigned_agent=req.assigned_agent,
            type=req.type,
            metadata=req.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.get("", response_model=List[SubTaskResponse], summary="查询子任务列表")
async def list_sub_tasks(
    task_id: Optional[str] = None,
    module_id: Optional[str] = None,
    status: Optional[str] = None,
    assigned_agent: Optional[str] = None,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """查询子任务列表，支持多条件过滤"""
    return sub_task_service.list_sub_tasks(
        db,
        task_id=task_id,
        module_id=module_id,
        status=status,
        assigned_agent=assigned_agent,
    )


@router.get("/{sub_task_id}", response_model=SubTaskResponse, summary="查看子任务详情")
async def get_sub_task(
    sub_task_id: str,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """获取单个子任务详情"""
    sub_task = sub_task_service.get_sub_task(db, sub_task_id)
    if not sub_task:
        raise HTTPException(status_code=404, detail="子任务不存在")
    return sub_task


@router.put("/{sub_task_id}", response_model=SubTaskResponse, summary="编辑子任务")
async def update_sub_task(
    sub_task_id: str,
    req: SubTaskUpdateRequest,
    agent: Agent = Depends(require_role("planner")),
    db: Session = Depends(get_db),
):
    """编辑子任务（规划者权限）"""
    try:
        sub_task = sub_task_service.update_sub_task(
            db,
            sub_task_id=sub_task_id,
            name=req.name,
            description=req.description,
            deliverable=req.deliverable,
            acceptance=req.acceptance,
            priority=req.priority,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


# ============================================================
# 自动调度 - Executor 轮询接口
# ============================================================

class PollResponse(BaseModel):
    found: bool = Field(..., description="是否找到待分配任务")
    sub_task: SubTaskResponse | None = Field(None, description="认领的子任务（如果有）")
    message: str = Field(..., description="提示信息")


@router.post("/poll", response_model=PollResponse, summary="Executor 轮询并认领待分配任务")
async def poll_pending_sub_task(
    session_id: Optional[str] = Body(None, description="OpenClaw 会话 ID"),
    agent: Agent = Depends(require_role("executor")),
    db: Session = Depends(get_db),
):
    """
    Executor 轮询接口：自动查找并认领一个 pending 状态的子任务。

    规则：
    1. 优先认领高优先级（high）的任务
    2. 同优先级按创建时间排序（先创建的先分配）
    3. 一个任务只能被一个 Agent 认领
    """
    # 查找当前 Agent 已认领但未完成的任务数
    current_task_count = db.query(func.count(SubTask.id)).filter(
        SubTask.assigned_agent == agent.id,
        SubTask.status.in_(["assigned", "in_progress"])
    ).scalar()

    if current_task_count >= 3:
        return PollResponse(
            found=False,
            message=f"当前已有 {current_task_count} 个进行中的任务，请先完成后再认领新任务"
        )

    # 查找待分配的任务（按优先级和创建时间排序）。最终归属由 claim 的条件更新保证。
    pending_tasks = db.query(SubTask).filter(
        SubTask.status == "pending"
    ).order_by(
        case((SubTask.priority == "high", 1), (SubTask.priority == "medium", 2), else_=3),
        SubTask.created_at.asc()
    ).with_for_update(skip_locked=True).limit(10).all()

    if not pending_tasks:
        return PollResponse(
            found=False,
            message="暂无待分配的任务"
        )

    last_error = None
    for pending_task in pending_tasks:
        try:
            sub_task = sub_task_service.claim_sub_task(
                db,
                sub_task_id=pending_task.id,
                agent_id=agent.id,
                session_id=session_id,
            )
            return PollResponse(
                found=True,
                sub_task=sub_task,
                message=f"成功认领任务：{sub_task.name}"
            )
        except ValueError as e:
            last_error = str(e)

    return PollResponse(
        found=False,
        message=f"认领失败：{last_error}" if last_error else "暂无可认领的任务"
    )


@router.get("/my/active", response_model=List[SubTaskResponse], summary="获取我认领的活跃任务")
async def get_my_active_tasks(
    agent: Agent = Depends(require_role("executor")),
    db: Session = Depends(get_db),
):
    """获取当前 Executor 已认领但未完成（assigned/in_progress）的任务列表"""
    return db.query(SubTask).filter(
        SubTask.assigned_agent == agent.id,
        SubTask.status.in_(["assigned", "in_progress"])
    ).order_by(SubTask.created_at.desc()).all()


# ============================================================
# 状态操作
# ============================================================

@router.post("/{sub_task_id}/claim", response_model=SubTaskResponse, summary="认领子任务")
async def claim_sub_task(
    sub_task_id: str,
    req: ClaimRequest,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Agent认领子任务，状态从 pending 变为 assigned"""
    try:
        sub_task = sub_task_service.claim_sub_task(
            db,
            sub_task_id=sub_task_id,
            agent_id=agent.id,
            session_id=req.session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/start", response_model=SubTaskResponse, summary="开始执行子任务")
async def start_sub_task(
    sub_task_id: str,
    req: StartRequest,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """开始执行子任务，状态从 assigned/rework 变为 in_progress"""
    try:
        sub_task = sub_task_service.start_sub_task(
            db,
            sub_task_id=sub_task_id,
            session_id=req.session_id,
            agent_id=agent.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/submit", response_model=SubTaskResponse, summary="提交子任务")
async def submit_sub_task(
    sub_task_id: str,
    req: Optional[SubmitRequest] = Body(default=None),
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """提交子任务进入审查，状态从 in_progress 变为 review"""
    try:
        if req:
            sub_task = sub_task_service.submit_sub_task_with_deliverable(
                db,
                sub_task_id=sub_task_id,
                agent_id=agent.id,
                deliverable=req.deliverable,
                output_content=req.output_content,
                project_writeback=req.project_writeback,
            )
        else:
            sub_task = sub_task_service.submit_sub_task(
                db,
                sub_task_id=sub_task_id,
                agent_id=agent.id,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/complete", response_model=SubTaskResponse, summary="完成子任务")
async def complete_sub_task(
    sub_task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """管理员标记子任务完成，状态变为 done"""
    try:
        sub_task = sub_task_service.complete_sub_task(db, sub_task_id=sub_task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/rework", response_model=SubTaskResponse, summary="子任务返工")
async def rework_sub_task(
    sub_task_id: str,
    req: ReworkRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """管理员将子任务标记为返工，状态从 review 变为 rework"""
    try:
        sub_task = sub_task_service.rework_sub_task(
            db,
            sub_task_id=sub_task_id,
            rework_agent=req.rework_agent,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/reassign", response_model=SubTaskResponse, summary="重新分配子任务")
async def reassign_sub_task(
    sub_task_id: str,
    req: ReassignRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """管理员重新分配子任务给其他Agent"""
    try:
        sub_task = sub_task_service.reassign_sub_task(
            db,
            sub_task_id=sub_task_id,
            agent_id=req.agent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/block", response_model=SubTaskResponse, summary="阻塞子任务")
async def block_sub_task(
    sub_task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """管理员将子任务标记为阻塞状态"""
    try:
        sub_task = sub_task_service.block_sub_task(db, sub_task_id=sub_task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task


@router.post("/{sub_task_id}/cancel", response_model=SubTaskResponse, summary="取消子任务")
async def cancel_sub_task(
    sub_task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """管理员取消子任务"""
    try:
        sub_task = sub_task_service.cancel_sub_task(db, sub_task_id=sub_task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub_task
