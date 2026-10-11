"""
任务/模块/子任务一键创建服务
"""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.issue_record import IssueRecord
from app.models.review_record import ReviewRecord
from app.models.sub_task import SubTask
from app.models.task import Task
from app.services import sub_task_service, task_service
from app.services.acceptance_artifact_service import write_task_acceptance_artifact
from app.services.acceptance_criteria_service import run_acceptance_checks
from app.services.short_drama_lab_service import (
    CUSTOM_CAMPUS_TRACK_KEY,
    DEFAULT_TRACK_KEY,
    build_custom_campus_sample_payload,
    build_dynamic_custom_campus_rewrite_payload,
    build_dynamic_custom_campus_sample_payload,
    build_final_summary,
    build_internal_test_plan,
    build_market_logic_report,
    build_patch_summary,
    build_platform_taxonomy_report,
    build_rerun_reason,
    build_round_defects,
    build_round_strengths,
    build_sample_payload,
    dumps_metadata,
    score_script_alignment,
    generate_chapters_with_ai,
)
from app.services.market_insight_service import recommend_topics
from app.services.story_bible_service import build_story_bible, merge_outline_with_backfill
from app.services.story_source_service import load_story_source
from app.services.material_library_service import (
    analyze_live_material,
    create_material_item,
    material_to_dict,
    refine_material_payload,
    select_project_materials,
)
from app.services.rule_service import create_rule
from app.services.telemetry_service import log_timeline_event, log_skill_usage, log_learning
from app.services.issue_feedback_service import (
    build_category_context,
    build_issue_feedback_snapshot,
    build_issue_rule_suggestions,
    extract_round_issue_candidates,
    issue_to_dict,
    upsert_issue_records,
)


DEFAULT_SCENE_TEMPLATE = [
    {
        "name": "市场验证",
        "description": "先扫描外部热榜和已有数据源，筛出可爆款题材。",
        "deliverable": "推荐题材列表、热度分析、风险提示",
        "acceptance": "给出可执行的推荐题材和改写建议",
    },
    {
        "name": "题目生成",
        "description": "围绕推荐题材生成多组爆款标题。",
        "deliverable": "标题候选集",
        "acceptance": "标题短、准、狠，能一眼看出冲突或关系",
    },
    {
        "name": "大纲生成",
        "description": "为推荐题材生成短剧大纲。",
        "deliverable": "分集或阶段性大纲",
        "acceptance": "有开场、冲突、升级、钩子",
    },
    {
        "name": "梗概生成",
        "description": "把核心冲突压缩成可读梗概。",
        "deliverable": "梗概文本",
        "acceptance": "清楚说明主角目标、阻碍和代价",
    },
    {
        "name": "角色库生成",
        "description": "生成核心角色库与关系张力。",
        "deliverable": "角色库",
        "acceptance": "至少 4 个角色，目标、弱点、说话风格明确",
    },
]


LAB_MODULE_TEMPLATE = [
    {
        "name": "市场赛道归纳",
        "description": "归纳大类、小类与对应剧本概括，建立赛道 benchmark。",
        "sub_tasks": [
            {
                "name": "1. 市场赛道地图",
                "description": "整理市场常见短剧大类、小类与剧本概括。",
                "deliverable": "大类/小类/剧本概括清单",
                "acceptance": "至少覆盖核心热门赛道并能区分表达差异",
            },
            {
                "name": "2. 头部结构特征",
                "description": "提炼各赛道头部作品的结构、钩子、表达形式。",
                "deliverable": "赛道 benchmark 特征表",
                "acceptance": "能直接指导 IP/单元/剧本生成",
            },
        ],
    },
    {
        "name": "写作逻辑生成",
        "description": "生成 IP、单元剧与赛道化写作底层逻辑。",
        "sub_tasks": [
            {
                "name": "3. IP 逻辑卡",
                "description": "生成 IP核、关系引擎、情绪主轴与延展点。",
                "deliverable": "IP 逻辑卡",
                "acceptance": "每个赛道都有明确 IP核与复用资产",
            },
            {
                "name": "4. 单元逻辑卡",
                "description": "生成主线+单元或纯单元结构模板。",
                "deliverable": "单元逻辑卡",
                "acceptance": "能解释每类短剧怎么拆单元、怎么留钩子",
            },
            {
                "name": "5. 分类规则覆盖",
                "description": "检查大类/小类/剧本概括是否覆盖市场常见类型。",
                "deliverable": "分类覆盖报告",
                "acceptance": "分类清晰、无主要热赛道遗漏",
            },
        ],
    },
    {
        "name": "内部测试循环",
        "description": "根据市场对标结构生成样稿、审查缺陷、补逻辑并重跑。",
        "sub_tasks": [
            {
                "name": "6. 第1轮样稿生成",
                "description": "按最新市场规则生成内部测试样稿。",
                "deliverable": "测试样稿",
                "acceptance": "样稿明确标注赛道、结构和表达方式",
            },
            {
                "name": "7. 第1轮结构评审",
                "description": "对标头部作品结构与表达形式做内部评审。",
                "deliverable": "缺陷清单与评分",
                "acceptance": "指出结构、IP、单元、表达上的缺口",
            },
            {
                "name": "8. 逻辑补丁与重跑",
                "description": "补写作逻辑缺陷并重新试跑，直到主要赛道对齐。",
                "deliverable": "补丁摘要与重跑记录",
                "acceptance": "能解释为什么重跑、补了什么、提升了什么",
            },
        ],
    },
    {
        "name": "最优样稿验收",
        "description": "输出最强样稿前三章及验收说明到桌面。",
        "sub_tasks": [
            {
                "name": "9. 最优样稿导出",
                "description": "导出一个最强样稿前三章和对标通过情况。",
                "deliverable": "桌面验收文件",
                "acceptance": "桌面可见验收文件，包含前三章与迭代说明",
            },
        ],
    },
]


