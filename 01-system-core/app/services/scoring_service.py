"""
统一评分服务 — 集中管理OpenMOSS各场景的评分计算

设计目标：
- 统一评分维度与权重
- 消除分散的评分逻辑
- 支持配置化调整
"""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass


@dataclass
class ScoringConfig:
    """评分配置基类"""
    base_score: float = 100.0
    min_score: float = 40.0
    max_score: float = 98.0


# ============================================================
# 剧本对齐评分（short_drama_lab_service.score_script_alignment）
# ============================================================
SCRIPT_ALIGNMENT_CONFIG = ScoringConfig(
    base_score=100.0,
    min_score=40.0,
    max_score=98.0,
)

def calculate_script_alignment_score(defects: list[str], strengths: list[str]) -> dict[str, Any]:
    """
    计算剧本对齐评分

    规则：
    - 基础分100
    - 每个缺陷扣12分
    - 每个优点加4分（上限12分）
    - 最终分截断在[40, 98]
    - 通过条件：缺陷<=1且轮次>=2

    Returns:
        {
            "score": 85.0,
            "passed": bool,
            "defect_count": len(defects),
            "strength_count": len(strengths),
            "breakdown": {
                "base": 100,
                "defect_penalty": -24,
                "strength_bonus": 8,
            }
        }
    """
    defect_count = len(defects or [])
    strength_count = len(strengths or [])

    raw_score = 100 - defect_count * 12 + min(strength_count * 4, 12)
    final_score = max(SCRIPT_ALIGNMENT_CONFIG.min_score, min(raw_score, SCRIPT_ALIGNMENT_CONFIG.max_score))

    passed = defect_count <= 1  # 根据原逻辑：缺陷<=1且round>=2（round由调用方传入）

    return {
        "score": round(final_score, 2),
        "passed": passed,
        "defect_count": defect_count,
        "strength_count": strength_count,
        "breakdown": {
            "base": 100.0,
            "defect_penalty": -defect_count * 12,
            "strength_bonus": min(strength_count * 4, 12.0),
        },
    }


# ============================================================
# 单集重写评分（short_drama_lab_service.score_episode_rewrite_alignment）
# ============================================================
EPISODE_REWRITE_CONFIG = ScoringConfig(
    base_score=92.0,
    min_score=40.0,
    max_score=98.0,
)

def calculate_episode_rewrite_score(defects: list[str], strengths: list[str]) -> dict[str, Any]:
    """
    计算单集重写对齐评分

    规则：
    - 基础分92
    - 每个缺陷扣10分
    - 每个优点加3分（上限9分）
    - 最终分截断在[40, 98]
    """
    defect_count = len(defects or [])
    strength_count = len(strengths or [])

    raw_score = 92 - defect_count * 10 + min(strength_count * 3, 9)
    final_score = max(EPISODE_REWRITE_CONFIG.min_score, min(raw_score, EPISODE_REWRITE_CONFIG.max_score))

    passed = defect_count == 0  # 根据原逻辑：decision=="pass"且无缺陷

    return {
        "score": round(final_score, 2),
        "passed": passed,
        "defect_count": defect_count,
        "strength_count": strength_count,
        "breakdown": {
            "base": 92.0,
            "defect_penalty": -defect_count * 10,
            "strength_bonus": min(strength_count * 3, 9.0),
        },
    }


# ============================================================
# 素材候选评分（material_library_service.score_material_candidate）
# ============================================================
MATERIAL_SELECTION_CONFIG = {
    "heat_weight": 0.35,        # 热度权重
    "data_points_weight": 6,    # 数据点权重（每项）
    "structure_tags_weight": 5, # 结构标签权重（每项）
    "project_fit_weight": 4,    # 项目适配权重（每项）
    "citation_weight": 3,       # 引用数量权重（每项）
    "summary_bonus": 8,         # 摘要长度>=80的加分
    "hot_track_bonus": 10,      # 热门赛道加分
    "hot_track_tags": {"校园", "系统", "逆袭", "追妻火葬场", "悬疑", "女性成长"},
}

