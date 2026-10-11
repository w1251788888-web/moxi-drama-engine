"""
缩短Issue反馈链路 — 合并5层为2层

原链路（5层）：
  extract_round_issue_candidates → normalize_issue_candidate
  → upsert_issue_records → build_issue_feedback_snapshot
  → build_issue_rule_suggestions

新链路（2层）：
  detect_issues() → process_issue_feedback()
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session

from app.models.issue_record import IssueRecord
from app.models.task import Task
from app.models.sub_task import SubTask


def detect_issues(review_result: dict[str, Any], category_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    问题检测与归一化（合并原extract_round_issue_candidates + normalize_issue_candidate）

    Args:
        review_result: { "round": int, "defects": [...], "score": int, ... }
        category_context: { "category_path": str, ... }

    Returns:
        [
            {
                "issue_key": "writing_over_conservative",
                "title": "写法过于保守",
                "severity": "high",
                "symptom": "保守",
                "root_cause": "...",
                "negative_prompt_hint": "...",
                "review_check_hint": "...",
                "retrieval_hint": {...},
                "evidence": [{"round": 1, "defect": "保守", ...}],
                "trigger_rounds": [1],
            },
            ...
        ]
    """
    from app.services.issue_feedback_service import normalize_issue_candidate, ISSUE_PATTERNS

    candidates: list[dict[str, Any]] = []
    round_no = review_result.get("round", 1)
    defects = review_result.get("defects") or []

    for defect in defects:
        defect_str = str(defect).strip()
        if not defect_str:
            continue

        # 归一化
        normalized = normalize_issue_candidate(defect_str)

        # 构建evidence
        evidence = [{
            "round": round_no,
            "score": review_result.get("score"),
            "defect": defect_str,
            "patch_summary": review_result.get("patch_summary") or "",
        }]

        #  enriched candidate
        candidate = {
            **normalized,
            "evidence": evidence,
            "trigger_rounds": [round_no],
        }
        candidates.append(candidate)

    return candidates


def process_issue_feedback(
    db: Session,
    task: Task,
    issue_candidates: list[dict[str, Any]],
    category_context: dict[str, Any] | None = None,
    review_sub_task: SubTask | None = None,
) -> dict[str, Any]:
    """
    Issue反馈全链路处理（合并原 upsert_issue_records + build_issue_feedback_snapshot + build_issue_rule_suggestions）

    Args:
        db: 数据库会话
        task: 任务对象
        issue_candidates: detect_issues返回的问题候选列表
        category_context: 分类上下文 {category_path, ...}
        review_sub_task: 关联的审查子任务（可选）

    Returns:
        {
            "records": [...],           # 写入的IssueRecord列表
            "snapshot": {...},          # 反馈快照（供下一轮生成注入）
            "suggestions": [...],       # 规则建议
            "stats": {
                "new_count": int,       # 新问题数
                "updated_count": int,   # 更新问题数
                "scope_upgraded": int,  # 升级问题数
            }
        }
    """
    from app.services.issue_feedback_service import (
        upsert_issue_records,
        build_issue_feedback_snapshot,
        build_issue_rule_suggestions,
    )

    category_path = (category_context or {}).get("category_path", "当前赛道")

    # 1. 写入/更新Issue记录
    records = upsert_issue_records(db, task, review_sub_task, issue_candidates, {"category_path": category_path})

    # 2. 构建反馈快照
    snapshot = build_issue_feedback_snapshot(db, category_path)

    # 3. 生成规则建议
    suggestions = build_issue_rule_suggestions(records)

    # 统计
    new_count = sum(1 for r in records if r.occurrence_count == 1)
    updated_count = sum(1 for r in records if r.occurrence_count > 1)
    scope_upgraded = sum(1 for r in records if r.scope_level in {"category", "global"})

    return {
        "records": records,
        "snapshot": snapshot,
        "suggestions": suggestions,
        "stats": {
            "new_count": new_count,
            "updated_count": updated_count,
            "scope_upgraded": scope_upgraded,
        },
    }
