"""测试页"剧本片段建议 / 局部替换"两个轻量路由（从 short_drama_writing.py 抽出）。

这两个 endpoint 只调用 services.text_generation_service，不依赖 router 内的
任何辅助 helper，是最容易拆出去的一对。聚合到 main router 时无需改动。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.routers.short_drama._billing import (
    charge_short_drama_usage,
    ensure_short_drama_project_access,
    record_short_drama_failure,
)
from app.schemas.short_drama_writing import (
    SceneSuggestRequest,
    SceneSuggestResponse,
    ScenePatchRequest,
    ScenePatchResponse,
)
from app.services.text_generation_service import begin_usage_collection, end_usage_collection, generate_text

router = APIRouter()  # 由主 router 加 prefix

_SEGMENT_LABELS = {
    "hook": "开场钩子",
    "validation": "冲突验证",
    "explosion": "爆点升级",
    "resolution": "收束尾钩",
}


def _clip_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _suggest_character_context(req: SceneSuggestRequest) -> str:
    lines: list[str] = []
    for char in (req.characters or [])[:8]:
        name = _clip_text(char.get("name"), 24)
        if not name:
            continue
        role = _clip_text(char.get("role"), 24)
        info = _clip_text(char.get("info") or char.get("background"), 120)
        rels = []
        for rel in (char.get("relationships") or [])[:4]:
            if not isinstance(rel, dict):
                continue
            target = _clip_text(rel.get("targetName") or rel.get("target_name") or rel.get("target"), 24)
            rel_type = _clip_text(rel.get("type") or rel.get("relationship"), 24)
            if target:
                rels.append(f"与{target}:{rel_type or '关系'}")
        lines.append(f"- {name}({role or '角色'}): {info}" + (f"；关系：{'、'.join(rels)}" if rels else ""))
    return "\n".join(lines)


def _suggest_contract_context(req: SceneSuggestRequest) -> str:
    contract = req.episode_contract or {}
    parts: list[str] = []
    for key, label in (
        ("start_state", "承接"),
        ("must_happen", "必须发生"),
        ("relationship_delta", "关系变化"),
        ("information_delta", "信息揭露"),
        ("public_pressure", "公开压迫"),
        ("real_loss", "当场后果"),
        ("evidence_object", "物件钩子"),
        ("villain_pressure_action", "反派动作"),
        ("ending_hook", "尾钩"),
    ):
        value = contract.get(key)
        if isinstance(value, list):
            text = "；".join(_clip_text(item, 90) for item in value[:5] if str(item).strip())
        else:
            text = _clip_text(value, 280)
        if text:
            parts.append(f"- {label}: {text}")
    return "\n".join(parts)


def _suggest_issue_context(req: SceneSuggestRequest) -> str:
    feedback = req.issue_feedback or {}
    issues = feedback.get("issues") if isinstance(feedback, dict) else []
    if not isinstance(issues, list):
        issues = []
    return "；".join(_clip_text(item, 80) for item in issues[:5] if str(item).strip())


def _build_scene_suggest_prompt(req: SceneSuggestRequest) -> tuple[str, str]:
    """构建分段精写建议提示词：建议必须带可执行改法，而不是泛泛点评。"""
    system_prompt = (
        "你是短剧分段精写审稿专家。你必须基于本集大纲、角色关系、已确认前文和当前段落给建议。"
        "每条建议必须同时包含【问题】和【改法】，改法要能直接交给 AI 执行。"
        "禁止泛泛而谈，禁止改换题材、人物、核心冲突，禁止提前兑现后续剧情。"
    )
    segment_label = _SEGMENT_LABELS.get(req.segment_id, req.segment_id or "当前段落")
    previous_briefs = []
    for item in (req.previous_episode_briefs or [])[-3:]:
        previous_briefs.append(
            f"第{item.get('episode_no') or item.get('ep') or ''}集："
            f"{_clip_text(item.get('title'), 40)}｜"
            f"{_clip_text(item.get('summary') or item.get('actual_progress'), 160)}"
        )
    user_prompt = (
        f"分段类型：{segment_label}\n"
        f"受众/题材：{req.audience_axis or '未填'} / {req.genre_main or '未填'}\n"
        f"本集标题：{req.episode_title or '未填'}\n"
        f"本集摘要：{_clip_text(req.episode_summary, 500)}\n"
        f"本集冲突：{_clip_text(req.episode_conflict, 400)}\n"
        f"本集尾钩：{_clip_text(req.episode_hook, 260)}\n\n"
        f"上一集/前序简记：\n{chr(10).join(previous_briefs) or '暂无'}\n\n"
        f"角色与关系：\n{_suggest_character_context(req) or '暂无'}\n\n"
        f"当前关系护栏：\n{_clip_text(req.relationship_guardrails, 700) or '暂无'}\n\n"
        f"本集硬约束：\n{_suggest_contract_context(req) or '暂无'}\n\n"
        f"已确认前文：\n{_clip_text(req.confirmed_content, 900) or '暂无'}\n\n"
        f"当前待审片段：\n{_clip_text(req.scene_content, 1800)}\n\n"
        f"已有问题反馈：{_suggest_issue_context(req) or '暂无'}\n\n"
        "请输出 2-3 条建议。每条一行，格式固定为："
        "【问题】具体问题；【改法】具体替换/补写方向。每条不超过 80 字。"
    ).strip()
    return system_prompt, user_prompt


def _parse_scene_suggestions(raw: str) -> list[str]:
    suggestions: list[str] = []
    for line in (raw or "").splitlines():
        text = re.sub(r"^[\d]+[.、．]\s*|^[·•\-–]\s*", "", line).strip()
        if not text:
            continue
        if "【问题】" not in text or "【改法】" not in text:
            text = f"【问题】建议不够聚焦；【改法】{text}"
        suggestions.append(text[:90])
        if len(suggestions) >= 3:
            break
    return suggestions


def _ensure_scene_edit_access(
    db: Session,
    project_id: str,
    actor: ProjectAccessActor,
    *,
    require_credit: bool = True,
) -> None:
    ensure_short_drama_project_access(
        db,
        project_id,
        actor,
        require_credit=require_credit,
    )


def _charge_scene_edit(
    db: Session,
    actor: ProjectAccessActor,
    usage_metrics: dict,
    *,
    generation_type: str,
    reason: str,
) -> None:
    charge_short_drama_usage(
        db,
        actor,
        usage_metrics,
        generation_type=generation_type,
        reason=reason,
    )


def _record_scene_edit_failure(
    db: Session,
    actor: ProjectAccessActor,
    exc: Exception,
    *,
    generation_type: str,
) -> None:
    record_short_drama_failure(
        db,
        actor,
        generation_type=generation_type,
        reason=f"测试页局部编辑失败，未扣费：{exc}",
    )


@router.post(
    "/testing/script-scene/suggest",
    response_model=SceneSuggestResponse,
    summary="生成剧本片段改进建议",
)
async def suggest_scene_improvement(
    req: SceneSuggestRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    """对已生成的剧本片段给出 2-3 条具体改进建议。"""
    _ensure_scene_edit_access(db, req.project_id, actor)
    system_prompt, user_prompt = _build_scene_suggest_prompt(req)
    usage_metrics, usage_token = begin_usage_collection({"scope": "testing_scene_suggest"})
    try:
        raw = generate_text(system_prompt, user_prompt, temperature=0.35, max_tokens=320)
    except Exception as exc:
        _record_scene_edit_failure(db, actor, exc, generation_type="testing_scene_suggest")
        return SceneSuggestResponse(suggestions=[
            "【问题】当前片段还缺少可执行诊断；【改法】先补本集冲突、角色关系和结尾动作。",
        ])
    finally:
        end_usage_collection(usage_token)
    _charge_scene_edit(
        db,
        actor,
        usage_metrics,
        generation_type="testing_scene_suggest",
        reason="测试页片段建议成功扣费",
    )
    suggestions = _parse_scene_suggestions(raw)
    return SceneSuggestResponse(suggestions=suggestions)


@router.post(
    "/testing/script-scene/patch",
    response_model=ScenePatchResponse,
    summary="局部替换剧本选中文字",
)
async def patch_scene_text(
    req: ScenePatchRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    """用户选中一段文字并给出修改指令，AI 只返回替换片段，不输出完整剧本。"""
    _ensure_scene_edit_access(db, req.project_id, actor)
    style_ex = (
        "【场1-1：夜  内  书房】"
        if req.scene_header_style == "bracket"
        else "1-1  夜  内  书房"
    )
    system_prompt = (
        "你是短剧剧本编辑，专门执行局部文字替换。"
        "严格规则：你只能输出替换片段本身，禁止输出完整剧本，禁止输出任何解释、前缀或上下文，"
        "禁止重复原文中未被选中的部分。"
        f"场次标头格式参考：{style_ex}"
    )
    user_prompt = (
        f"完整剧本（仅供参考，不要输出）：\n{str(req.full_text or '')[:3000]}\n\n"
        f"---\n需要替换的原文片段：\n{req.selected_text}\n\n"
        f"修改指令：{req.instruction}\n\n"
        "只输出替换片段，不输出完整剧本，不输出任何解释，直接给出替换后的文字。"
    )
    usage_metrics, usage_token = begin_usage_collection({"scope": "testing_scene_patch"})
    try:
        replacement = generate_text(
            system_prompt, user_prompt, temperature=0.45, max_tokens=800
        )
    except Exception as exc:
        _record_scene_edit_failure(db, actor, exc, generation_type="testing_scene_patch")
        raise HTTPException(status_code=502, detail=f"AI 修改失败：{exc}")
    finally:
        end_usage_collection(usage_token)
    _charge_scene_edit(
        db,
        actor,
        usage_metrics,
        generation_type="testing_scene_patch",
        reason="测试页局部替换成功扣费",
    )
    return ScenePatchResponse(replacement=(replacement or "").strip())