def calculate_material_selection_score(
    heat_score: float,
    data_points: list,
    structure_tags: list,
    project_fit_tags: list,
    citation_count: int,
    summary: str,
) -> dict[str, Any]:
    """
    计算素材入库筛选分

    规则：
    - 热度分 = min(heat_score, 100) * 0.35
    - 数据点加分 = min(len(data_points), 5) * 6
    - 结构标签加分 = min(len(structure_tags), 6) * 5
    - 项目适配加分 = min(len(project_fit_tags), 5) * 4
    - 引用数量加分 = min(citation_count, 5) * 3
    - 摘要长度>=80: +8
    - 热门赛道标签: +10
    - 总分截断[0, 100]
    """
    cfg = MATERIAL_SELECTION_CONFIG

    score = 0.0
    score += min(heat_score, 100.0) * cfg["heat_weight"]
    score += min(len(data_points or []), 5) * cfg["data_points_weight"]
    score += min(len(structure_tags or []), 6) * cfg["structure_tags_weight"]
    score += min(len(project_fit_tags or []), 5) * cfg["project_fit_weight"]
    score += min(citation_count, 5) * cfg["citation_weight"]

    breakdown = {
        "heat_component": round(min(heat_score, 100.0) * cfg["heat_weight"], 2),
        "data_points_component": round(min(len(data_points or []), 5) * cfg["data_points_weight"], 2),
        "structure_tags_component": round(min(len(structure_tags or []), 6) * cfg["structure_tags_weight"], 2),
        "project_fit_component": round(min(len(project_fit_tags or []), 5) * cfg["project_fit_weight"], 2),
        "citation_component": round(min(citation_count, 5) * cfg["citation_weight"], 2),
    }

    if len(summary or "") >= 80:
        score += cfg["summary_bonus"]
        breakdown["summary_bonus"] = cfg["summary_bonus"]

    # 热门赛道检测
    tags_set = set(project_fit_tags or [])
    hot_match = tags_set & cfg["hot_track_tags"]
    if hot_match:
        score += cfg["hot_track_bonus"]
        breakdown["hot_track_bonus"] = cfg["hot_track_bonus"]
        breakdown["matched_hot_tags"] = list(hot_match)

    final_score = round(min(score, 100.0), 2)

    return {
        "score": final_score,
        "breakdown": breakdown,
        "passed": final_score >= 75.0,  # APPROVAL_THRESHOLD
    }


# ============================================================
# 审查质量评分（reward_service.apply_review_score）
# ============================================================
REVIEW_QUALITY_RULES = {
    5: {"delta": +5, "label": "超出预期"},
    4: {"delta": +5, "label": "完全达标"},
    3: {"delta": 0,  "label": "基本达标"},
    2: {"delta": -5, "label": "部分不足"},
    1: {"delta": -5, "label": "严重不足"},
}


def calculate_review_score(score: int) -> dict[str, Any]:
    """
    根据审查评分返回积分变化

    Args:
        score: 审查分数1-5

    Returns:
        {
            "delta": +5/-5/0,
            "label": "超出预期"/"完全达标"/...,
            "should_record": bool  # 是否写入积分记录（3分不记录）
        }
    """
    rule = REVIEW_QUALITY_RULES.get(score, {"delta": 0, "label": "未知评分"})
    should_record = rule["delta"] != 0  # 3分delta为0，不记录

    return {
        "delta": rule["delta"],
        "label": rule["label"],
        "should_record": should_record,
    }


# ============================================================
# 统一评分入口
# ============================================================
SCORING_DIMENSIONS = {
    "script_alignment": SCRIPT_ALIGNMENT_CONFIG,
    "episode_rewrite": EPISODE_REWRITE_CONFIG,
    "material_selection": MATERIAL_SELECTION_CONFIG,
    "review_quality": REVIEW_QUALITY_RULES,
}


def calculate_score(score_type: str, **kwargs) -> dict[str, Any]:
    """
    统一评分计算入口

    Usage:
        # 剧本对齐
        result = calculate_score("script_alignment", defects=[...], strengths=[...])

        # 素材筛选
        result = calculate_score("material_selection", heat_score=85, data_points=[...], ...)

        # 审查评分
        result = calculate_score("review_quality", score=4)

    Returns:
        根据score_type返回对应的评分结果字典
    """
    if score_type == "script_alignment":
        return calculate_script_alignment_score(
            defects=kwargs.get("defects", []),
            strengths=kwargs.get("strengths", []),
        )
    elif score_type == "episode_rewrite":
        return calculate_episode_rewrite_score(
            defects=kwargs.get("defects", []),
            strengths=kwargs.get("strengths", []),
        )
    elif score_type == "material_selection":
        return calculate_material_selection_score(
            heat_score=kwargs.get("heat_score", 0.0),
            data_points=kwargs.get("data_points", []),
            structure_tags=kwargs.get("structure_tags", []),
            project_fit_tags=kwargs.get("project_fit_tags", []),
            citation_count=kwargs.get("citation_count", 0),
            summary=kwargs.get("summary", ""),
        )
    elif score_type == "review_quality":
        return calculate_review_score(kwargs.get("score", 3))
    else:
        raise ValueError(f"未知评分类型: {score_type}. 支持: {list(SCORING_DIMENSIONS.keys())}")
