"""短剧写作会话导出路由（从 short_drama_writing.py 抽出）。

这个 endpoint 只调用 services 层的 export_txt / export_docx，
不依赖主 router 内的私有 helper，是纯外壳代码。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.schemas.short_drama_writing import ExportRequest, ExportResponse
from app.services.short_drama_export import NoExportableScriptError, export_docx, export_txt
from app.services.short_drama_session_metadata import (
    get_session_task,
    now_iso,
    save_metadata,
)

router = APIRouter()  # 由主 router 加 prefix


@router.post("/sessions/{task_id}/export", response_model=ExportResponse, summary="导出写作会话")
async def export_session(task_id: str, req: ExportRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    task, metadata = get_session_task(db, task_id)
    session_name = task.name

    try:
        if req.format == "txt":
            path = export_txt(session_name, metadata, req.episode_no, req.scope)
        else:
            path = export_docx(session_name, metadata, req.episode_no, req.scope)
    except NoExportableScriptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    metadata.setdefault("exports", [])
    if not isinstance(metadata["exports"], list):
        metadata["exports"] = []
    metadata["exports"].append(
        {
            "format": req.format,
            "path": str(path),
            "episode_no": req.episode_no,
            "scope": req.scope,
            "exported_at": now_iso(),
        }
    )
    metadata["updated_at"] = now_iso()

    save_metadata(db, task, metadata)

    return ExportResponse(path=str(path))
