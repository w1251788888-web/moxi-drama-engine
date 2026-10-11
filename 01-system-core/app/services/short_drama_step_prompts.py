"""run-step prompt 装配（从 short_drama_writing.py 抽出）。

5 个函数：

- render_step_prompt：把 step 模板 + 变量渲染成 user_prompt
- system_prompt_for_step：按 step_id 取 system prompt（默认兜底文案）
- step_generation_payload：装出 (variables, system_prompt, user_prompt) 三元组（含 RAG 注入兜底）
- derive_category_path：把 metadata.project.genre_main / genre_sub 拼成 “主类 / 子类”
- build_startup_context：装出 StartupContextResponse（startup-context endpoint 主体）

依赖：rule_resolver、rag_injection、template_vars、session_metadata，全部已在 services。
"""
from __future__ import annotations

import re
from string import Template
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.short_drama_writing import (
    StartupChecklistItem,
    StartupContextResponse,
)
from app.services.short_drama_rag_injection import apply_rag_injection
from app.services.short_drama_rule_resolver import (
    load_agent_prompt,
    load_step_template,
    resolve_rules_injection,
)
from app.services.short_drama_session_metadata import build_startup_checklist
from app.services.short_drama_template_vars import build_base_template_vars
from app.services.short_drama_workflow_config import (
    STEP_ID,
    STEP_PROMPT_FILE,
    STEP_SYSTEM_PROMPT_FILE,
)


_UNRESOLVED_TEMPLATE_VAR_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*")


def _blank_unresolved_template_vars(text: str) -> str:
    """把未填上的 ${x} 兜底置空，避免字面变量泄漏给模型。"""
    return _UNRESOLVED_TEMPLATE_VAR_RE.sub("", text)


def render_step_prompt(step_id: STEP_ID, variables: dict[str, str]) -> str:
    """把 step 模板 + 变量渲染成 user_prompt。"""
    template_text = load_step_template(STEP_PROMPT_FILE[step_id])
    # Bug Fix #4: 先替换 {{rules:xxx}} 语法，再做 ${} Template 替换
    template_text = resolve_rules_injection(template_text, variables)
    return _blank_unresolved_template_vars(Template(template_text).safe_substitute(variables))


def system_prompt_for_step(step_id: STEP_ID) -> str:
    """按 step_id 取 system prompt（默认兜底文案）。"""
    file_name = STEP_SYSTEM_PROMPT_FILE.get(step_id)
    if file_name:
        return load_agent_prompt(file_name)
    return "你是短剧写作引擎。严格按要求输出 JSON 对象，不要输出解释。"


async def step_generation_payload(
    step_id: STEP_ID,
    metadata: dict,
    req_vars: dict[str, Any],
    *,
    draft_episode: int,
    known_template_keys: tuple[str, ...],
    db: Session | None = None,
) -> tuple[dict[str, str], str, str, list[dict[str, Any]]]:
    """装出 (variables, system_prompt, user_prompt, rag_evidence)（含 RAG 注入兜底）。"""
    variables = build_base_template_vars(
        metadata, draft_episode=draft_episode, known_template_keys=known_template_keys
    )

    for key, value in (req_vars or {}).items():
        if key not in known_template_keys:
            # 允许 UI 传入扩展字段，但不直接注入模板（避免拼错字段导致 prompt 污染）
            continue
        new_val = "" if value is None else str(value)
        # 不让 req_vars 的空值覆盖 base 已注入的非空值
        if not new_val and variables.get(key):
            continue
        variables[key] = new_val

    # RAG 注入（按步骤配置，失败/未配置时安全降级）
    rag_evidence = await apply_rag_injection(step_id, metadata, variables, db=db)

    # 兜底：任何未被注入的 rag_* 占位符都填空，避免 prompt 里出现字面 ${rag_...}
    for _rag_key in (
        "rag_asset_references",
        "rag_market_signals",
        "rag_novel_chapters",
        "rag_script_references",
        "rag_character_references",
        "rag_beat_references",
        "rag_review_references",
    ):
        variables.setdefault(_rag_key, "")

    user_prompt = render_step_prompt(step_id, variables)
    system_prompt = system_prompt_for_step(step_id)
    return variables, system_prompt, user_prompt, rag_evidence


def derive_category_path(metadata: dict) -> str:
    """把 metadata.project.genre_main / genre_sub 拼成 “主类 / 子类”。"""
    project = metadata.get("project") or {}
    genre_main = str(project.get("genre_main") or "").strip()
    genre_sub = str(project.get("genre_sub") or "").strip()
    return " / ".join(part for part in [genre_main, genre_sub] if part) or genre_sub or genre_main or "当前赛道"


def build_startup_context(
    metadata: dict,
    recommended_materials: list[dict[str, Any]] | None = None,
) -> StartupContextResponse:
    """装出 StartupContextResponse（startup-context endpoint 主体）。"""
    recommended_materials = recommended_materials or []
    checklist = build_startup_checklist(metadata)
    return StartupContextResponse(
        materials=metadata.get("materials") or [],
        recommended_materials=recommended_materials,
        issue_feedback=metadata.get("issue_feedback") or {},
        startup_checklist=[StartupChecklistItem(**item) for item in checklist],
    )
