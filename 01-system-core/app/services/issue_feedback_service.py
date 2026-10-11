"""
问题清单反馈服务
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.issue_record import IssueRecord
from app.models.task import Task
from app.models.sub_task import SubTask

ISSUE_PATTERNS = [
    {
        "match": ["保守", "不够狠", "放不开"],
        "issue_key": "writing_over_conservative",
        "title": "写法过于保守",
        "severity": "high",
        "root_cause": "生成结果过度求稳，冲突和动作场面没有充分放大。",
        "negative_prompt_hint": "避免把情节写成安全但平的版本，必须保留冲突锋利度和动作场面张力。",
        "review_check_hint": "检查是否存在明显求稳、冲突变软、场面感被压平的问题。",
        "retrieval_hint": {
            "prefer_borrow_points": ["场面", "动作", "围观", "翻盘", "关系推进"],
            "avoid_summary_like": True,
            "avoid_generic_risk": True,
        },
    },
    {
        "match": ["总结", "概括", "不像重写", "梗概"],
        "issue_key": "summary_like_revision",
        "title": "改写结果过于总结化",
        "severity": "high",
        "root_cause": "召回和改写偏向摘要信息，导致文本更像概括而不是场景化重写。",
        "negative_prompt_hint": "不要把改写写成总结或梗概，必须落到具体场景、动作和人物反应。",
        "review_check_hint": "检查文本是否出现只讲结论不长场面的摘要化表达。",
        "retrieval_hint": {
            "prefer_borrow_points": ["动作", "反应", "关系推进", "名场面"],
            "avoid_summary_like": True,
            "avoid_generic_risk": True,
        },
    },
    {
        "match": ["rag", "素材", "召回"],
        "issue_key": "rag_after_revision_over_conservative",
        "title": "素材召回后改写过于保守",
        "severity": "high",
        "root_cause": "素材召回提供了方向，但也把表达收束成更保守、更标准化的版本。",
        "negative_prompt_hint": "素材只能提供参考，不要让召回内容压平角色声音和场面生长感。",
        "review_check_hint": "检查召回素材是否导致表达趋同、观感变稳但失去生气。",
        "retrieval_hint": {
            "prefer_borrow_points": ["角色声音", "关系拉扯", "场面", "围观感"],
            "avoid_summary_like": True,
            "avoid_generic_risk": True,
        },
    },
    {
        "match": ["围观", "公开", "打脸"],
        "issue_key": "public_payoff_not_strong_enough",
        "title": "围观打脸回报不够强",
        "severity": "medium",
        "root_cause": "高回报桥段缺少见证者、结果展示或后果兑现。",
        "negative_prompt_hint": "关键翻盘必须有围观者、结果展示和后果兑现，不能只停在口头回击。",
        "review_check_hint": "检查打脸桥段是否具备围观感、反应链和结果落地。",
        "retrieval_hint": {
            "prefer_borrow_points": ["围观", "翻盘", "公开结果", "亮牌"],
            "avoid_summary_like": False,
            "avoid_generic_risk": False,
        },
    },
]


SCOPE_LEVELS = ["project", "category", "global"]  # 三级scope：项目级 → 分类级 → 全局级


def _json_dumps(value: Any, default: Any) -> str:
    payload = value if value is not None else default
    return json.dumps(payload, ensure_ascii=False)



def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default



def normalize_issue_candidate(text: str) -> dict[str, Any]:
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    for item in ISSUE_PATTERNS:
        if any(keyword in normalized or keyword in lowered for keyword in item["match"]):
            return {
                "issue_key": item["issue_key"],
                "title": item["title"],
                "severity": item["severity"],
                "symptom": normalized,
                "root_cause": item["root_cause"],
                "negative_prompt_hint": item["negative_prompt_hint"],
                "review_check_hint": item["review_check_hint"],
                "retrieval_hint": item["retrieval_hint"],
            }
    issue_key = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_") or "project_specific_issue"
    return {
        "issue_key": issue_key[:80],
        "title": normalized[:60] or "项目特定问题",
        "severity": "medium",
        "symptom": normalized,
        "root_cause": "当前问题尚未命中预置归一规则，先按项目问题沉淀。",
        "negative_prompt_hint": f"避免再次出现：{normalized}" if normalized else "避免重复出现当前问题。",
        "review_check_hint": f"重点检查：{normalized}" if normalized else "重点检查当前项目已暴露问题。",
        "retrieval_hint": {
            "prefer_borrow_points": [],
            "avoid_summary_like": False,
            "avoid_generic_risk": False,
        },
    }



def build_category_context(task_metadata: dict[str, Any], best_sample: dict[str, Any] | None = None) -> dict[str, Any]:
    best_sample = best_sample or {}
    track = str(best_sample.get("track") or task_metadata.get("current_track") or "当前赛道").strip()
    source_payload = task_metadata.get("source_payload") or {}
    project_brief = source_payload.get("project_brief") or {}
    labels = list(project_brief.get("genres") or [])
    labels.extend(task_metadata.get("hot_category_summary") or [])
    labels.extend([track, task_metadata.get("lab_type") or ""])
    labels = [str(label).strip() for label in labels if str(label).strip()]
    primary_genre = next((label for label in project_brief.get("genres") or [] if str(label).strip()), "")
    category_path = " / ".join(part for part in [track, str(primary_genre).strip()] if part)
    return {
        "category_path": category_path or track or "当前赛道",
        "category_labels": list(dict.fromkeys(labels)),
    }



def extract_round_issue_candidates(task_metadata: dict[str, Any], round_result: dict[str, Any], best_sample: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    del task_metadata, best_sample
    candidates: list[dict[str, Any]] = []
    for defect in round_result.get("defects") or []:
        item = normalize_issue_candidate(str(defect))
        item["evidence"] = [
            {
                "round": round_result.get("round"),
                "score": round_result.get("score"),
                "defect": defect,
                "patch_summary": round_result.get("patch_summary") or "",
            }
        ]
        item["trigger_rounds"] = [round_result.get("round")]
        candidates.append(item)
    return candidates



def _next_scope_level(current: str, occurrence_count: int, cross_category_count: int) -> str:
    """
    简化的三级scope升级逻辑：
    - project: 单次出现（首次）
    - category: 同类别出现 >=2次
    - global: 跨类别出现 >=2次
    """
    if cross_category_count >= 2:
        return "global"
    if occurrence_count >= 2:
        return "category"
    return "project"



def upsert_issue_records(
    db: Session,
    task: Task,
    review_sub_task: SubTask | None,
    issue_candidates: list[dict[str, Any]],
    category_context: dict[str, Any],
) -> list[IssueRecord]:
    category_path = str(category_context.get("category_path") or "当前赛道")
    updated_records: list[IssueRecord] = []
    for candidate in issue_candidates:
        issue_key = str(candidate.get("issue_key") or "project_specific_issue")
        existing = db.query(IssueRecord).filter(
            IssueRecord.issue_key == issue_key,
            IssueRecord.category_path == category_path,
        ).first()
        if existing:
            evidence = _json_loads(existing.evidence_json, [])
            evidence.extend(candidate.get("evidence") or [])
            rounds = sorted({int(item) for item in (_json_loads(existing.trigger_rounds_json, []) + (candidate.get("trigger_rounds") or [])) if item is not None})
            existing.task_id = task.id
            existing.sub_task_id = review_sub_task.id if review_sub_task else existing.sub_task_id
            existing.symptom = str(candidate.get("symptom") or existing.symptom or "")
            existing.root_cause = str(candidate.get("root_cause") or existing.root_cause or "")
            existing.negative_prompt_hint = str(candidate.get("negative_prompt_hint") or existing.negative_prompt_hint or "")
            existing.review_check_hint = str(candidate.get("review_check_hint") or existing.review_check_hint or "")
            existing.retrieval_hint_json = _json_dumps(candidate.get("retrieval_hint") or _json_loads(existing.retrieval_hint_json, {}), {})
            existing.evidence_json = _json_dumps(evidence[-10:], [])
            existing.trigger_rounds_json = _json_dumps(rounds, [])
            existing.occurrence_count = int(existing.occurrence_count or 1) + 1
            cross_category_count = db.query(IssueRecord.category_path).filter(IssueRecord.issue_key == issue_key).distinct().count()
            existing.scope_level = _next_scope_level(existing.scope_level, existing.occurrence_count, cross_category_count)
            existing.last_seen_at = datetime.now()
            updated_records.append(existing)
            continue

        cross_category_count = db.query(IssueRecord.category_path).filter(IssueRecord.issue_key == issue_key).distinct().count()
        record = IssueRecord(
            task_id=task.id,
            sub_task_id=review_sub_task.id if review_sub_task else None,
            issue_key=issue_key,
            title=str(candidate.get("title") or issue_key),
            category_path=category_path,
            scope_level=_next_scope_level("project_only", 1, cross_category_count),
            status="open",
            severity=str(candidate.get("severity") or "medium"),
            symptom=str(candidate.get("symptom") or ""),
            root_cause=str(candidate.get("root_cause") or ""),
            evidence_json=_json_dumps(candidate.get("evidence") or [], []),
            trigger_rounds_json=_json_dumps(candidate.get("trigger_rounds") or [], []),
            negative_prompt_hint=str(candidate.get("negative_prompt_hint") or ""),
            review_check_hint=str(candidate.get("review_check_hint") or ""),
            retrieval_hint_json=_json_dumps(candidate.get("retrieval_hint") or {}, {}),
            occurrence_count=1,
            last_seen_at=datetime.now(),
        )
        db.add(record)
        updated_records.append(record)

    db.commit()
    for record in updated_records:
        db.refresh(record)
    return updated_records



def list_issue_records(
    db: Session,
    *,
    task_id: str | None = None,
    category_path: str | None = None,
    scope_level: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[IssueRecord]:
    query = db.query(IssueRecord)
    if task_id:
        query = query.filter(IssueRecord.task_id == task_id)
    if category_path:
        query = query.filter(IssueRecord.category_path == category_path)
    if scope_level:
        query = query.filter(IssueRecord.scope_level == scope_level)
    if status:
        query = query.filter(IssueRecord.status == status)
    return query.order_by(IssueRecord.last_seen_at.desc(), IssueRecord.created_at.desc()).limit(limit).all()



def get_issue_record(db: Session, issue_id: str) -> IssueRecord | None:
    return db.query(IssueRecord).filter(IssueRecord.id == issue_id).first()



def issue_to_dict(record: IssueRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "sub_task_id": record.sub_task_id,
        "issue_key": record.issue_key,
        "title": record.title,
        "category_path": record.category_path,
        "scope_level": record.scope_level,
        "status": record.status,
        "severity": record.severity,
        "symptom": record.symptom,
        "root_cause": record.root_cause,
        "evidence": _json_loads(record.evidence_json, []),
        "trigger_rounds": _json_loads(record.trigger_rounds_json, []),
        "negative_prompt_hint": record.negative_prompt_hint,
        "review_check_hint": record.review_check_hint,
        "retrieval_hint": _json_loads(record.retrieval_hint_json, {}),
        "occurrence_count": record.occurrence_count,
        "last_seen_at": record.last_seen_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }



def build_issue_feedback_snapshot(db: Session, category_path: str, limit: int = 5) -> dict[str, Any]:
    """构建Issue反馈快照（供下一轮生成时注入）"""
    records = list_issue_records(db, category_path=category_path, status="open", limit=limit)
    # 使用三级scope: project/category/global（原五级已简化）
    stable_records = [record for record in records if record.scope_level in {"category", "global"}]
    negative_hints = [record.negative_prompt_hint for record in stable_records if record.negative_prompt_hint]
    review_checks = [record.review_check_hint for record in stable_records if record.review_check_hint]
    retrieval_bias = {
        "prefer_borrow_points": [],
        "avoid_summary_like": False,
        "avoid_generic_risk": False,
    }
    for record in stable_records:
        hint = _json_loads(record.retrieval_hint_json, {})
        retrieval_bias["prefer_borrow_points"].extend(hint.get("prefer_borrow_points") or [])
        retrieval_bias["avoid_summary_like"] = retrieval_bias["avoid_summary_like"] or bool(hint.get("avoid_summary_like"))
        retrieval_bias["avoid_generic_risk"] = retrieval_bias["avoid_generic_risk"] or bool(hint.get("avoid_generic_risk"))
    retrieval_bias["prefer_borrow_points"] = list(dict.fromkeys(retrieval_bias["prefer_borrow_points"]))
    return {
        "category_path": category_path,
        "issue_count": len(records),
        "stable_issue_count": len(stable_records),
        "issues": [issue_to_dict(record) for record in records],
        "negative_prompt_hints": negative_hints,
        "review_checklist": review_checks,
        "retrieval_bias": retrieval_bias,
        "summary": "；".join(record.title for record in stable_records[:3]) or "当前分类暂无稳定问题反馈。",
    }



def build_issue_rule_suggestions(issue_records: list[IssueRecord]) -> list[dict[str, Any]]:
    """基于Issue记录生成规则建议（用于进化系统）"""
    suggestions: list[dict[str, Any]] = []
    for record in issue_records:
        # 使用三级scope：category/global 才纳入规则建议
        if record.scope_level not in {"category", "global"}:
            continue
        scope = "global" if record.scope_level == "global" else "task"
        suggestions.append({
            "scope": scope,
            "rule_type": "suggestion",
            "status": "candidate",
            "source": "workflow_summary",
            "content": f"建议规则（{record.scope_level}）：在 {record.category_path} 中重点规避“{record.title}”。检查项：{record.review_check_hint or record.symptom}",
        })
    return suggestions
