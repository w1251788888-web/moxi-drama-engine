"""
验收成果写入服务
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.enum.text import WD_BREAK
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.module import Module
from app.models.reward_log import RewardLog
from app.models.review_record import ReviewRecord
from app.models.sub_task import SubTask
from app.models.task import Task
from app.services import workspace_service

# 外部工具 Skill 导入
try:
    from skills.docwen_skill.docwen_cli import md2docx
    DOCWEN_AVAILABLE = True
except ImportError:
    DOCWEN_AVAILABLE = False


ACCEPTANCE_ARTIFACT_DIR = workspace_service.acceptance_artifacts_root()
DESKTOP_ACCEPTANCE_DIR = ACCEPTANCE_ARTIFACT_DIR


def write_task_acceptance_artifact(db: Session, task_id: str) -> Path:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    metadata = _parse_metadata(task.metadata_json)
    if metadata.get("lab_type") in {"short_drama_market_alignment", "custom_short_drama_alignment"}:
        return _write_short_drama_lab_artifact(db, task, metadata)

    modules = db.query(Module).filter(Module.task_id == task_id).order_by(Module.created_at.asc()).all()
    sub_tasks = db.query(SubTask).filter(SubTask.task_id == task_id).order_by(SubTask.created_at.asc()).all()
    reviews = db.query(ReviewRecord).join(SubTask, SubTask.id == ReviewRecord.sub_task_id).filter(SubTask.task_id == task_id).order_by(ReviewRecord.created_at.asc()).all()
    rewards = db.query(RewardLog).join(SubTask, SubTask.id == RewardLog.sub_task_id).filter(SubTask.task_id == task_id).order_by(RewardLog.created_at.asc()).all()
    logs = db.query(ActivityLog).join(SubTask, SubTask.id == ActivityLog.sub_task_id).filter(SubTask.task_id == task_id).order_by(ActivityLog.created_at.asc()).all()

    return _write_artifact(
        task=task,
        title="任务验收成果",
        sections=[
            _section("任务概览", [
                f"任务名称: {task.name}",
                f"任务状态: {task.status}",
                f"任务类型: {task.type}",
                f"任务说明: {task.description or '无'}",
                f"模块数量: {len(modules)}",
                f"子任务数量: {len(sub_tasks)}",
                f"已完成数量: {sum(1 for item in sub_tasks if item.status == 'done')}",
                f"完成时间: {task.updated_at.strftime('%Y-%m-%d %H:%M:%S') if task.updated_at else '未记录'}",
            ]),
            _section(
                "模块清单",
                [
                    f"- {module.name} | {module.description or '无说明'}"
                    for module in modules
                ] or ["- 无"],
            ),
            _section(
                "已完成子任务",
                [
                    f"- {sub_task.name} | 状态 {sub_task.status} | 交付物 {sub_task.deliverable or '无'}"
                    for sub_task in sub_tasks
                    if sub_task.status == 'done'
                ] or ["- 无"],
            ),
            _section(
                "审查记录",
                [
                    f"- 轮次 {review.round} | 子任务 {review.sub_task_id[:8]} | 结果 {review.result} | 评分 {review.score}"
                    for review in reviews
                ] or ["- 无"],
            ),
            _section(
                "积分记录",
                [
                    f"- {reward.reason} | 分值 {reward.score_delta} | 子任务 {reward.sub_task_id[:8] if reward.sub_task_id else '无'}"
                    for reward in rewards
                ] or ["- 无"],
            ),
            _section(
                "活动日志",
                [
                    f"- {log.action} | {log.summary}"
                    for log in logs
                ] or ["- 无"],
            ),
        ],
    )


def write_sub_task_acceptance_artifact(db: Session, sub_task_id: str) -> Path:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")

    task = db.query(Task).filter(Task.id == sub_task.task_id).first()
    module = db.query(Module).filter(Module.id == sub_task.module_id).first() if sub_task.module_id else None
    review = (
        db.query(ReviewRecord)
        .filter(ReviewRecord.sub_task_id == sub_task_id)
        .order_by(ReviewRecord.created_at.desc())
        .first()
    )
    reward_logs = (
        db.query(RewardLog)
        .filter(RewardLog.sub_task_id == sub_task_id)
        .order_by(RewardLog.created_at.asc())
        .all()
    )
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.sub_task_id == sub_task_id)
        .order_by(ActivityLog.created_at.asc())
        .all()
    )

    return _write_artifact(
        task=task,
        title=f"子任务验收成果 - {sub_task.name}",
        sections=[
            _section("子任务概览", [
                f"子任务名称: {sub_task.name}",
                f"子任务状态: {sub_task.status}",
                f"所属任务: {task.name if task else '未知'}",
                f"所属模块: {module.name if module else '未绑定'}",
                f"优先级: {sub_task.priority}",
                f"交付物: {sub_task.deliverable or '无'}",
                f"验收标准: {sub_task.acceptance or '无'}",
                f"完成时间: {sub_task.completed_at.strftime('%Y-%m-%d %H:%M:%S') if sub_task.completed_at else '未记录'}",
            ]),
            _section(
                "审查结果",
                [
                    f"- 轮次 {review.round} | 结果 {review.result} | 评分 {review.score}"
                    if review
                    else "- 无",
                ],
            ),
            _section(
                "积分记录",
                [
                    f"- {reward.reason} | 分值 {reward.score_delta}"
                    for reward in reward_logs
                ] or ["- 无"],
            ),
            _section(
                "活动日志",
                [
                    f"- {log.action} | {log.summary}"
                    for log in logs
                ] or ["- 无"],
            ),
        ],
    )


def _write_short_drama_lab_artifact(db: Session, task: Task, metadata: dict[str, Any]) -> Path:
    modules = db.query(Module).filter(Module.task_id == task.id).order_by(Module.created_at.asc()).all()
    sub_tasks = db.query(SubTask).filter(SubTask.task_id == task.id).order_by(SubTask.created_at.asc()).all()
    reviews = db.query(ReviewRecord).join(SubTask, SubTask.id == ReviewRecord.sub_task_id).filter(SubTask.task_id == task.id).order_by(ReviewRecord.created_at.asc()).all()
    logs = db.query(ActivityLog).join(SubTask, SubTask.id == ActivityLog.sub_task_id).filter(SubTask.task_id == task.id).order_by(ActivityLog.created_at.asc()).all()

    rounds = metadata.get("rounds") or []
    best_sample = metadata.get("best_sample") or {}
    market_logic = metadata.get("market_logic") or {}
    source_payload = metadata.get("source_payload") or {}
    platform_taxonomy = metadata.get("platform_taxonomy") or market_logic.get("platform_taxonomy") or {}
    hot_category_summary = metadata.get("hot_category_summary") or market_logic.get("hot_category_summary") or []
    sample_titles = metadata.get("sample_titles") or market_logic.get("sample_titles") or []
    benchmarks = market_logic.get("benchmarks") or []
    benchmark = next(
        (
            item
            for item in benchmarks
            if f"{item.get('big_category', '')} / {item.get('sub_category', '')}" == (best_sample.get("track") or metadata.get("current_track"))
        ),
        benchmarks[0] if benchmarks else {},
    )

    ordered_sub_tasks = sorted(sub_tasks, key=lambda item: _sequence_key(_parse_metadata(item.metadata_json).get("sequence")))
    return _write_short_drama_lab_docx(
        task=task,
        metadata=metadata,
        market_logic=market_logic,
        benchmark=benchmark,
        best_sample=best_sample,
        rounds=rounds,
        ordered_sub_tasks=ordered_sub_tasks,
        reviews=reviews,
        logs=logs,
    )


def _write_artifact(task: Task | None, title: str, sections: list[str]) -> Path:
    acceptance_dir = workspace_service.ensure_acceptance_artifacts_root()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = _sanitize_name(task.name if task else title)
    if task:
        file_name = f"{base_name}-验收-{timestamp}.txt"
    else:
        file_name = f"{_sanitize_name(title)}-{timestamp}.txt"

    content = "\n\n".join([f"# {title}"] + sections) + "\n"

    # 使用 docwen-skill 转换为 DOCX（如果可用）
    if DOCWEN_AVAILABLE:
        try:
            md_path = workspace_service.artifact_path(f"{base_name}-验收-{timestamp}.md", root=acceptance_dir)
            md_path.write_text(content, encoding="utf-8")
            docx_path = md2docx(str(md_path), template="acceptance")
            return docx_path
        except Exception as e:
            import logging
            logging.warning(f"docwen转换失败，回退到txt: {e}")

    # 降级：直接写txt
    artifact_path = workspace_service.artifact_path(file_name, root=acceptance_dir)
    artifact_path.write_text(content, encoding="utf-8")
    return artifact_path


def _write_short_drama_lab_docx(
    task: Task,
    metadata: dict[str, Any],
    market_logic: dict[str, Any],
    benchmark: dict[str, Any],
    best_sample: dict[str, Any],
    rounds: list[dict[str, Any]],
    ordered_sub_tasks: list[SubTask],
    reviews: list[ReviewRecord],
    logs: list[ActivityLog],
) -> Path:
    acceptance_dir = workspace_service.ensure_acceptance_artifacts_root()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file_name = f"{_sanitize_name(task.name)}-验收-{timestamp}.docx"
    artifact_path = workspace_service.artifact_path(file_name, root=acceptance_dir)

    document = Document()
    document.add_heading("短剧市场对标实验室验收文档", level=0)
    document.add_paragraph(f"任务名称：{task.name}")
    document.add_paragraph(f"任务状态：{task.status}")
    document.add_paragraph(f"实验类型：{metadata.get('lab_type') or 'short_drama_market_alignment'}")
    document.add_paragraph(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    platform_taxonomy = metadata.get("platform_taxonomy") or market_logic.get("platform_taxonomy") or {}
    hot_category_summary = metadata.get("hot_category_summary") or market_logic.get("hot_category_summary") or []
    sample_titles = metadata.get("sample_titles") or market_logic.get("sample_titles") or []
    story_bible = metadata.get("story_bible") or {}
    outline_backfill = metadata.get("outline_backfill") or {}
    material_candidates = metadata.get("material_candidates") or []
    selected_materials = metadata.get("selected_materials") or []
    workflow_optimization_report = metadata.get("workflow_optimization_report") or {}
    rule_upgrade_suggestions = metadata.get("rule_upgrade_suggestions") or []
    issue_snapshot = metadata.get("issue_snapshot") or {}
    issue_records = metadata.get("issue_records") or []

    # 如未提供 workflow_optimization_report，则实时生成
    if not workflow_optimization_report:
        try:
            from app.services.reflection_service import generate_workflow_optimization_report
            db_for_reflection = SessionLocal()
            workflow_optimization_report = generate_workflow_optimization_report(
                db_for_reflection,
                task_ids=[task.id],
            )
            db_for_reflection.close()
        except Exception:
            workflow_optimization_report = {
                "token_saving_actions": [],
                "effective_steps": [],
                "redundant_steps": [],
                "observations": ["反思服务不可用"],
                "next_actions": [],
            }

    _add_doc_heading(document, "一、市场底层逻辑定位", level=1)
    _add_doc_kv(document, "大类赛道", "、".join(market_logic.get("big_categories") or []) or "无")
    _add_doc_kv(document, "小类赛道", "、".join(market_logic.get("sub_categories") or []) or "无")
    _add_doc_kv(document, "市场摘要", market_logic.get("summary") or "无")
    _add_doc_kv(document, "最终命中赛道", best_sample.get("track") or metadata.get("current_track") or "未记录")

    _add_doc_heading(document, "二、平台来源与分类画像", level=1)
    _add_doc_kv(document, "学习平台", platform_taxonomy.get("platform_name") or metadata.get("source_platform") or "无")
    _add_doc_kv(document, "来源标识", metadata.get("source_platform") or platform_taxonomy.get("source_key") or "无")
    _add_doc_kv(document, "来源地址", metadata.get("source_url") or platform_taxonomy.get("source_url") or "无")
    hot_signal = platform_taxonomy.get("hot_signal") or {}
    _add_doc_kv(document, "热度入口", f"{hot_signal.get('dimension') or '推荐'} -> {' / '.join(hot_signal.get('priority') or []) or '无'}")
    _add_doc_kv(document, "学习目标", hot_signal.get("primary_learning_target") or "最热")
    _add_doc_bullets(document, "内容类型", platform_taxonomy.get("content_types") or ["无"])
    dimensions = platform_taxonomy.get("dimensions") or {}
    _add_doc_bullets(document, "背景维度", dimensions.get("背景") or ["无"])
    _add_doc_bullets(document, "主题维度", dimensions.get("主题") or ["无"])
    _add_doc_bullets(document, "设定维度", dimensions.get("设定") or ["无"])
    _add_doc_bullets(document, "受众维度", dimensions.get("受众") or ["无"])
    _add_doc_bullets(document, "平台最热分类结论", hot_category_summary or ["无"])
    _add_doc_bullets(document, "首批学习样本", sample_titles or ["无"])

    _add_doc_heading(document, "三、用户底层逻辑拆解", level=1)
    source_payload = metadata.get("source_payload") or {}
    project_brief = source_payload.get("project_brief") or {}
    meme_logic = metadata.get("meme_logic") or source_payload.get("meme_logic") or {}
    season_arc = metadata.get("season_arc") or source_payload.get("season_arc") or []
    _add_doc_kv(document, "原稿路径", metadata.get("source_doc_path") or source_payload.get("source_doc_path") or "无")
    _add_doc_kv(document, "原稿摘要", metadata.get("source_summary") or source_payload.get("source_summary") or "无")
    _add_doc_kv(document, "项目标题", project_brief.get("title") or task.name)
    _add_doc_kv(document, "题材标签", "、".join(project_brief.get("genres") or []) or "无")
    _add_doc_kv(document, "赛季总纲", "；".join(f"第{item.get('season')}季-{item.get('goal')}" for item in season_arc) or "无")
    _add_doc_bullets(document, "IP核", benchmark.get("ip_core") or ["无"])
    _add_doc_bullets(document, "单元策略", [benchmark.get("unit_strategy") or "无"])
    _add_doc_bullets(document, "结构规则", benchmark.get("structure_rules") or ["无"])
    _add_doc_bullets(document, "表达规则", benchmark.get("expression_rules") or ["无"])
    _add_doc_bullets(document, "嘉豪梗定义", [meme_logic.get("definition") or "无"])
    _add_doc_bullets(document, "嘉豪核心动作", meme_logic.get("core_behaviors") or ["无"])
    _add_doc_bullets(document, "嘉豪写作用途", meme_logic.get("writing_use") or ["无"])
    _add_doc_bullets(document, "对标特征", best_sample.get("accepted_features") or benchmark.get("benchmark_features") or ["无"])
    _add_doc_bullets(document, "修补焦点", benchmark.get("patch_focus") or ["无"])

    if story_bible:
        _add_doc_heading(document, "四、前置设定层（故事圣经）", level=1)
        _add_doc_kv(document, "构建模式", story_bible.get("mode") or "无")
        _add_doc_kv(document, "项目标题", story_bible.get("title") or project_brief.get("title") or task.name)
        _add_doc_bullets(
            document,
            "角色库",
            [
                f"{item.get('name') or '未命名'}｜身份 {item.get('identity') or '无'}｜目标 {item.get('goal') or '无'}｜弱点 {item.get('weakness') or '无'}｜弧线 {item.get('arc') or '无'}｜来源 {item.get('source') or '无'}"
                for item in (story_bible.get("character_bible") or [])
            ] or ["无"],
        )
        world_bible = story_bible.get("world_bible") or {}
        _add_doc_kv(document, "世界观设定", world_bible.get("setting") or "无")
        _add_doc_bullets(document, "世界规则", world_bible.get("rules") or ["无"])
        _add_doc_bullets(document, "世界约束", world_bible.get("constraints") or ["无"])
        golden_finger = story_bible.get("golden_finger_bible") or {}
        _add_doc_bullets(
            document,
            "金手指库",
            [
                f"存在：{golden_finger.get('exists', False)}",
                f"来源：{golden_finger.get('origin') or '无'}",
                f"触发：{golden_finger.get('trigger') or '无'}",
                f"收益：{golden_finger.get('benefit') or '无'}",
                f"代价：{golden_finger.get('cost') or '无'}",
                f"升级路径：{golden_finger.get('upgrade_path') or '无'}",
                f"来源标记：{golden_finger.get('source') or '无'}",
            ],
        )
        _add_doc_bullets(
            document,
            "关系矩阵",
            [
                f"{item.get('pair') or '未命名关系'}｜当前 {item.get('current_state') or '无'}｜上限 {item.get('ceiling') or '无'}｜冲突 {item.get('conflict') or '无'}｜来源 {item.get('source') or '无'}"
                for item in (story_bible.get("relationship_matrix") or [])
            ] or ["无"],
        )
        conflict_map = story_bible.get("conflict_map") or {}
        _add_doc_kv(document, "主线冲突", conflict_map.get("main_conflict") or "无")
        _add_doc_bullets(document, "阶段冲突", conflict_map.get("stage_conflicts") or ["无"])
        _add_doc_bullets(document, "反派压力", conflict_map.get("antagonist_pressure") or ["无"])
        _add_doc_bullets(
            document,
            "大纲回写",
            [
                f"标题：{outline_backfill.get('title') or '无'}",
                f"人物补写：{outline_backfill.get('characters') or '无'}",
                f"世界观补写：{outline_backfill.get('world') or '无'}",
                f"核心设定补写：{outline_backfill.get('core_setting') or '无'}",
            ],
        )

    _add_doc_heading(document, "五、内部测试循环与收敛", level=1)
    for item in rounds or [{}]:
        round_no = item.get("round", "?")
        document.add_paragraph(f"第{round_no}轮", style="Heading 2")
        _add_doc_kv(document, "评分", str(item.get("score", "未记录")))
        _add_doc_kv(document, "通过", str(item.get("passed", False)))
        _add_doc_bullets(document, "命中项", item.get("strengths") or ["无"])
        _add_doc_bullets(document, "缺陷项", item.get("defects") or ["无"])
        _add_doc_bullets(document, "补丁方案", [item.get("patch_summary") or "无"])
        _add_doc_bullets(document, "重跑原因", [item.get("rerun_reason") or "无"])
    _add_doc_kv(document, "最终收敛说明", metadata.get("final_summary") or "无")

    if material_candidates:
        _add_doc_heading(document, "六、素材候选与精选入库", level=1)
        _add_doc_bullets(
            document,
            "素材候选",
            [
                f"{item.get('title') or '未命名'}｜平台 {item.get('source_platform') or '无'}｜类型 {item.get('content_type') or '无'}｜筛选分 {item.get('selection_score') or 0}｜状态 {item.get('status') or 'candidate'}｜热度原因 {item.get('heat_reason') or '无'}"
                for item in material_candidates
            ] or ["无"],
        )
        if selected_materials:
            _add_doc_bullets(
                document,
                "本次生成实际召回素材",
                [
                    f"{item.get('title') or '未命名素材'}｜结构 {'、'.join(item.get('structure_tags') or []) or '无'}｜借鉴 {'；'.join(item.get('borrow_points') or []) or '无'}｜风险 {'；'.join(item.get('risk_points') or []) or '无'}"
                    for item in selected_materials
                ] or ["无"],
            )

    if workflow_optimization_report:
        _add_doc_heading(document, "七、流程优化复盘", level=1)
        _add_doc_bullets(document, "省 token 动作", workflow_optimization_report.get("token_saving_actions") or ["无"])
        _add_doc_bullets(document, "有效步骤", workflow_optimization_report.get("effective_steps") or ["无"])
        _add_doc_bullets(document, "冗余步骤", workflow_optimization_report.get("redundant_steps") or ["无"])
        _add_doc_bullets(document, "观察结论", workflow_optimization_report.get("observations") or ["无"])
        _add_doc_bullets(document, "后续动作", workflow_optimization_report.get("next_actions") or ["无"])

    if issue_snapshot or issue_records:
        _add_doc_heading(document, "八、问题清单反哺结果", level=1)
        _add_doc_kv(document, "分类路径", metadata.get("project_category_path") or issue_snapshot.get("category_path") or "无")
        _add_doc_kv(document, "问题反馈摘要", metadata.get("issue_feedback_summary") or issue_snapshot.get("summary") or "无")
        _add_doc_bullets(document, "评审检查清单", metadata.get("issue_review_checklist") or issue_snapshot.get("review_checklist") or ["无"])
        retrieval_bias = metadata.get("issue_retrieval_bias") or issue_snapshot.get("retrieval_bias") or {}
        _add_doc_bullets(document, "召回偏置说明", [
            f"偏好借鉴点：{'、'.join(retrieval_bias.get('prefer_borrow_points') or []) or '无'}",
            f"避免总结化：{retrieval_bias.get('avoid_summary_like', False)}",
            f"避免泛风险提示：{retrieval_bias.get('avoid_generic_risk', False)}",
        ])
        _add_doc_bullets(
            document,
            "本项目沉淀问题",
            [
                f"{item.get('title') or '未命名问题'}｜级别 {item.get('scope_level') or 'project_only'}｜出现 {item.get('occurrence_count') or 1} 次｜症状 {item.get('symptom') or '无'}"
                for item in issue_records
            ] or ["无"],
        )

    if rule_upgrade_suggestions:
        _add_doc_heading(document, "九、规则升级建议（候选）", level=1)
        _add_doc_bullets(
            document,
            "候选建议",
            [
                f"范围 {item.get('scope') or '无'}｜状态 {item.get('status') or 'candidate'}｜来源 {item.get('source') or '无'}｜内容 {item.get('content') or '无'}"
                for item in rule_upgrade_suggestions
            ] or ["无"],
        )

    _add_doc_heading(document, "十、执行顺序与过程可视化", level=1)
    for sub_task in ordered_sub_tasks:
        meta = _parse_metadata(sub_task.metadata_json)
        title = f"{meta.get('sequence') or '-'}｜{sub_task.name}"
        document.add_paragraph(title, style="Heading 2")
        _add_doc_kv(document, "状态", sub_task.status)
        _add_doc_kv(document, "阶段", meta.get("module_stage") or "未记录")
        _add_doc_kv(document, "轮次", str(meta.get("round") or "-"))
        _add_doc_kv(document, "通过", str(meta.get("passed", "未判定")))
        _add_doc_bullets(document, "缺陷", meta.get("defects") or ["无"])
        _add_doc_bullets(document, "优势", meta.get("strengths") or ["无"])
        _add_doc_bullets(document, "补丁", [meta.get("patch_summary") or "无"])
        _add_doc_bullets(document, "重跑原因", [meta.get("rerun_reason") or "无"])
        _add_doc_bullets(document, "命中特征", meta.get("accepted_features") or ["无"])
        _add_doc_bullets(document, "过程摘要", [meta.get("sample_preview") or "无"])

    _add_doc_heading(document, "十一、第一季60集规划与最优样稿验收版", level=1)
    _add_doc_kv(document, "样稿标题", best_sample.get("title") or "未命名样稿")
    _add_doc_kv(document, "样稿概括", best_sample.get("summary") or "无")
    _add_doc_kv(document, "预览摘要", best_sample.get("sample_preview") or "无")
    _add_doc_kv(document, "60集规划摘要", best_sample.get("season_plan_summary") or "无")
    _add_doc_kv(document, "感情线推进", best_sample.get("romance_progress") or "无")
    _add_doc_kv(document, "校园打脸密度", best_sample.get("campus_face_slap_density") or "无")
    _add_doc_bullets(document, "嘉豪梗命中点", best_sample.get("meme_hit_points") or ["无"])
    _add_doc_bullets(document, "命中 benchmark 特征", best_sample.get("accepted_features") or ["无"])
    season_plan_lines = _build_season_plan_lines(best_sample.get("season_plan") or metadata.get("season_plan") or [])
    _add_doc_bullets(document, "第一季60集规划", season_plan_lines or ["无"])

    chapter_titles = best_sample.get("chapter_titles") or ["误伤开局", "抽离反噬", "翻面追击"]
    for index, chapter in enumerate(best_sample.get("chapters") or [], start=1):
        chapter_name = chapter_titles[index - 1] if index - 1 < len(chapter_titles) else f"第{index}章"
        document.add_paragraph(f"第{index}章《{chapter_name}》", style="Heading 2")
        for block in chapter.split("\n\n"):
            cleaned = block.strip()
            if cleaned:
                document.add_paragraph(cleaned)
        if index < len(best_sample.get("chapters") or []):
            document.paragraphs[-1].runs[-1].add_break(WD_BREAK.PAGE)

    rewrite_episodes = best_sample.get("rewrite_episodes") or metadata.get("rewrite_episodes") or []
    if rewrite_episodes:
        _add_doc_heading(document, "十二、第5-10集逐集重写与决策验收", level=1)
        _add_doc_kv(document, "重写生成模式", best_sample.get("rewrite_generation_mode") or best_sample.get("generation_mode") or "无")
        _add_doc_kv(document, "重写规则依据", best_sample.get("rewrite_rule_basis") or best_sample.get("rule_basis") or "无")
        _add_doc_kv(document, "重写摘要", metadata.get("rewrite_summary") or best_sample.get("rewrite_preview") or "无")
        rewrite_error = best_sample.get("rewrite_error") or ""
        if rewrite_error:
            _add_doc_kv(document, "重写错误", rewrite_error)

        for item in rewrite_episodes:
            document.add_paragraph(f"第{item.get('episode', '?')}集《{item.get('title') or '未命名'}》", style="Heading 2")
            _add_doc_kv(document, "是否通过", str(item.get("passed", False)))
            _add_doc_kv(document, "轮次", str(item.get("attempts", 0)))
            _add_doc_kv(document, "评分", str(item.get("score", "未记录")))
            _add_doc_kv(document, "集概括", item.get("summary") or item.get("decision_comment") or "无")
            _add_doc_bullets(document, "优势", item.get("strengths") or ["无"])
            _add_doc_bullets(document, "问题", item.get("defects") or ["无"])
            _add_doc_bullets(document, "补丁", [item.get("patch_summary") or "无"])
            _add_doc_bullets(document, "重跑原因", [item.get("rerun_reason") or "无"])
            rule_checks = item.get("rule_checks") or {}
            if rule_checks:
                _add_doc_bullets(document, "规则核查", [f"{key}: {value}" for key, value in rule_checks.items()])
            history = item.get("history") or []
            if history:
                _add_doc_bullets(
                    document,
                    "多轮记录",
                    [
                        f"第{entry.get('attempt', '?')}轮｜评分 {entry.get('score', '未记录')}｜决策 {entry.get('decision', '未记录')}｜问题 {('；'.join(entry.get('defects') or []) or '无')}｜补丁 {entry.get('patch_summary') or '无'}"
                        for entry in history
                    ],
                )
            body = item.get("body") or ""
            for block in body.split("\n\n"):
                cleaned = block.strip()
                if cleaned:
                    document.add_paragraph(cleaned)
            document.add_paragraph("")

    _add_doc_heading(document, "十二、审查与活动记录", level=1)
    _add_doc_bullets(
        document,
        "审查记录",
        [
            f"第{review.round}轮｜结果 {review.result}｜评分 {review.score}｜问题 {review.issues or '无'}｜意见 {review.comment or '无'}"
            for review in reviews
        ] or ["无"],
    )
    _add_doc_bullets(
        document,
        "活动日志",
        [f"{log.action}｜{log.summary}" for log in logs] or ["无"],
    )

    document.save(artifact_path)
    return artifact_path


def _build_round_lines(rounds: list[dict[str, Any]]) -> list[str]:
    round_lines: list[str] = []
    for item in rounds:
        defects = "；".join(item.get("defects") or []) or "无"
        strengths = "；".join(item.get("strengths") or []) or "无"
        round_lines.extend([
            f"- 第{item.get('round', '?')}轮 | 评分 {item.get('score', '未记录')} | 通过 {item.get('passed', False)}",
            f"  缺陷: {defects}",
            f"  命中: {strengths}",
            f"  补丁: {item.get('patch_summary') or '无'}",
            f"  重跑原因: {item.get('rerun_reason') or '无'}",
        ])
    return round_lines or ["- 无"]


def _build_chapter_lines(best_sample: dict[str, Any]) -> list[str]:
    chapter_lines = []
    for index, chapter in enumerate(best_sample.get("chapters") or [], start=1):
        chapter_lines.append(f"第{index}章")
        chapter_lines.append(chapter)
        chapter_lines.append("")
    return chapter_lines or ["暂无前三章正文。"]


def _build_season_plan_lines(season_plan: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for arc in season_plan:
        lines.append(
            f"- 第{arc.get('start_episode', '?')}-{arc.get('end_episode', '?')}集｜{arc.get('arc_title', '未命名段落')}｜目标 {arc.get('goal', '无')}｜钩子 {arc.get('hook', '无')}"
        )
    return lines or ["暂无第一季60集规划。"]


def _add_doc_heading(document: Document, title: str, level: int = 1) -> None:
    document.add_paragraph(title, style=f"Heading {level}")


def _add_doc_kv(document: Document, label: str, value: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.add_run(f"{label}：").bold = True
    paragraph.add_run(value)


def _add_doc_bullets(document: Document, label: str, items: list[str]) -> None:
    document.add_paragraph(label)
    for item in items:
        document.add_paragraph(str(item), style="List Bullet")


def _sequence_key(sequence: str | None) -> tuple[int, ...]:
    if not sequence:
        return (9999,)
    values: list[int] = []
    for part in str(sequence).split("."):
        try:
            values.append(int(part))
        except ValueError:
            values.append(9999)
    return tuple(values)


def _section(header: str, lines: Iterable[str]) -> str:
    return "\n".join([header, "-" * len(header), *lines])


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", value).strip()
    return cleaned or "untitled"


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}