CUSTOM_LAB_MODULE_TEMPLATE = [
    {
        "name": "平台分类与热门归纳",
        "description": "围绕平台分类页和推荐-最热入口，沉淀平台分类画像与热门赛道结论。",
        "sub_tasks": [
            {
                "name": "1. 平台分类抓取与归纳",
                "description": "整理平台的内容类型、背景、主题、设定、受众、时间与推荐维度。",
                "deliverable": "平台分类画像",
                "acceptance": "能明确说明平台一级维度与推荐-最热学习入口",
            },
            {
                "name": "2. 热门赛道结构提炼",
                "description": "从热门分类与样本标题提炼男频、女频、混合题材的热赛道规律。",
                "deliverable": "热赛道结构报告",
                "acceptance": "能指导底层规则与内部测试，不停留在标签罗列",
            },
        ],
    },
    {
        "name": "规则注入与链路更新",
        "description": "把平台学习结果写入 rules、steps 与执行 Agent，形成新的写作底层逻辑。",
        "sub_tasks": [
            {
                "name": "3. 底层规则升级",
                "description": "更新市场验证、男女频、质检与短剧核心规则。",
                "deliverable": "规则升级清单",
                "acceptance": "规则能明确映射平台热门分类与写法",
            },
            {
                "name": "4. 写作步骤注入",
                "description": "更新分集节拍、分场表、剧本初稿提示与执行 Agent。",
                "deliverable": "写作链路更新结果",
                "acceptance": "写作生产链能直接命中平台热分类观感",
            },
            {
                "name": "5. 分类覆盖校验",
                "description": "检查平台高频背景、主题、设定、受众是否都被底层逻辑吸收。",
                "deliverable": "分类覆盖报告",
                "acceptance": "无主要热分类遗漏，男频女频混合题材都有映射",
            },
        ],
    },
    {
        "name": "内部测试循环",
        "description": "按平台热赛道规则生成样稿、评审缺陷、补丁重跑直到通过。",
        "sub_tasks": [
            {
                "name": "6. 平台样稿生成",
                "description": "按当前平台最热赛道逻辑生成内部测试样稿。",
                "deliverable": "平台对标样稿",
                "acceptance": "样稿明确标注赛道、热分类命中与结构特征",
            },
            {
                "name": "7. 平台结构评审",
                "description": "检查样稿是否达到平台热门题材的结构、表达与钩子标准。",
                "deliverable": "缺陷清单与评分",
                "acceptance": "缺陷具体且能直接回填补丁",
            },
            {
                "name": "8. 逻辑补丁与重跑",
                "description": "补足平台对标缺陷并重新试跑，直到达到内部通过标准。",
                "deliverable": "补丁摘要与重跑记录",
                "acceptance": "至少保留一轮以上重跑痕迹，并说明提升点",
            },
        ],
    },
    {
        "name": "Word验收导出",
        "description": "把平台来源、分类画像、规则升级与最优样稿导出到桌面。",
        "sub_tasks": [
            {
                "name": "9. Word 验收件导出",
                "description": "导出包含平台来源、分类画像、规则升级项和内部测试结果的 Word 文档。",
                "deliverable": "桌面 Word 文档",
                "acceptance": "桌面可验收，文档清楚展示平台学习来源与收敛结果",
            },
        ],
    },
]


def create_market_validation_task(db: Session) -> dict[str, Any]:
    task = task_service.create_task(
        db,
        name="短剧市场验证与题材推荐",
        description="扫描市场热度信号，推荐最适合快速起量的短剧题材，并输出 starter pack。",
        type="once",
    )
    module = task_service.create_module(
        db,
        task_id=task.id,
        name="市场验证",
        description="题材热度扫描、爆款预测、推荐题材确认",
    )
    for index, item in enumerate(DEFAULT_SCENE_TEMPLATE, start=1):
        sub_task_service.create_sub_task(
            db,
            task_id=task.id,
            module_id=module.id,
            name=f"{index}. {item['name']}",
            description=item["description"],
            deliverable=item["deliverable"],
            acceptance=item["acceptance"],
            priority="high" if index == 1 else "medium",
        )
    return {
        "task": task,
        "module": module,
    }


def create_short_drama_lab_task(db: Session, task_name: str | None = None, task_description: str | None = None) -> dict[str, Any]:
    market_logic = build_market_logic_report()
    internal_test_plan = build_internal_test_plan()
    platform_taxonomy = build_platform_taxonomy_report()
    task = task_service.create_task(
        db,
        name=task_name or "短剧市场对标写作实验室",
        description=task_description or "根据平台热门分类生成短剧写作底层逻辑，内部测试样稿、补齐缺陷并循环重跑，最终导出最优样稿前三章验收结果。",
        type="once",
        metadata={
            "lab_type": "short_drama_market_alignment",
            "market_logic": market_logic,
            "internal_test_plan": internal_test_plan,
            "source_platform": platform_taxonomy["source_key"],
            "source_url": platform_taxonomy["source_url"],
            "platform_taxonomy": platform_taxonomy,
            "hot_category_summary": platform_taxonomy["hot_category_summary"],
            "sample_titles": [item["title"] for item in platform_taxonomy["sample_titles"]],
            "learn_from_hot_category": True,
            "current_track": DEFAULT_TRACK_KEY,
            "project_category_path": DEFAULT_TRACK_KEY,
            "project_category_labels": [DEFAULT_TRACK_KEY],
            "rounds": [],
            "best_sample": {},
            "issue_snapshot": {},
            "issue_feedback_summary": "当前分类暂无历史问题反馈。",
            "issue_review_checklist": [],
            "issue_retrieval_bias": {},
            "material_candidates": [],
            "workflow_optimization_report": {},
            "rule_upgrade_suggestions": [],
            "final_summary": "尚未启动基于平台热门分类的内部测试循环。",
        },
    )

    created_modules = []
    for module_index, module_item in enumerate(LAB_MODULE_TEMPLATE, start=1):
        module = task_service.create_module(
            db,
            task_id=task.id,
            name=f"{module_index}. {module_item['name']}",
            description=module_item["description"],
        )
        created_modules.append(module)
        for sub_index, sub_task in enumerate(module_item["sub_tasks"], start=1):
            sub_task_service.create_sub_task(
                db,
                task_id=task.id,
                module_id=module.id,
                name=sub_task["name"],
                description=sub_task["description"],
                deliverable=sub_task["deliverable"],
                acceptance=sub_task["acceptance"],
                priority="high" if module_index <= 2 else "medium",
                metadata={
                    "module_stage": module_item["name"],
                    "sequence": f"{module_index}.{sub_index}",
                    "loop_required": module_item["name"] == "内部测试循环",
                    "market_snapshot": dumps_metadata(market_logic) if module_index == 1 else "",
                },
            )

    return {
        "task": task,
        "modules": created_modules,
        "market_logic": market_logic,
        "internal_test_plan": internal_test_plan,
    }



