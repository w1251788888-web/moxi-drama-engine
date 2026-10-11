"""测试页"读取前端工作流进度文件"路由（从 short_drama_writing.py 抽出）。

这个 endpoint 只读 frontend_workflow_progress.json 文件，不依赖 router 内的
任何辅助 helper，纯文件 IO + 数据整理，搬出去对调用方零影响。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import verify_admin
from app.schemas.short_drama_writing import (
    TestingResumeQuery,
    TestingResumeResponse,
)
from app.services import workspace_service

router = APIRouter()  # 由主 router 加 prefix


@router.post(
    "/testing/resume",
    response_model=TestingResumeResponse,
    summary="读取前端工作流进度文件，返回已完成/待生成集列表",
)
async def resume_testing_workflow(req: TestingResumeQuery, _: bool = Depends(verify_admin)):
    try:
        ws = workspace_service.ensure_project_workspace(
            req.workspace_path,
            allowed_roots=workspace_service.project_workspace_roots(),
            create=False,
        )
    except workspace_service.WorkspaceMissingError as exc:
        raise HTTPException(status_code=404, detail=f"工作目录不存在：{req.workspace_path}") from exc
    except workspace_service.WorkspaceBoundaryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    progress_path = ws / "frontend_workflow_progress.json"
    if not progress_path.exists():
        raise HTTPException(status_code=404, detail="未找到 frontend_workflow_progress.json")
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"进度文件解析失败：{exc}")
    results = data.get("results") or []
    completed: list[int] = []
    failed: list[int] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            ep = int(item.get("episode_no") or 0)
        except Exception:
            continue
        if not ep:
            continue
        if int(item.get("char_count") or 0) <= 0 or item.get("blocking_issues"):
            failed.append(ep)
        else:
            completed.append(ep)
    completed_set = set(completed)
    pending = [n for n in range(1, max(1, req.expected_total) + 1) if n not in completed_set]
    return TestingResumeResponse(
        workspace_path=str(ws),
        progress_file=str(progress_path),
        project_id=str(data.get("project_id") or ""),
        project_name=str(data.get("project_name") or ""),
        completed_episodes=sorted(completed),
        pending_episodes=pending,
        failed_episodes=sorted(failed),
        last_updated=str(data.get("updated_at") or ""),
    )
