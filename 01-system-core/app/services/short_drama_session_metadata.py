"""短剧写作会话的 metadata 持久化辅助（从 short_drama_writing.py 抽出）。

这些函数全部围绕 task.metadata_json 字符串的读 / 写 / 合并：
- 时间戳工具
- JSON dump / load
- dict deep merge
- "这是不是 short drama session" 校验 + 取 task

不涉及业务逻辑，纯数据通道。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.task import Task
from app.services.short_drama_workflow_config import KIND


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dump_metadata(metadata: dict | None) -> str:
    if not metadata:
        return ""
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))


def load_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def deep_merge(dst: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            deep_merge(dst[key], value)
        else:
            dst[key] = value
    return dst


def ensure_is_session(metadata: dict) -> None:
    if metadata.get("kind") != KIND:
        raise HTTPException(status_code=404, detail="写作会话不存在")


def get_session_task(db: Session, task_id: str) -> tuple[Task, dict]:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="写作会话不存在")
    metadata = load_metadata(task.metadata_json)
    ensure_is_session(metadata)
    return task, metadata


def save_metadata(db: Session, task: Task, metadata: dict) -> None:
    """把 metadata 写回 task 行（统一 JSON 格式 + 乐观锁 + commit + refresh）。"""
    current_version = int(getattr(task, "metadata_version", 0) or 0)
    rows = db.query(Task).filter(
        Task.id == task.id,
        Task.metadata_version == current_version,
    ).update(
        {
            Task.metadata_json: dump_metadata(metadata),
            Task.metadata_version: current_version + 1,
            Task.updated_at: datetime.now(),
        },
        synchronize_session=False,
    )
    if rows != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="写作会话已被其他操作更新，请刷新后重试")
    db.commit()
    db.refresh(task)


def build_startup_checklist(metadata: dict) -> list[dict[str, Any]]:
    """从 metadata 派生项目启动 checklist（写回 metadata["startup_checklist"]）。

    纯计算：根据 project / inputs / materials / issue_feedback / steps 现状
    生成 6 条状态项，前端用于展示"项目准备度"。
    """
    project = metadata.get("project") or {}
    inputs = metadata.get("inputs") or {}
    materials = metadata.get("materials") or []
    issue_feedback = metadata.get("issue_feedback") or {}
    steps = metadata.get("steps") or {}

    # market_check 通过状态
    mc_step = (steps or {}).get("market_check") or {}
    mc_result = mc_step.get("market_check_result") or {}
    mc_verdict = str(mc_result.get("verdict") or "").strip().lower()
    mc_passed = mc_verdict in ("pass", "warn")  # warn 是软通过

    items = [
        {
            "key": "brief",
            "label": "项目 brief 已填写",
            "done": bool(str(inputs.get("brief") or "").strip()),
            "hint": "至少补充一句项目题眼、主冲突或开场钩子。",
        },
        {
            "key": "genre",
            "label": "题材与受众已明确",
            "done": bool(str(project.get("genre_main") or "").strip() and str(project.get("audience_axis") or "").strip()),
            "hint": "至少明确主类型和受众轴。",
        },
        {
            "key": "market_check",
            "label": "市场可行性已通过",
            "done": mc_passed,
            "hint": "需先执行市场可行性检查（≥3项通过才能放行进入概念规划）。",
        },
        {
            "key": "materials",
            "label": "已准备素材参考",
            "done": isinstance(materials, list) and len(materials) > 0,
            "hint": "可先自动推荐，再手动删减到 1-3 条。",
        },
        {
            "key": "issues",
            "label": "已加载历史问题反馈",
            "done": bool(str((issue_feedback or {}).get("summary") or "").strip()),
            "hint": "建议开项前刷新一次历史问题约束。",
        },
        {
            "key": "storyboard",
            "label": "分镜步骤可用",
            "done": isinstance(steps, dict) and "storyboard" in steps,
            "hint": "可在成稿后补跑 storyboard，不影响主链起稿。",
        },
    ]
    metadata["startup_checklist"] = items
    return items
