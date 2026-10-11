"""
管理端任务查询路由
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.schemas.admin_task import (
    AdminModuleDetail,
    AdminModulePageResponse,
    AdminSubTaskDetail,
    AdminSubTaskPageResponse,
    AdminTaskDetail,
    AdminTaskPageResponse,
)
from app.routers.projects._helpers import _project_library_delete_roots, _safe_rmtree
from app.services import admin_task_query_service


router = APIRouter(prefix="/admin", tags=["Admin Task"])


def _raise_admin_query_error(exc: Exception) -> None:
    """统一处理管理端查询异常"""
    if isinstance(exc, admin_task_query_service.ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, admin_task_query_service.InvalidQueryError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/tasks", response_model=AdminTaskPageResponse, summary="管理端查看任务列表")
async def list_admin_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: Optional[str] = Query(None, description="任务状态"),
    task_type: Optional[str] = Query(None, alias="type", description="任务类型 once/recurring"),
    keyword: Optional[str] = Query(None, description="按任务名或描述搜索"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """分页查询管理端任务列表"""
    try:
        return admin_task_query_service.list_tasks(
            db,
            page=page,
            page_size=page_size,
            status=status,
            task_type=task_type,
            keyword=keyword,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        _raise_admin_query_error(exc)


@router.get("/tasks/{task_id}", response_model=AdminTaskDetail, summary="管理端查看任务详情")
async def get_admin_task_detail(
    task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """查看管理端任务详情"""
    try:
        return admin_task_query_service.get_task_detail(db, task_id)
    except Exception as exc:
        _raise_admin_query_error(exc)


@router.get("/tasks/{task_id}/modules", response_model=AdminModulePageResponse, summary="管理端查看任务模块列表")
async def list_admin_task_modules(
    task_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """分页查看某任务下的模块列表"""
    try:
        return admin_task_query_service.list_task_modules(
            db,
            task_id=task_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        _raise_admin_query_error(exc)


@router.get("/modules/{module_id}", response_model=AdminModuleDetail, summary="管理端查看模块详情")
async def get_admin_module_detail(
    module_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """查看管理端模块详情"""
    try:
        return admin_task_query_service.get_module_detail(db, module_id)
    except Exception as exc:
        _raise_admin_query_error(exc)


@router.get(
    "/tasks/{task_id}/sub-tasks",
    response_model=AdminSubTaskPageResponse,
    summary="管理端查看任务子任务列表",
)
async def list_admin_task_sub_tasks(
    task_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    module_id: Optional[str] = Query(None, description="按模块过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    assigned_agent: Optional[str] = Query(None, description="按 Agent ID 过滤"),
    priority: Optional[str] = Query(None, description="按优先级过滤"),
    task_type: Optional[str] = Query(None, alias="type", description="按类型过滤 once/recurring"),
    keyword: Optional[str] = Query(None, description="按名称或描述搜索"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """分页查看某任务下的子任务列表"""
    try:
        return admin_task_query_service.list_task_sub_tasks(
            db,
            task_id=task_id,
            page=page,
            page_size=page_size,
            module_id=module_id,
            status=status,
            assigned_agent=assigned_agent,
            priority=priority,
            task_type=task_type,
            keyword=keyword,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        _raise_admin_query_error(exc)


@router.get(
    "/modules/{module_id}/sub-tasks",
    response_model=AdminSubTaskPageResponse,
    summary="管理端查看模块子任务列表",
)
async def list_admin_module_sub_tasks(
    module_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    assigned_agent: Optional[str] = Query(None, description="按 Agent ID 过滤"),
    priority: Optional[str] = Query(None, description="按优先级过滤"),
    task_type: Optional[str] = Query(None, alias="type", description="按类型过滤 once/recurring"),
    keyword: Optional[str] = Query(None, description="按名称或描述搜索"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """分页查看某模块下的子任务列表"""
    try:
        return admin_task_query_service.list_module_sub_tasks(
            db,
            module_id=module_id,
            page=page,
            page_size=page_size,
            status=status,
            assigned_agent=assigned_agent,
            priority=priority,
            task_type=task_type,
            keyword=keyword,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        _raise_admin_query_error(exc)


@router.get("/sub-tasks", response_model=AdminSubTaskPageResponse, summary="管理端查看全局子任务列表")
async def list_admin_sub_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    task_id: Optional[str] = Query(None, description="按任务过滤"),
    module_id: Optional[str] = Query(None, description="按模块过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    assigned_agent: Optional[str] = Query(None, description="按 Agent ID 过滤"),
    priority: Optional[str] = Query(None, description="按优先级过滤"),
    task_type: Optional[str] = Query(None, alias="type", description="按类型过滤 once/recurring"),
    keyword: Optional[str] = Query(None, description="按名称或描述搜索"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """分页查看全局子任务列表"""
    try:
        return admin_task_query_service.list_sub_tasks(
            db,
            page=page,
            page_size=page_size,
            task_id=task_id,
            module_id=module_id,
            status=status,
            assigned_agent=assigned_agent,
            priority=priority,
            task_type=task_type,
            keyword=keyword,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        _raise_admin_query_error(exc)


def _delete_task_core(db: Session, task_id: str) -> tuple[bool, str | None]:
    """删除单个任务的核心逻辑，返回 (是否成功, 工作目录路径)。任务不存在返回 (False, None)。"""
    import json
    from pathlib import Path
    from app.models.task import Task
    from app.models.module import Module
    from app.models.sub_task import SubTask

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return False, None

    deleted_dir = None
    if task.metadata_json:
        try:
            meta = json.loads(task.metadata_json)
            work_dir = meta.get("work_dir") or meta.get("output_dir") or meta.get("project_dir")
            if work_dir:
                work_path = Path(work_dir)
                try:
                    cleaned = _safe_rmtree(work_path, allowed_roots=_project_library_delete_roots())
                except ValueError:
                    cleaned = False
                if cleaned:
                    deleted_dir = str(work_path)
        except Exception:
            pass

    db.query(SubTask).filter(SubTask.task_id == task_id).delete(synchronize_session=False)
    db.query(Module).filter(Module.task_id == task_id).delete(synchronize_session=False)
    db.delete(task)
    return True, deleted_dir


@router.delete("/tasks/{task_id}", summary="管理端删除任务")
async def delete_admin_task(
    task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """删除任务及其所有关联数据（模块、子任务等），同时删除关联的工作目录"""
    ok, deleted_dir = _delete_task_core(db, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    db.commit()
    msg = f"任务 {task_id} 已删除"
    if deleted_dir:
        msg += f"，工作目录 {deleted_dir} 已清理"
    return {"status": "ok", "message": msg}


@router.post("/tasks/bulk-delete", summary="管理端批量删除任务")
async def bulk_delete_admin_tasks(
    payload: dict,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """批量删除任务。请求体：{"task_ids": ["id1", "id2", ...]}"""
    task_ids = payload.get("task_ids") or []
    if not isinstance(task_ids, list) or not task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")
    if len(task_ids) > 200:
        raise HTTPException(status_code=400, detail="单次批量删除不能超过 200 个")

    deleted: list[str] = []
    not_found: list[str] = []
    cleaned_dirs: list[str] = []
    for tid in task_ids:
        if not isinstance(tid, str) or not tid:
            continue
        ok, deleted_dir = _delete_task_core(db, tid)
        if ok:
            deleted.append(tid)
            if deleted_dir:
                cleaned_dirs.append(deleted_dir)
        else:
            not_found.append(tid)
    db.commit()

    return {
        "status": "ok",
        "deleted_count": len(deleted),
        "not_found_count": len(not_found),
        "cleaned_dir_count": len(cleaned_dirs),
        "deleted": deleted,
        "not_found": not_found,
    }


@router.get("/sub-tasks/{sub_task_id}", response_model=AdminSubTaskDetail, summary="管理端查看子任务详情")
async def get_admin_sub_task_detail(
    sub_task_id: str,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """查看管理端子任务详情"""
    try:
        return admin_task_query_service.get_sub_task_detail(db, sub_task_id)
    except Exception as exc:
        _raise_admin_query_error(exc)
