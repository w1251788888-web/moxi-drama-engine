"""
反思分析服务

分析 issue_feedback、review rounds、activity logs，输出结构化的工作流优化报告。
用于持续改进 OpenMOSS 的生成质量与效率。

与 acceptance_artifact_service.py 配合，将优化报告写入验收文档的「流程优化复盘」章节。
"""
from __future__ import annotations

from typing import Any
from collections import Counter
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.review_record import ReviewRecord
from app.models.sub_task import SubTask
from app.models.task import Task
from app.services.issue_feedback_service import build_issue_feedback_snapshot, build_issue_rule_suggestions


# ============================================================
# 优化洞察提取
# ============================================================

def analyze_workflow_reflection(
    db: Session,
    task_id: str,
    rounds_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    分析单次任务的工作流反思数据

    Args:
        db: 数据库会话
        task_id: 任务 ID
        rounds_data: 轮次数据（可选，不传则从数据库读取）

    Returns:
        {
            "task_id": str,
            "generated_at": str,
            "token_saving_actions": [...],
            "effective_steps": [...],
            "redundant_steps": [...],
            "observations": [...],
            "next_actions": [...],
            "issue_summary": {...},
            "rule_suggestions": [...]
        }
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {"error": f"任务 {task_id} 不存在"}

    # 收集基础数据
    sub_tasks = db.query(SubTask).filter(SubTask.task_id == task_id).order_by(SubTask.created_at.asc()).all()
    reviews = db.query(ReviewRecord).join(SubTask).filter(SubTask.task_id == task_id).order_by(ReviewRecord.created_at.asc()).all()
    logs = db.query(ActivityLog).join(SubTask).filter(SubTask.task_id == task_id).order_by(ActivityLog.created_at.asc()).all()

    # 1. 轮次效率分析
    rounds_analysis = _analyze_rounds_efficiency(rounds_data or _extract_rounds_from_subtasks(sub_tasks, reviews))

    # 2. 审查意见聚类
    review_insights = _cluster_review_insights(reviews)

    # 3. 活动日志模式识别
    activity_patterns = _detect_activity_patterns(logs)

    # 4. Issue 反馈总结
    from app.models.issue_record import IssueRecord
    # 从 task.metadata_json 中提取 category_path
    import json
    category_path = ""
    try:
        task_meta = json.loads(task.metadata_json or "{}")
        category_path = task_meta.get("project_category_path", "")
    except Exception:
        category_path = ""
    issue_snapshot = build_issue_feedback_snapshot(db, category_path)
    issue_records = db.query(IssueRecord).filter(IssueRecord.task_id == task_id).all()
    issue_suggestions = build_issue_rule_suggestions(issue_records)

    # 5. Token 节省机会识别
    token_savings = _identify_token_savings(sub_tasks, reviews, rounds_analysis)

    # 6. 冗余步骤检测
    redundancy = _detect_redundant_steps(sub_tasks, activity_patterns)

    # 7. 有效步骤识别
    effective_steps = _identify_effective_steps(sub_tasks, rounds_analysis, review_insights)

    # 8. 观察结论生成
    observations = _generate_observations(rounds_analysis, review_insights, activity_patterns, issue_snapshot)

    # 9. 后续动作建议
    next_actions = _generate_next_actions(observations, issue_suggestions, redundancy)

    return {
        "task_id": task_id,
        "task_name": task.name,
        "generated_at": datetime.now().isoformat(),
        "token_saving_actions": token_savings,
        "effective_steps": effective_steps,
        "redundant_steps": redundancy,
        "observations": observations,
        "next_actions": next_actions,
        "issue_summary": issue_snapshot,
        "rule_suggestions": issue_suggestions,
        "stats": {
            "sub_task_count": len(sub_tasks),
            "review_count": len(reviews),
            "log_count": len(logs),
            "round_count": len(rounds_data or []),
        },
    }


# ============================================================
# 辅助分析函数
# ============================================================

def _extract_rounds_from_subtasks(sub_tasks: list[SubTask], reviews: list[ReviewRecord]) -> list[dict[str, Any]]:
    """从子任务和审查记录中提取轮次数据"""
    rounds_map = {}
    for st in sub_tasks:
        meta = st.metadata_json or "{}"
        import json
        try:
            md = json.loads(meta)
            round_no = md.get("round")
            if round_no is not None:
                if round_no not in rounds_map:
                    rounds_map[round_no] = {"round": round_no, "score": None, "passed": None, "defects": [], "strengths": []}
                rounds_map[round_no].update(md)
        except Exception:
            pass

    # 用 review 补全 score/passed（ReviewRecord 没有 metadata_json，直接使用字段）
    for rv in reviews:
        round_no = rv.round
        if round_no is not None and round_no in rounds_map:
            rounds_map[round_no]["score"] = rv.score
            rounds_map[round_no]["passed"] = rv.result == "pass"
            # 将 issues 加入 defects
            if rv.issues:
                rounds_map[round_no]["defects"].extend([i.strip() for i in rv.issues.split(";") if i.strip()])

    return [rounds_map[k] for k in sorted(rounds_map.keys())]


def _analyze_rounds_efficiency(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """分析轮次效率：收敛速度、分数提升、缺陷减少趋势"""
    if not rounds:
        return {"trend": "unknown", "converged": False, "score_delta": 0}

    scores = [r.get("score", 0) for r in rounds if r.get("score") is not None]
    defects_counts = [len(r.get("defects", [])) for r in rounds]

    # 分数趋势
    score_trend = "stable"
    if len(scores) >= 2:
        if scores[-1] > scores[0]:
            score_trend = "improving"
        elif scores[-1] < scores[0]:
            score_trend = "declining"

    # 是否收敛（最后两轮分数变化<5分）
    converged = False
    if len(scores) >= 2:
        converged = abs(scores[-1] - scores[-2]) < 5

    # 缺陷变化趋势
    defect_trend = "stable"
    if len(defects_counts) >= 2:
        if defects_counts[-1] < defects_counts[0]:
            defect_trend = "decreasing"
        elif defects_counts[-1] > defects_counts[0]:
            defect_trend = "increasing"

    return {
        "trend": score_trend,
        "converged": converged,
        "score_delta": scores[-1] - scores[0] if scores else 0,
        "defect_trend": defect_trend,
        "round_count": len(rounds),
        "scores": scores,
        "defects_per_round": defects_counts,
    }


def _cluster_review_insights(reviews: list[ReviewRecord]) -> dict[str, Any]:
    """对审查意见进行聚类，提取高频问题点"""
    if not reviews:
        return {"top_issues": [], "issue_frequency": {}}

    all_issues = []
    for rv in reviews:
        issues = (rv.issues or "").split(";")
        all_issues.extend([i.strip() for i in issues if i.strip()])

    counter = Counter(all_issues)
    top_issues = [{"issue": issue, "count": count} for issue, count in counter.most_common(5)]

    return {
        "top_issues": top_issues,
        "issue_frequency": dict(counter),
        "total_issues": len(all_issues),
    }


def _detect_activity_patterns(logs: list[ActivityLog]) -> dict[str, Any]:
    """识别活动日志中的模式：高频操作、等待时间、串行/并行"""
    if not logs:
        return {}

    action_counts = Counter(log.action for log in logs)
    # 识别串行等待：planning 后紧跟 execution 的时间间隔中位数
    time_diffs = []
    for i in range(1, len(logs)):
        if logs[i-1].action == "planning" and logs[i].action == "execution":
            if logs[i-1].timestamp and logs[i].timestamp:
                diff = (logs[i].timestamp - logs[i-1].timestamp).total_seconds()
                time_diffs.append(diff)

    median_wait = sorted(time_diffs)[len(time_diffs)//2] if time_diffs else None

    return {
        "action_distribution": dict(action_counts),
        "median_planning_execution_gap_sec": median_wait,
        "most_frequent_action": action_counts.most_common(1)[0] if action_counts else None,
    }


def _identify_token_savings(sub_tasks: list[SubTask], reviews: list[ReviewRecord], rounds_analysis: dict) -> list[str]:
    """识别可能的 token 节省机会"""
    savings = []

    # 检查重复生成：多轮中相似提示词
    prompts = []
    for st in sub_tasks:
        meta = st.metadata_json or "{}"
        import json
        try:
            md = json.loads(meta)
            prompt = md.get("prompt", "") or md.get("user_prompt", "")
            if prompt:
                prompts.append((st.id, prompt[:100]))  # 取前100字符比较
        except Exception:
            pass

    # 简单的重复检测（前100字符相同）
    prompt_texts = [p[1] for p in prompts]
    dupes = [p for p in prompts if prompt_texts.count(p[1]) > 1]
    if dupes:
        savings.append(f"发现 {len(dupes)//2} 个重复生成任务，可合并或复用")

    # 检查多轮审查的重复问题
    rounds_defects = rounds_analysis.get("defects_per_round", [])
    if len(rounds_defects) >= 2 and all(d == rounds_defects[0] for d in rounds_defects):
        savings.append("连续多轮缺陷未减少，可调整审查策略或提前结束")

    # 检查是否过度审查
    review_per_subtask = len(reviews) / len(sub_tasks) if sub_tasks else 0
    if review_per_subtask > 2:
        savings.append(f"平均每子任务审查次数{review_per_subtask:.1f}过高，考虑降低轮次")

    return savings


def _detect_redundant_steps(sub_tasks: list[SubTask], activity_patterns: dict) -> list[str]:
    """检测冗余步骤"""
    redundant = []

    # 检查是否有子任务无交付物
    no_deliverables = [st for st in sub_tasks if not st.deliverable]
    if no_deliverables:
        redundant.append(f"{len(no_deliverables)} 个子任务无交付物，可删除或合并")

    # 检查 action 分布：某个 action 占比过高（如 planning 过多）
    action_dist = activity_patterns.get("action_distribution", {})
    total = sum(action_dist.values()) if action_dist else 0
    if total > 0:
        for action, count in action_dist.items():
            if count / total > 0.5 and action in ("planning", "blocked"):
                redundant.append(f"动作 '{action}' 占比 {count/total:.1%}，流程可能过于碎片化")

    return redundant


def _identify_effective_steps(sub_tasks: list[SubTask], rounds_analysis: dict, review_insights: dict) -> list[str]:
    """识别有效步骤（质量高、效率好的环节）"""
    effective = []

    # 快速收敛
    if rounds_analysis.get("converged"):
        round_count = rounds_analysis.get("round_count", 0)
        if round_count <= 2:
            effective.append("快速收敛（2轮内通过）")

    # 缺陷持续下降
    defect_trend = rounds_analysis.get("defect_trend")
    if defect_trend == "decreasing":
        effective.append("缺陷持续下降，修复策略有效")

    # 高频问题的正面表现
    top_issues = review_insights.get("top_issues", [])
    if not top_issues:
        effective.append("无高频问题，审查质量高")

    # 子任务完成率
    completed = sum(1 for st in sub_tasks if st.status == "done")
    completion_rate = completed / len(sub_tasks) if sub_tasks else 0
    if completion_rate >= 0.9:
        effective.append(f"子任务完成率高（{completion_rate:.1%}）")

    return effective


def _generate_observations(
    rounds_analysis: dict,
    review_insights: dict,
    activity_patterns: dict,
    issue_snapshot: dict,
) -> list[str]:
    """生成观察结论"""
    observations = []

    # 轮次分析观察
    if rounds_analysis.get("trend") == "improving":
        observations.append("评分呈上升趋势，迭代方向正确")
    elif rounds_analysis.get("trend") == "declining":
        observations.append("评分下降，需检查补丁方向是否合理")

    # 缺陷观察
    top_issues = review_insights.get("top_issues", [])
    if top_issues:
        top3 = "、".join(item["issue"] for item in top_issues[:3])
        observations.append(f"高频问题：{top3}")

    # Issue 反馈观察
    summary = issue_snapshot.get("summary", "")
    if summary:
        observations.append(f"Issue反馈摘要：{summary[:100]}")

    # 等待时间观察
    median_wait = activity_patterns.get("median_planning_execution_gap_sec")
    if median_wait and median_wait > 5:
        observations.append(f"规划到执行的等待时间较长（中位数{median_wait:.0f}秒）")

    # 默认观察
    if not observations:
        observations.append("未发现明显异常，流程运行平稳")

    return observations


def _generate_next_actions(
    observations: list[str],
    issue_suggestions: list[dict],
    redundant_steps: list[str],
) -> list[str]:
    """生成后续动作建议"""
    actions = []

    # 基于冗余步骤
    for r in redundant_steps:
        actions.append(f"【移除冗余】{r}")

    # 基于 Issue 建议
    for sug in issue_suggestions[:3]:
        content = sug.get("content", "")
        if content:
            actions.append(f"【规则升级】{content[:80]}")

    # 基于观察
    for obs in observations:
        if "等待时间" in obs:
            actions.append("【效率优化】考虑并行化规划与执行步骤")
        elif "评分下降" in obs:
            actions.append("【方向修正】重新评估当前赛道规则与样稿匹配度")

    # 默认建议
    if not actions:
        actions.append("维持当前流程，继续收集反馈")

    return actions


# ============================================================
# 批量分析（供外部调用）
# ============================================================

def generate_workflow_optimization_report(
    db: Session,
    task_ids: list[str] | None = None,
    days_back: int = 7,
) -> dict[str, Any]:
    """
    生成跨任务的工作流优化报告

    Args:
        db: 数据库会话
        task_ids: 指定任务ID列表，为空则取最近 N 天的任务
        days_back: 回溯天数

    Returns:
        {
            "period": str,
            "task_count": int,
            "common_issues": [...],
            "suggested_rule_upgrades": [...],
            "efficiency_trends": {...}
        }
    """
    cutoff = datetime.now() - timedelta(days=days_back)

    query = db.query(Task)
    if task_ids:
        query = query.filter(Task.id.in_(task_ids))
    else:
        query = query.filter(Task.created_at >= cutoff)

    tasks = query.all()

    all_observations = []
    all_actions = []
    all_savings = []
    all_redundant = []
    issue_counter = Counter()

    for task in tasks:
        reflection = analyze_workflow_reflection(db, task.id)
        all_observations.extend(reflection.get("observations", []))
        all_actions.extend(reflection.get("next_actions", []))
        all_savings.extend(reflection.get("token_saving_actions", []))
        all_redundant.extend(reflection.get("redundant_steps", []))

        # 收集 issue
        issue_summary = reflection.get("issue_summary", {})
        for rec in issue_summary.get("records", []):
            issue_counter[rec.get("normalized_issue", "unknown")] += 1

    # 聚合
    common_issues = [{"issue": i, "count": c} for i, c in issue_counter.most_common(10)]

    return {
        "period": f"{cutoff.date()} ~ {datetime.now().date()}",
        "task_count": len(tasks),
        "common_issues": common_issues,
        "frequent_token_savings": list(set(all_savings)),
        "frequent_redundancies": list(set(all_redundant)),
        "suggested_next_actions": list(set(all_actions))[:10],
        "aggregated_observations": list(set(all_observations)),
    }