def create_custom_short_drama_lab_task(
    db: Session,
    doc_path: str,
    task_name: str | None = None,
    task_description: str | None = None,
) -> dict[str, Any]:
    source_payload = load_story_source(doc_path)
    story_bible = build_story_bible(mode="extract_and_expand", source_payload=source_payload, project_name=task_name or source_payload["title"])
    outline_backfill = merge_outline_with_backfill(source_payload, story_bible)
    market_logic = build_market_logic_report()
    internal_test_plan = build_internal_test_plan()
    platform_taxonomy = build_platform_taxonomy_report()
    task = task_service.create_task(
        db,
        name=task_name or source_payload["title"],
        description=task_description or source_payload["source_summary"],
        type="once",
        metadata={
            "lab_type": "custom_short_drama_alignment",
            "source_doc_path": source_payload["source_doc_path"],
            "source_summary": source_payload["source_summary"],
            "source_payload": source_payload,
            "story_bible": story_bible,
            "outline_backfill": outline_backfill,
            "market_logic": market_logic,
            "internal_test_plan": internal_test_plan,
            "source_platform": platform_taxonomy["source_key"],
            "source_url": platform_taxonomy["source_url"],
            "platform_taxonomy": platform_taxonomy,
            "hot_category_summary": platform_taxonomy["hot_category_summary"],
            "sample_titles": [item["title"] for item in platform_taxonomy["sample_titles"]],
            "learn_from_hot_category": True,
            "current_track": CUSTOM_CAMPUS_TRACK_KEY,
            "project_category_path": CUSTOM_CAMPUS_TRACK_KEY,
            "project_category_labels": list(source_payload.get("project_brief", {}).get("genres") or []) + [CUSTOM_CAMPUS_TRACK_KEY],
            "season_arc": source_payload["season_arc"],
            "meme_logic": source_payload["meme_logic"],
            "season_plan": [],
            "rounds": [],
            "best_sample": {},
            "issue_snapshot": {},
            "issue_feedback_summary": "当前分类暂无历史问题反馈。",
            "issue_review_checklist": [],
            "issue_retrieval_bias": {},
            "material_candidates": [],
            "workflow_optimization_report": {},
            "rule_upgrade_suggestions": [],
            "final_summary": "尚未启动基于平台热门分类的定制实验。",
        },
    )

    created_modules = []
    for module_index, module_item in enumerate(CUSTOM_LAB_MODULE_TEMPLATE, start=1):
        module = task_service.create_module(
            db,
            task_id=task.id,
            name=f"{module_index}. {module_item['name']}",
            description=module_item["description"],
        )
        created_modules.append(module)
        for sub_index, sub_task in enumerate(module_item["sub_tasks"], start=1):
            sub_task_service.create_sub_task(
                db,
                task_id=task.id,
                module_id=module.id,
                name=sub_task["name"],
                description=sub_task["description"],
                deliverable=sub_task["deliverable"],
                acceptance=sub_task["acceptance"],
                priority="high" if module_index <= 2 else "medium",
                metadata={
                    "module_stage": module_item["name"],
                    "sequence": f"{module_index}.{sub_index}",
                    "loop_required": module_item["name"] == "内部测试循环",
                    "source_doc_path": source_payload["source_doc_path"] if module_index == 1 else "",
                },
            )

    return {
        "task": task,
        "modules": created_modules,
        "market_logic": market_logic,
        "internal_test_plan": internal_test_plan,
        "source_payload": source_payload,
    }


