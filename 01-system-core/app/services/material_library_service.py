"""
素材库服务
"""
from __future__ import annotations

import json
from typing import Any

from app.models.material_item import MaterialItem
from app.services.text_generation_service import generate_json, generation_enabled

# 外部工具 Skill 导入（可选）
try:
    from skills.funnlp_skill.funnlp_cli import detect_similar_segments
    FUNNLP_AVAILABLE = True
except ImportError:
    FUNNLP_AVAILABLE = False

APPROVAL_THRESHOLD = 75.0


def _json_dumps(value: Any, default: Any) -> str:
    payload = value if value is not None else default
    return json.dumps(payload, ensure_ascii=False)


def _json_loads(raw: str, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def material_to_dict(item: MaterialItem) -> dict[str, Any]:
    """将MaterialItem模型转换为字典，返回统一的项目标签"""
    # 优先读取新字段project_tags_json，不存在则回退到旧三标签合并
    project_tags = _json_loads(item.project_tags_json, None)
    if project_tags is None:
        # 渐进式迁移：旧数据回退逻辑
        structure_tags = _json_loads(item.structure_tags_json, [])
        style_tags = _json_loads(item.style_tags_json, [])
        project_fit_tags = _json_loads(item.project_fit_tags_json, [])
        project_tags = list(dict.fromkeys(structure_tags + style_tags + project_fit_tags))

    return {
        "id": item.id,
        "source_platform": item.source_platform,
        "source_url": item.source_url,
        "content_type": item.content_type,
        "title": item.title,
        "summary": item.summary,
        "heat_score": item.heat_score,
        "heat_reason": item.heat_reason,
        "data_points": _json_loads(item.data_points_json, []),
        "tags": project_tags,  # 统一标签出口（兼容前端）
        "project_tags": project_tags,  # 统一标签（新字段名）
        "structure_tags": _json_loads(item.structure_tags_json, []),  # 保留旧字段（已废弃）
        "style_tags": _json_loads(item.style_tags_json, []),  # 保留旧字段（已废弃）
        "project_fit_tags": _json_loads(item.project_fit_tags_json, []),  # 保留旧字段（已废弃）
        "selection_score": item.selection_score,
        "status": item.status,
        "citations": _json_loads(item.citations_json, []),
        "raw_payload": _json_loads(item.raw_payload_json, {}),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }



def create_material_item(db: Session, payload: dict[str, Any]) -> MaterialItem:
    """创建素材项（同时写入旧字段和新字段，保持向后兼容）"""
    # 提取并合并标签（新字段）
    structure_tags = payload.get("structure_tags") or []
    style_tags = payload.get("style_tags") or []
    project_fit_tags = payload.get("project_fit_tags") or []
    # 合并去重
    merged_tags = list(dict.fromkeys(structure_tags + style_tags + project_fit_tags))
    project_tags_json = _json_dumps(merged_tags, [])

    item = MaterialItem(
        source_platform=str(payload.get("source_platform") or "unknown"),
        source_url=str(payload.get("source_url") or ""),
        content_type=str(payload.get("content_type") or "短剧"),
        title=str(payload.get("title") or "未命名素材"),
        summary=str(payload.get("summary") or ""),
        heat_score=float(payload.get("heat_score") or 0.0),
        heat_reason=str(payload.get("heat_reason") or ""),
        data_points_json=_json_dumps(payload.get("data_points"), []),
        structure_tags_json=_json_dumps(payload.get("structure_tags"), []),
        style_tags_json=_json_dumps(payload.get("style_tags"), []),
        project_fit_tags_json=_json_dumps(payload.get("project_fit_tags"), []),
        project_tags_json=project_tags_json,  # 新字段
        selection_score=float(payload.get("selection_score") or 0.0),
        status=str(payload.get("status") or "candidate"),
        citations_json=_json_dumps(payload.get("citations"), []),
        raw_payload_json=_json_dumps(payload.get("raw_payload"), {}),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_material_status(db: Session, item_id: str, status: str) -> MaterialItem:
    item = db.query(MaterialItem).filter(MaterialItem.id == item_id).first()
    if not item:
        raise ValueError(f"素材 {item_id} 不存在")
    item.status = status
    db.commit()
    db.refresh(item)
    return item


def list_material_items(
    db: Session,
    status: str | None = None,
    content_type: str | None = None,
    source_platform: str | None = None,
    limit: int = 50,
) -> list[MaterialItem]:
    query = db.query(MaterialItem)
    if status:
        query = query.filter(MaterialItem.status == status)
    if content_type:
        query = query.filter(MaterialItem.content_type == content_type)
    if source_platform:
        query = query.filter(MaterialItem.source_platform == source_platform)
    return query.order_by(MaterialItem.selection_score.desc(), MaterialItem.created_at.desc()).limit(limit).all()


def _material_issue_bias(payload: dict[str, Any], issue_feedback: dict[str, Any] | None = None) -> float:
    issue_feedback = issue_feedback or {}
    retrieval_bias = issue_feedback.get("retrieval_bias") or {}
    score = 0.0
    summary = str(payload.get("summary") or "")
    borrow_points = [str(item).strip() for item in ((payload.get("raw_payload") or {}).get("borrow_points") or []) if str(item).strip()]
    risk_points = [str(item).strip() for item in ((payload.get("raw_payload") or {}).get("risk_points") or []) if str(item).strip()]

    prefer_points = set(str(item).strip() for item in (retrieval_bias.get("prefer_borrow_points") or []) if str(item).strip())
    if prefer_points:
        score += sum(4 for item in borrow_points if any(point in item for point in prefer_points))
    if retrieval_bias.get("avoid_summary_like") and any(token in summary for token in {"概括", "总结", "主题", "核心", "表达", "结构启发"}):
        score -= 10
    if retrieval_bias.get("avoid_generic_risk") and any(token in risk for risk in risk_points for token in {"泛化", "空泛", "总结", "保守"}):
        score -= 6
    return score



def select_project_materials(
    db: Session,
    *,
    content_type: str = "短剧",
    project_tags: list[str] | None = None,
    limit: int = 3,
    issue_feedback: dict[str, Any] | None = None,
    category_path: str | None = None,
) -> list[dict[str, Any]]:
    project_tags = [str(tag).strip() for tag in (project_tags or []) if str(tag).strip()]
    if category_path:
        project_tags = list(dict.fromkeys(project_tags + [str(category_path).strip()]))
    items = list_material_items(db, status="approved", content_type=content_type, limit=50)
    scored: list[tuple[float, MaterialItem]] = []
    for item in items:
        payload = material_to_dict(item)
        # 使用统一project_tags（已合并structure+style+project_fit）
        project_tags_set = set(payload.get("project_tags") or [])
        # 项目适配标签权重12，结构标签权重6
        fit_tags = set(payload.get("project_fit_tags") or [])
        structure_tags = set(payload.get("structure_tags") or [])
        overlap = len(fit_tags.intersection(project_tags)) * 12 + len(structure_tags.intersection(project_tags)) * 6
        score = float(payload.get("selection_score") or 0) + overlap + _material_issue_bias(payload, issue_feedback)
        scored.append((score, item))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [material_to_dict(item) for _, item in scored[:limit]]


def score_material_candidate(payload: dict[str, Any]) -> float:
    """
    计算素材入库筛选分（使用统一评分服务 + 热度趋势优化）

    规则：
    - 热度分 = min(heat_score, 100) * 0.35
    - 数据点加分 = min(len(data_points), 5) * 6
    - 结构标签加分 = min(len(structure_tags), 6) * 5
    - 项目适配加分 = min(len(project_fit_tags), 5) * 4
    - 引用数量加分 = min(citation_count, 5) * 3
    - 摘要长度>=80: +8
    - 热门赛道标签: +10
    - 热度新鲜度（7天内+5，30天内+2）
    - 总分截断[0, 100]
    """
    from app.services.scoring_service import calculate_score
    from datetime import datetime, timedelta

    heat_score = float(payload.get("heat_score") or 0.0)
    data_points = payload.get("data_points") or []
    structure_tags = payload.get("structure_tags") or []
    project_fit_tags = payload.get("project_fit_tags") or []
    citation_count = len(payload.get("citations") or [])
    summary = str(payload.get("summary") or "")

    # 基础分（统一评分服务）
    result = calculate_score(
        "material_selection",
        heat_score=heat_score,
        data_points=data_points,
        structure_tags=structure_tags,
        project_fit_tags=project_fit_tags,
        citation_count=citation_count,
        summary=summary,
    )
    base_score = result["score"]

    # 热度新鲜度加成
    bonus = 0.0
    created_at = payload.get("created_at") or payload.get("raw_payload", {}).get("created_at")
    if created_at:
        try:
            if isinstance(created_at, str):
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                created = created_at
            age_days = (datetime.now() - created).days
            if age_days <= 7:
                bonus += 5.0
            elif age_days <= 30:
                bonus += 2.0
        except Exception:
            pass

    # 平台热度加权（主流平台额外+3）
    platform = str(payload.get("source_platform") or payload.get("raw_payload", {}).get("platform", ""))
    hot_platforms = {"红果", "抖音", "快手", "微信", "novelquickapp", "zhihu", "bilibili"}
    if any(p in platform for p in hot_platforms):
        bonus += 3.0

    final_score = min(100.0, base_score + bonus)
    return round(final_score, 2)


def refine_material_payload(raw_item: dict[str, Any], content_type: str = "短剧") -> dict[str, Any]:
    title = str(raw_item.get("title") or "").strip()
    summary = str(raw_item.get("summary") or "").strip()
    tags = [str(tag).strip() for tag in (raw_item.get("tags") or []) if str(tag).strip()]
    heat_reason = str(raw_item.get("heat_reason") or "").strip()
    data_points = raw_item.get("data_points") or []
    source_platform = str(raw_item.get("source_platform") or raw_item.get("source") or "unknown")
    source_url = str(raw_item.get("source_url") or raw_item.get("url") or "")
    citations = [str(item).strip() for item in (raw_item.get("citations") or []) if str(item).strip()]
    project_fit_tags = [tag for tag in tags if tag in {"校园", "系统", "逆袭", "追妻火葬场", "悬疑", "女性成长", "男频", "女频", "漫剧", "横屏"}]
    structure_tags = [tag for tag in tags if tag not in {"男频", "女频"}][:8]
    style_tags = [str(raw_item.get("style_hint") or "").strip()] if raw_item.get("style_hint") else []

    # 合并标签
    merged_tags = list(dict.fromkeys(structure_tags + style_tags + project_fit_tags))
    project_tags_json = _json_dumps(merged_tags, [])

    payload = {
        "source_platform": source_platform,
        "source_url": source_url,
        "content_type": content_type,
        "title": title,
        "summary": summary,
        "heat_score": float(raw_item.get("heat_score") or raw_item.get("heat") or 0.0),
        "heat_reason": heat_reason or "基于平台热度、标签密度与结构特征综合评估。",
        "data_points": data_points,
        "structure_tags": structure_tags,
        "style_tags": style_tags,
        "project_fit_tags": project_fit_tags,
        "project_tags": merged_tags,  # 统一标签
        "citations": citations,
        "raw_payload": raw_item,
    }
    payload["selection_score"] = score_material_candidate(payload)
    payload["status"] = "approved" if payload["selection_score"] >= APPROVAL_THRESHOLD else "candidate"
    return payload


def check_material_duplicate(db: Session, new_summary: str, threshold: float = 0.75) -> list[dict[str, Any]]:
    """
    检测新素材是否与已有素材重复（使用 funnlp-skill 文本相似度）

    Args:
        db: 数据库会话
        new_summary: 新素材摘要
        threshold: 相似度阈值（0-1），默认0.75

    Returns:
        重复嫌疑素材列表，每项包含 {id, title, similarity, is_duplicate}
    """
    if not FUNNLP_AVAILABLE:
        return []  # funnlp 未安装，跳过查重

    if not new_summary or not new_summary.strip():
        return []

    existing = list_material_items(db, status="approved", limit=50)
    duplicates = []

    for item in existing:
        existing_summary = item.summary or ""
        if not existing_summary:
            continue

        try:
            result = detect_similar_segments(new_summary, existing_summary, threshold=threshold)
            if result.get("is_duplicate"):
                duplicates.append({
                    "id": item.id,
                    "title": item.title,
                    "similarity": result.get("similarity", 0.0),
                    "is_duplicate": True,
                })
        except Exception:
            # 单条检测失败不影响整体
            continue

    return duplicates


def analyze_live_material(raw_item: dict[str, Any], content_type: str = "短剧") -> dict[str, Any]:
    base_payload = refine_material_payload(raw_item, content_type=content_type)
    if not generation_enabled():
        return base_payload

    prompt_payload = {
        "title": base_payload["title"],
        "summary": base_payload["summary"],
        "citations": base_payload["citations"],
        "source_platform": base_payload["source_platform"],
        "content_type": base_payload["content_type"],
        "existing_tags": (base_payload.get("structure_tags") or []) + (base_payload.get("project_fit_tags") or []),
        "existing_data_points": base_payload.get("data_points") or [],
    }
    system_prompt = (
        "你是影视爆款素材分析器。"
        "只做结构化提炼，不发明不存在的数据，不自动上升为底层规则。"
        "输出必须是 JSON 对象。"
    )
    user_prompt = (
        "请根据输入提炼适合写作素材库入库的结构化结果。"
        "输出字段必须包含：summary、heat_reason、data_points、structure_tags、style_tags、project_fit_tags、borrow_points、risk_points。"
        "要求：1) data_points 为字符串数组或对象数组；2) structure_tags/style_tags/project_fit_tags 各不超过 8 项；"
        "3) borrow_points/risk_points 各不超过 5 项；4) 不要把素材结论写成正式规则。\n\n"
        f"输入：{prompt_payload}"
    )
    try:
        analyzed = generate_json(system_prompt, user_prompt, temperature=0.2)
    except Exception:
        return base_payload

    merged_raw_payload = dict(base_payload.get("raw_payload") or {})
    merged_raw_payload["borrow_points"] = analyzed.get("borrow_points") or []
    merged_raw_payload["risk_points"] = analyzed.get("risk_points") or []
    merged_raw_payload["analysis"] = analyzed
    merged_payload = {
        **base_payload,
        "summary": str(analyzed.get("summary") or base_payload.get("summary") or ""),
        "heat_reason": str(analyzed.get("heat_reason") or base_payload.get("heat_reason") or ""),
        "data_points": analyzed.get("data_points") or base_payload.get("data_points") or [],
        "structure_tags": analyzed.get("structure_tags") or base_payload.get("structure_tags") or [],
        "style_tags": analyzed.get("style_tags") or base_payload.get("style_tags") or [],
        "project_fit_tags": analyzed.get("project_fit_tags") or base_payload.get("project_fit_tags") or [],
        "raw_payload": merged_raw_payload,
    }
    merged_payload["selection_score"] = score_material_candidate(merged_payload)
    merged_payload["status"] = "approved" if merged_payload["selection_score"] >= APPROVAL_THRESHOLD else "candidate"
    return merged_payload