def execute_short_drama_lab_task(db: Session, task_id: str) -> dict[str, Any]:
    import time
    start_time = time.time()

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        log_learning(
            skill="short_drama_lab",
            insight_type="fix",
            key="task_not_found",
            insight=f"尝试执行不存在的任务: {task_id}",
            confidence=9,
        )
        raise ValueError(f"任务 {task_id} 不存在")

    task_metadata = _parse_metadata(task.metadata_json)
    fallback_metadata = getattr(task, "metadata", None)
    if not task_metadata.get("lab_type") and isinstance(fallback_metadata, dict):
        task_metadata = fallback_metadata
    lab_type = task_metadata.get("lab_type")
    if lab_type not in {"short_drama_market_alignment", "custom_short_drama_alignment"}:
        raise ValueError("当前任务不是短剧市场对标实验任务")

    is_custom_lab = lab_type == "custom_short_drama_alignment"
    track = task_metadata.get("current_track") or (CUSTOM_CAMPUS_TRACK_KEY if is_custom_lab else DEFAULT_TRACK_KEY)
    source_payload = task_metadata.get("source_payload") if is_custom_lab else None
    category_context = build_category_context(task_metadata, {"track": track})
    issue_snapshot = build_issue_feedback_snapshot(db, category_context["category_path"])
    task_metadata["project_category_path"] = category_context["category_path"]
    task_metadata["project_category_labels"] = category_context["category_labels"]
    task_metadata["issue_snapshot"] = issue_snapshot
    task_metadata["issue_feedback_summary"] = issue_snapshot.get("summary", "")
    task_metadata["issue_review_checklist"] = issue_snapshot.get("review_checklist", [])
    task_metadata["issue_retrieval_bias"] = issue_snapshot.get("retrieval_bias", {})
    project_tags = _build_project_material_tags(task_metadata)
    selected_materials = select_project_materials(
        db,
        content_type="短剧",
        project_tags=project_tags,
        limit=3,
        issue_feedback=issue_snapshot,
        category_path=category_context["category_path"],
    )
    sub_tasks = (
        db.query(SubTask)
        .filter(SubTask.task_id == task_id)
        .order_by(SubTask.created_at.asc())
        .all()
    )
    if not sub_tasks:
        raise ValueError("当前实验任务没有子任务，无法执行")

    system_agent = _get_or_create_system_agent(db)
    session_id = f"lab-{uuid.uuid4().hex[:8]}"

    task.status = "in_progress"
    db.commit()
    db.refresh(task)

    ordered_sub_tasks = sorted(sub_tasks, key=lambda item: _sequence_key(_parse_metadata(item.metadata_json).get("sequence")))
    for item in ordered_sub_tasks[:5]:
        _complete_setup_sub_task(db, item, track, session_id, system_agent.id)

    loop_tasks = ordered_sub_tasks[5:8]
    if len(loop_tasks) != 3:
        raise ValueError("内部测试循环子任务数量异常")
    draft_task, review_task, patch_task = loop_tasks
    export_task = ordered_sub_tasks[8] if len(ordered_sub_tasks) > 8 else None

    max_rounds = int((task_metadata.get("internal_test_plan") or {}).get("max_rounds") or 3)
    rounds: list[dict[str, Any]] = []
    best_sample: dict[str, Any] = {}
    previous_round_texts: list[str] = []

    for round_no in range(1, max_rounds + 1):
        sample = build_dynamic_custom_campus_sample_payload(round_no, source_payload, selected_materials) if is_custom_lab else build_sample_payload(track, round_no)
        sample = _inject_selected_materials(sample, selected_materials, issue_snapshot)
        defects = build_round_defects(track, round_no)
        strengths = build_round_strengths(track, round_no)
        chapters = sample.get("chapters") or []
        acceptance_checks = run_acceptance_checks(
            {
                "chapters": chapters if isinstance(chapters, list) else [],
                "summary": sample.get("summary") or "",
            },
            track=track,
            previous_episodes=list(previous_round_texts),
        )
        review_result = score_script_alignment(
            track,
            defects=defects,
            strengths=strengths,
            round_no=round_no,
            script_chapters=chapters,
        )
        review_result["acceptance_checks"] = acceptance_checks
        review_result["patch_summary"] = build_patch_summary(track, defects, round_no)
        review_result["rerun_reason"] = build_rerun_reason(defects, round_no)
        review_result["accepted_features"] = sample["accepted_features"]
        review_result["chapter_titles"] = sample["chapter_titles"]
        if is_custom_lab:
            review_result["season_plan_summary"] = sample.get("season_plan_summary", "")
            review_result["meme_hit_points"] = sample.get("meme_hit_points", [])
            review_result["romance_progress"] = sample.get("romance_progress", "")
            review_result["campus_face_slap_density"] = sample.get("campus_face_slap_density", "")
        rounds.append(review_result)

        round_text = "\n\n".join(str(item) for item in chapters) if isinstance(chapters, list) else ""
        if round_text.strip():
            previous_round_texts.append(round_text)

        sample_payload = {
            **sample,
            "score": review_result["score"],
            "passed": review_result["passed"],
            "strengths": strengths,
            "defects": defects,
            "selected_materials": sample.get("selected_materials", []),
            "acceptance_checks": acceptance_checks,
        }
        if not best_sample or review_result["score"] >= best_sample.get("score", 0):
            best_sample = sample_payload

        _run_round_generation(db, draft_task, round_no, sample_payload, review_result, session_id, system_agent.id)
        _run_round_review(db, review_task, round_no, review_result, sample_payload, session_id, system_agent.id, issue_snapshot.get("review_checklist", []))
        round_issue_candidates = extract_round_issue_candidates(task_metadata, review_result, best_sample)
        issue_records = upsert_issue_records(db, task, review_task, round_issue_candidates, category_context)
        issue_snapshot = build_issue_feedback_snapshot(db, category_context["category_path"])
        patch_sub_task = patch_task if not review_result["passed"] else (export_task or patch_task)
        _run_round_patch(db, patch_sub_task, round_no, review_result, sample_payload, session_id, system_agent.id)

        task_metadata = _parse_metadata(task.metadata_json)
        task_metadata["current_track"] = track
        task_metadata["market_logic"] = task_metadata.get("market_logic") or build_market_logic_report()
        task_metadata["platform_taxonomy"] = task_metadata.get("platform_taxonomy") or build_platform_taxonomy_report()
        task_metadata["source_platform"] = task_metadata.get("source_platform") or task_metadata["platform_taxonomy"].get("source_key")
        task_metadata["source_url"] = task_metadata.get("source_url") or task_metadata["platform_taxonomy"].get("source_url")
        task_metadata["hot_category_summary"] = task_metadata.get("hot_category_summary") or task_metadata["platform_taxonomy"].get("hot_category_summary", [])
        task_metadata["sample_titles"] = task_metadata.get("sample_titles") or [item.get("title") for item in task_metadata["platform_taxonomy"].get("sample_titles", [])]
        task_metadata["learn_from_hot_category"] = True
        task_metadata["project_category_path"] = category_context["category_path"]
        task_metadata["project_category_labels"] = category_context["category_labels"]
        task_metadata["issue_snapshot"] = issue_snapshot
        task_metadata["issue_feedback_summary"] = issue_snapshot.get("summary", "")
        task_metadata["issue_review_checklist"] = issue_snapshot.get("review_checklist", [])
        task_metadata["issue_retrieval_bias"] = issue_snapshot.get("retrieval_bias", {})
        task_metadata["selected_materials"] = selected_materials
        task_metadata["rounds"] = rounds
        task_metadata["season_plan"] = best_sample.get("season_plan", task_metadata.get("season_plan", []))
        task_metadata["best_sample"] = {
            "title": best_sample.get("title"),
            "score": best_sample.get("score"),
            "passed": best_sample.get("passed"),
            "strengths": best_sample.get("strengths", []),
            "accepted_features": best_sample.get("accepted_features", []),
            "sample_preview": best_sample.get("sample_preview", ""),
            "chapters": best_sample.get("chapters", []),
            "track": best_sample.get("track"),
            "summary": best_sample.get("summary"),
            "chapter_titles": best_sample.get("chapter_titles", []),
            "season_plan": best_sample.get("season_plan", []),
            "season_plan_summary": best_sample.get("season_plan_summary", ""),
            "meme_hit_points": best_sample.get("meme_hit_points", []),
            "romance_progress": best_sample.get("romance_progress", ""),
            "generation_mode": best_sample.get("generation_mode", "static_payload"),
            "rule_basis": best_sample.get("rule_basis", "benchmark_defaults"),
            "generation_context": best_sample.get("generation_context", {}),
            "generation_error": best_sample.get("generation_error", ""),
            "selected_materials": best_sample.get("selected_materials", []),
        }
        task_metadata["final_summary"] = build_final_summary(track, task_metadata["best_sample"], rounds)
        task.metadata_json = dumps_metadata(task_metadata).replace("\n", "").replace("  ", "")
        db.commit()
        db.refresh(task)

        if review_result["passed"]:
            break

    if export_task:
        _complete_export_task(db, export_task, best_sample, rounds, session_id, system_agent.id)

    rewrite_payload: dict[str, Any] = {}
    if is_custom_lab:
        rewrite_payload = build_dynamic_custom_campus_rewrite_payload(source_payload, selected_materials)

    task_metadata = _parse_metadata(task.metadata_json)
    material_candidates = _build_material_candidates(task_metadata, best_sample)
    create_material_entries = [create_material_item(db, candidate) for candidate in material_candidates]
    workflow_optimization_report = _build_workflow_optimization_report(task_metadata, rounds, best_sample)
    issue_snapshot = build_issue_feedback_snapshot(db, category_context["category_path"])
    issue_records = [
        item
        for item in (
            db.query(IssueRecord).filter(IssueRecord.task_id == task.id).order_by(IssueRecord.created_at.asc()).all()
        )
    ]
    rule_upgrade_suggestions = _build_rule_upgrade_suggestions(task_metadata, rounds, best_sample, issue_records)
    for suggestion in rule_upgrade_suggestions:
        create_rule(
            db,
            scope=suggestion["scope"],
            content=suggestion["content"],
            task_id=task.id if suggestion["scope"] == "task" else None,
            rule_type=suggestion["rule_type"],
            status=suggestion["status"],
            source=suggestion["source"],
        )

    task_metadata = _parse_metadata(task.metadata_json)
    task_metadata["material_candidates"] = [material_to_dict(item) for item in create_material_entries]
    task_metadata["project_category_path"] = category_context["category_path"]
    task_metadata["project_category_labels"] = category_context["category_labels"]
    task_metadata["issue_snapshot"] = issue_snapshot
    task_metadata["issue_feedback_summary"] = issue_snapshot.get("summary", "")
    task_metadata["issue_review_checklist"] = issue_snapshot.get("review_checklist", [])
    task_metadata["issue_retrieval_bias"] = issue_snapshot.get("retrieval_bias", {})
    task_metadata["issue_records"] = [issue_to_dict(item) for item in issue_records[-10:]]
    task_metadata["workflow_optimization_report"] = workflow_optimization_report
    task_metadata["rule_upgrade_suggestions"] = rule_upgrade_suggestions
    task_metadata["market_logic"] = task_metadata.get("market_logic") or build_market_logic_report()
    task_metadata["platform_taxonomy"] = task_metadata.get("platform_taxonomy") or build_platform_taxonomy_report()
    task_metadata["source_platform"] = task_metadata.get("source_platform") or task_metadata["platform_taxonomy"].get("source_key")
    task_metadata["source_url"] = task_metadata.get("source_url") or task_metadata["platform_taxonomy"].get("source_url")
    task_metadata["hot_category_summary"] = task_metadata.get("hot_category_summary") or task_metadata["platform_taxonomy"].get("hot_category_summary", [])
    task_metadata["sample_titles"] = task_metadata.get("sample_titles") or [item.get("title") for item in task_metadata["platform_taxonomy"].get("sample_titles", [])]
    task_metadata["learn_from_hot_category"] = True
    task_metadata["selected_materials"] = selected_materials
    task_metadata["season_plan"] = best_sample.get("season_plan", task_metadata.get("season_plan", []))
    task_metadata["best_sample"] = {
        "title": best_sample.get("title"),
        "score": best_sample.get("score"),
        "passed": best_sample.get("passed"),
        "strengths": best_sample.get("strengths", []),
        "accepted_features": best_sample.get("accepted_features", []),
        "sample_preview": best_sample.get("sample_preview", ""),
        "chapters": best_sample.get("chapters", []),
        "track": best_sample.get("track"),
        "summary": best_sample.get("summary"),
        "chapter_titles": best_sample.get("chapter_titles", []),
        "season_plan": best_sample.get("season_plan", []),
        "season_plan_summary": best_sample.get("season_plan_summary", ""),
        "meme_hit_points": best_sample.get("meme_hit_points", []),
        "romance_progress": best_sample.get("romance_progress", ""),
        "campus_face_slap_density": best_sample.get("campus_face_slap_density", ""),
        "generation_mode": best_sample.get("generation_mode", "static_payload"),
        "rule_basis": best_sample.get("rule_basis", "benchmark_defaults"),
        "generation_context": best_sample.get("generation_context", {}),
        "generation_error": best_sample.get("generation_error", ""),
        "selected_materials": best_sample.get("selected_materials", []),
        "rewrite_episodes": rewrite_payload.get("rewrite_episodes", []),
        "rewrite_generation_mode": rewrite_payload.get("generation_mode", ""),
        "rewrite_rule_basis": rewrite_payload.get("rule_basis", ""),
        "rewrite_error": rewrite_payload.get("generation_error", ""),
        "rewrite_preview": rewrite_payload.get("sample_preview", ""),
    }
    task_metadata["rewrite_episodes"] = rewrite_payload.get("rewrite_episodes", [])
    task_metadata["rewrite_summary"] = rewrite_payload.get("summary", "")
    task_metadata["final_summary"] = build_final_summary(track, task_metadata["best_sample"], rounds)
    task.status = "completed"
    task.metadata_json = dumps_metadata(task_metadata).replace("\n", "").replace("  ", "")
    db.commit()
    db.refresh(task)

    artifact_path = write_task_acceptance_artifact(db, task.id)
    task_metadata = _parse_metadata(task.metadata_json)
    task_metadata["artifact_path"] = str(artifact_path)
    task.metadata_json = dumps_metadata(task_metadata).replace("\n", "").replace("  ", "")
    db.commit()
    db.refresh(task)

    # 记录遥测数据
    duration = int(time.time() - start_time)
    outcome = "success" if all(r.get("passed") for r in rounds) else "partial"

    log_skill_usage("short_drama_lab_execute", outcome, duration)
    log_timeline_event(
        skill="short_drama_lab",
        event="completed",
        outcome=outcome,
        duration_s=duration,
        metadata={
            "task_id": task_id,
            "track": track,
            "rounds": len(rounds),
            "best_score": best_sample.get("score", 0),
            "lab_type": lab_type,
        },
    )

    # 记录学习发现
    if rounds:
        last_round = rounds[-1]
        if last_round.get("defects"):
            log_learning(
                skill="short_drama_lab",
                insight_type="pattern",
                key=f"{track.replace(' / ', '_')}_common_defects",
                insight=f"常见缺陷: {'; '.join(last_round['defects'][:3])}",
                confidence=7,
            )

    return {
        "task": task,
        "artifact_path": str(artifact_path),
        "rounds": rounds,
        "best_sample": task_metadata["best_sample"],
    }


def _build_project_material_tags(task_metadata: dict[str, Any]) -> list[str]:
    source_payload = task_metadata.get("source_payload") or {}
    project_brief = source_payload.get("project_brief") or {}
    story_bible = task_metadata.get("story_bible") or {}
    tags: list[str] = []
    tags.extend(project_brief.get("genres") or [])
    tags.extend(task_metadata.get("hot_category_summary") or [])
    tags.extend(task_metadata.get("sample_titles") or [])
    tags.extend(story_bible.get("world_bible", {}).get("rules") or [])
    track = task_metadata.get("current_track")
    if track:
        tags.append(track)
    return [tag for tag in list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip())) if tag]



def _inject_selected_materials(
    sample_payload: dict[str, Any],
    selected_materials: list[dict[str, Any]],
    issue_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_snapshot = issue_snapshot or {}
    if not selected_materials and not issue_snapshot:
        return sample_payload
    sample_payload = dict(sample_payload)
    borrowed = [
        {
            "title": item.get("title"),
            "summary": item.get("summary"),
            "heat_reason": item.get("heat_reason"),
            "structure_tags": item.get("structure_tags") or [],
            "project_fit_tags": item.get("project_fit_tags") or [],
            "borrow_points": (item.get("raw_payload") or {}).get("borrow_points") or [],
            "risk_points": (item.get("raw_payload") or {}).get("risk_points") or [],
        }
        for item in selected_materials
    ]
    summary_lines = [sample_payload.get("summary") or ""]
    if borrowed:
        summary_lines.append("素材召回参考：")
        for item in borrowed:
            summary_lines.append(
                f"- {item.get('title') or '未命名素材'}｜结构 {'、'.join(item.get('structure_tags') or []) or '无'}｜借鉴 {'；'.join(item.get('borrow_points') or []) or '无'}｜风险 {'；'.join(item.get('risk_points') or []) or '无'}"
            )
    if issue_snapshot:
        if issue_snapshot.get("negative_prompt_hints"):
            summary_lines.append("分类问题回避：")
            for hint in issue_snapshot.get("negative_prompt_hints")[:3]:
                summary_lines.append(f"- {hint}")
        if issue_snapshot.get("review_checklist"):
            summary_lines.append("评审重点检查：")
            for hint in issue_snapshot.get("review_checklist")[:3]:
                summary_lines.append(f"- {hint}")
    sample_payload["summary"] = "\n".join(line for line in summary_lines if line)
    sample_payload["selected_materials"] = borrowed
    sample_payload["issue_constraints"] = issue_snapshot.get("negative_prompt_hints", [])
    sample_payload["review_focus"] = issue_snapshot.get("review_checklist", [])
    sample_payload["retrieval_bias_applied"] = issue_snapshot.get("retrieval_bias", {})
    return sample_payload



def _fetch_live_material_candidates(task_metadata: dict[str, Any], best_sample: dict[str, Any]) -> list[dict[str, Any]]:
    script_path = Path(__file__).resolve().parents[2] / "skills" / "local-web-search" / "scripts" / "local_web_search.py"
    if not script_path.exists():
        return []

    platform_taxonomy = task_metadata.get("platform_taxonomy") or {}
    source_payload = task_metadata.get("source_payload") or {}
    project_brief = source_payload.get("project_brief") or {}
    genres = project_brief.get("genres") or []
    track = best_sample.get("track") or task_metadata.get("current_track") or "短剧"
    platform_name = platform_taxonomy.get("platform_name") or task_metadata.get("source_platform") or "短剧平台"
    query = (
        f"2026 {platform_name} {track} 短剧 热门 榜单 爆款 结构 热度 原因 数据分析 "
        f"{' '.join(genres[:3])}"
    ).strip()

    try:
        result = subprocess.run(
            ["python3", str(script_path), "--query", query, "--mode", "live"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    output = (result.stdout or "").strip()
    if not output:
        return []

    summary_text, _, sources_block = output.partition("\nSources:\n")
    citations = [line.strip() for line in sources_block.splitlines() if line.strip()]
    raw_item = {
        "title": f"{platform_name} {track} 热门趋势",
        "summary": summary_text[:1200],
        "tags": list(dict.fromkeys((genres or []) + [track, platform_name] + (best_sample.get("accepted_features") or []))),
        "heat_reason": "基于联网检索到的近期热榜/报道/聚合内容整理。",
        "data_points": [
            {"label": "query", "value": query},
            {"label": "citation_count", "value": len(citations)},
            {"label": "track", "value": track},
        ],
        "source_platform": task_metadata.get("source_platform") or platform_taxonomy.get("source_key") or "web_search",
        "source_url": citations[0] if citations else (task_metadata.get("source_url") or platform_taxonomy.get("source_url") or ""),
        "citations": citations,
        "heat_score": 85 if citations else 70,
        "style_hint": best_sample.get("romance_progress") or best_sample.get("summary") or "",
    }
    return [analyze_live_material(raw_item)]



def _fetch_configured_trend_candidates(task_metadata: dict[str, Any], best_sample: dict[str, Any]) -> list[dict[str, Any]]:
    track = best_sample.get("track") or task_metadata.get("current_track") or "短剧"
    source_urls = [url for url in (task_metadata.get("source_url"),) if url]
    recommendation = recommend_topics(items=[], source_urls=source_urls, focus_axis=None)
    rows = recommendation.get("recommendations") or []
    candidates: list[dict[str, Any]] = []
    for row in rows[:3]:
        scores = row.get("scores") or {}
        raw_item = {
            "title": row.get("title") or "未命名热点",
            "summary": row.get("summary") or "",
            "tags": (row.get("tags") or []) + [row.get("genre_hint") or "", best_sample.get("track") or ""],
            "heat_reason": f"外部趋势源综合评分 {scores.get('total', 0)}，hook {scores.get('hook', 0)}，fit {scores.get('fit', 0)}。",
            "data_points": [
                {"label": "heat", "value": scores.get("heat", 0)},
                {"label": "fit", "value": scores.get("fit", 0)},
                {"label": "hook", "value": scores.get("hook", 0)},
            ],
            "source_platform": row.get("source") or "trend_feed",
            "source_url": "",
            "citations": [],
            "heat_score": scores.get("heat", 0),
            "style_hint": row.get("style_hint") or "",
        }
        candidates.append(analyze_live_material(raw_item))
    return candidates


def _build_material_candidates(task_metadata: dict[str, Any], best_sample: dict[str, Any]) -> list[dict[str, Any]]:
    live_candidates = _fetch_live_material_candidates(task_metadata, best_sample)
    trend_candidates = _fetch_configured_trend_candidates(task_metadata, best_sample)
    if live_candidates or trend_candidates:
        merged_candidates = live_candidates + trend_candidates
        deduped: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for item in sorted(merged_candidates, key=lambda row: float(row.get("selection_score") or 0), reverse=True):
            title = str(item.get("title") or "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            deduped.append(item)
        if deduped:
            return deduped[:5]

    platform_taxonomy = task_metadata.get("platform_taxonomy") or {}
    sample_titles = task_metadata.get("sample_titles") or []
    hot_category_summary = task_metadata.get("hot_category_summary") or []
    source_payload = task_metadata.get("source_payload") or {}
    project_brief = source_payload.get("project_brief") or {}
    track = best_sample.get("track") or task_metadata.get("current_track") or ""
    fit_tags = list(project_brief.get("genres") or [])
    fit_tags.extend(best_sample.get("accepted_features") or [])
    fit_tags.extend([
        tag
        for tag in [
            track,
            platform_taxonomy.get("platform_name"),
            task_metadata.get("source_platform"),
        ]
        if tag
    ])

    candidates: list[dict[str, Any]] = []
    for index, title in enumerate(sample_titles[:3], start=1):
        raw_item = {
            "title": title,
            "summary": f"围绕 {track or '当前赛道'} 的热门样本《{title}》整理得到的结构启发：{'；'.join(hot_category_summary[:3]) or '突出强冲突、强尾钩与高情绪密度'}。",
            "tags": list(dict.fromkeys(fit_tags + (hot_category_summary[:4] or []))),
            "heat_reason": f"来自 {platform_taxonomy.get('platform_name') or task_metadata.get('source_platform') or '平台热榜'} 的优先学习样本，第{index}个高价值标题。",
            "data_points": [
                {"label": "platform", "value": platform_taxonomy.get("platform_name") or task_metadata.get("source_platform") or "unknown"},
                {"label": "track", "value": track or "未锁定"},
                {"label": "sample_rank", "value": index},
            ],
            "source_platform": task_metadata.get("source_platform") or platform_taxonomy.get("source_key") or "unknown",
            "source_url": task_metadata.get("source_url") or platform_taxonomy.get("source_url") or "",
            "citations": [task_metadata.get("source_url") or platform_taxonomy.get("source_url") or ""],
            "heat_score": max(60, 88 - (index - 1) * 6),
            "style_hint": best_sample.get("romance_progress") or best_sample.get("summary") or "",
        }
        candidates.append(analyze_live_material(raw_item))
    return candidates



def _build_workflow_optimization_report(task_metadata: dict[str, Any], rounds: list[dict[str, Any]], best_sample: dict[str, Any]) -> dict[str, Any]:
    failed_rounds = [item for item in rounds if not item.get("passed")]
    story_bible = task_metadata.get("story_bible") or {}
    return {
        "status": "completed" if rounds else "pending",
        "token_saving_actions": [
            "先生成 story_bible，再按需注入角色/世界观/金手指，避免每轮全量召回大纲。",
            "内部测试只保留最优样稿与缺陷摘要，减少重复上下文传递。",
            "按赛道过滤素材候选，只保留高分条目参与后续项目参考。",
        ],
        "effective_steps": [
            "前置设定抽取与补全",
            "赛道锁定后再进入样稿循环",
            "审查结果结构化记录后再补丁重跑",
        ],
        "redundant_steps": [
            "重复注入完整原稿摘要" if task_metadata.get("source_summary") else "无明显冗余步骤",
            "在已通过轮次继续保留补丁子任务占位",
        ],
        "observations": [
            f"共执行 {len(rounds)} 轮内部测试，其中未通过 {len(failed_rounds)} 轮。",
            f"最优样稿赛道为 {best_sample.get('track') or task_metadata.get('current_track') or '未记录'}。",
            f"story_bible 模式：{story_bible.get('mode') or 'unknown'}。",
        ],
        "next_actions": [
            "后续长篇生成可按阶段缓存 season_plan 与关系矩阵，避免单次注入 10-20 集全量上下文。",
            "把 approved 素材条目作为项目级召回，而不是运行时规则。",
        ],
    }



def _build_rule_upgrade_suggestions(
    task_metadata: dict[str, Any],
    rounds: list[dict[str, Any]],
    best_sample: dict[str, Any],
    issue_records: list[IssueRecord] | None = None,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    track = best_sample.get("track") or task_metadata.get("current_track") or "当前赛道"
    accepted_features = best_sample.get("accepted_features") or []
    if accepted_features:
        suggestions.append({
            "scope": "task",
            "rule_type": "suggestion",
            "status": "candidate",
            "source": "workflow_summary",
            "content": "建议规则：在 {track} 题材中优先保留以下稳定命中特征：{features}。仅作为候选建议，需人工确认后再升级为正式规则。".format(
                track=track,
                features="；".join(accepted_features[:5]),
            ),
        })
    failed_defects = []
    for item in rounds:
        failed_defects.extend(item.get("defects") or [])
    if failed_defects:
        suggestions.append({
            "scope": "task",
            "rule_type": "suggestion",
            "status": "candidate",
            "source": "workflow_summary",
            "content": "建议规则：生成前优先检查以下高频缺陷，避免重复返工：{defects}。仅作为候选建议，需人工确认后再升级为正式规则。".format(
                defects="；".join(list(dict.fromkeys(failed_defects))[:5]),
            ),
        })
    suggestions.extend(build_issue_rule_suggestions(issue_records or []))
    return suggestions


    metadata = _parse_metadata(sub_task.metadata_json)
    metadata.update({
        "track": track,
        "sample_preview": metadata.get("sample_preview") or f"已完成{metadata.get('module_stage', '前置阶段')}，当前锁定赛道 {track}。",
        "passed": True,
    })
    _set_sub_task_status_flow(db, sub_task, metadata, session_id)
    _log_activity(db, agent_id, sub_task.id, "lab_setup", f"完成前置阶段：{sub_task.name}，锁定赛道 {track}", session_id)


def _complete_setup_sub_task(db: Session, sub_task: SubTask, track: str, session_id: str, agent_id: str) -> None:
    metadata = _parse_metadata(sub_task.metadata_json)
    metadata.update({
        "track": track,
        "sample_preview": metadata.get("sample_preview") or f"已完成{metadata.get('module_stage', '前置阶段')}，当前锁定赛道 {track}。",
        "passed": True,
    })
    _set_sub_task_status_flow(db, sub_task, metadata, session_id)
    _log_activity(db, agent_id, sub_task.id, "lab_setup", f"完成前置阶段：{sub_task.name}，锁定赛道 {track}", session_id)


def _run_round_generation(
    db: Session,
    sub_task: SubTask,
    round_no: int,
    sample_payload: dict[str, Any],
    review_result: dict[str, Any],
    session_id: str,
    agent_id: str,
) -> None:
    metadata = _parse_metadata(sub_task.metadata_json)
    metadata.update({
        "round": round_no,
        "score": review_result["score"],
        "passed": review_result["passed"],
        "sample_preview": sample_payload["sample_preview"],
        "accepted_features": sample_payload["accepted_features"],
        "chapter_titles": sample_payload["chapter_titles"],
        "defects": review_result["defects"],
        "strengths": review_result["strengths"],
    })
    _set_sub_task_status_flow(db, sub_task, metadata, session_id)
    _log_activity(db, agent_id, sub_task.id, "lab_generate", f"第{round_no}轮生成样稿《{sample_payload['title']}》", session_id)


def _run_round_review(
    db: Session,
    sub_task: SubTask,
    round_no: int,
    review_result: dict[str, Any],
    sample_payload: dict[str, Any],
    session_id: str,
    agent_id: str,
    review_checklist: list[str] | None = None,
) -> None:
    metadata = _parse_metadata(sub_task.metadata_json)
    metadata.update({
        "round": round_no,
        "score": review_result["score"],
        "passed": review_result["passed"],
        "defects": review_result["defects"],
        "strengths": review_result["strengths"],
        "patch_summary": review_result["patch_summary"],
        "rerun_reason": review_result["rerun_reason"],
        "accepted_features": sample_payload["accepted_features"],
        "review_checklist": review_checklist or [],
    })
    _set_sub_task_status_flow(db, sub_task, metadata, session_id)
    db.add(
        ReviewRecord(
            id=str(uuid.uuid4()),
            sub_task_id=sub_task.id,
            reviewer_agent=agent_id,
            round=round_no,
            result="approved" if review_result["passed"] else "rejected",
            score=max(1, min(5, round(review_result["score"] / 20))),
            issues="；".join(review_result["defects"]),
            comment="；".join((review_checklist or [])[:3]) + ("｜" if review_checklist else "") + review_result["patch_summary"],
            rework_agent=agent_id,
        )
    )
    db.commit()
    _log_activity(db, agent_id, sub_task.id, "lab_review", f"第{round_no}轮评审完成，评分 {review_result['score']}，通过 {review_result['passed']}", session_id)


def _run_round_patch(
    db: Session,
    sub_task: SubTask,
    round_no: int,
    review_result: dict[str, Any],
    sample_payload: dict[str, Any],
    session_id: str,
    agent_id: str,
) -> None:
    metadata = _parse_metadata(sub_task.metadata_json)
    metadata.update({
        "round": round_no,
        "score": review_result["score"],
        "passed": review_result["passed"],
        "defects": review_result["defects"],
        "strengths": review_result["strengths"],
        "patch_summary": review_result["patch_summary"],
        "rerun_reason": review_result["rerun_reason"],
        "sample_preview": sample_payload["summary"],
        "accepted_features": sample_payload["accepted_features"],
    })
    _set_sub_task_status_flow(db, sub_task, metadata, session_id)
    action = "lab_converge" if review_result["passed"] else "lab_patch"
    summary = (
        f"第{round_no}轮通过，锁定最优样稿《{sample_payload['title']}》"
        if review_result["passed"]
        else f"第{round_no}轮补丁完成：{review_result['patch_summary']}"
    )
    _log_activity(db, agent_id, sub_task.id, action, summary, session_id)


def _complete_export_task(
    db: Session,
    sub_task: SubTask,
    best_sample: dict[str, Any],
    rounds: list[dict[str, Any]],
    session_id: str,
    agent_id: str,
) -> None:
    metadata = _parse_metadata(sub_task.metadata_json)
    metadata.update({
        "round": rounds[-1]["round"] if rounds else None,
        "score": best_sample.get("score"),
        "passed": best_sample.get("passed"),
        "sample_preview": best_sample.get("sample_preview"),
        "accepted_features": best_sample.get("accepted_features", []),
        "chapter_titles": best_sample.get("chapter_titles", []),
        "patch_summary": rounds[-1].get("patch_summary") if rounds else "",
        "rerun_reason": rounds[-1].get("rerun_reason") if rounds else "",
    })
    _set_sub_task_status_flow(db, sub_task, metadata, session_id)
    _log_activity(db, agent_id, sub_task.id, "lab_export", f"导出最优样稿《{best_sample.get('title', '未命名样稿')}》前三章验收件", session_id)


def _set_sub_task_status_flow(db: Session, sub_task: SubTask, metadata: dict[str, Any], session_id: str) -> None:
    current = db.query(SubTask).filter(SubTask.id == sub_task.id).first()
    if not current:
        raise ValueError(f"子任务 {sub_task.id} 不存在")

    if current.status == "pending":
        current.status = "assigned"
    if current.status in {"assigned", "rework"}:
        current.status = "in_progress"
    if session_id:
        current.current_session_id = session_id
    current.metadata_json = dumps_metadata(metadata).replace("\n", "").replace("  ", "")
    current.status = "review"
    db.commit()
    db.refresh(current)
    current.metadata_json = dumps_metadata(metadata).replace("\n", "").replace("  ", "")
    current.status = "done"
    db.commit()
    db.refresh(current)


def _get_or_create_system_agent(db: Session) -> Agent:
    agent = db.query(Agent).filter(Agent.name == "ShortDramaLab").first()
    if agent:
        return agent

    agent = Agent(
        id=str(uuid.uuid4()),
        name="ShortDramaLab",
        role="planner",
        description="Anthropic Claude 驱动的短剧市场实验执行代理",
        status="active",
        api_key=f"lab-{uuid.uuid4().hex}",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _log_activity(db: Session, agent_id: str, sub_task_id: str, action: str, summary: str, session_id: str | None) -> None:
    db.add(
        ActivityLog(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            sub_task_id=sub_task_id,
            action=action,
            summary=summary,
            session_id=session_id,
        )
    )
    db.commit()


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _sequence_key(sequence: str | None) -> tuple[int, ...]:
    if not sequence:
        return (999,)
    return tuple(int(part) if part.isdigit() else 0 for part in sequence.split("."))
