"""测试页“素材/问题反馈/报告”上下文块（从 short_drama_writing.py 抽出）。

3 个纯函数，零 IO/AI/DB：

- build_testing_material_context：把 req.materials 拼成多块素材上下文（参考/借鉴/热度/风险/避免）
- build_testing_issue_feedback_context：把 req.issue_feedback 拼成 “- 总结/避免/审查重点” 块
- build_testing_report_context：把 req.quality_report / compliance_report 拼成历史报告块
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.short_drama_lab_service import (
    _build_selected_material_borrow_focus,
    _build_selected_material_do_not_copy,
    _build_selected_material_heat_signals,
    _build_selected_material_reference,
    _build_selected_material_risk_guardrails,
)

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def build_testing_material_context(req: "TestingScriptRequest") -> str:
    """把 req.materials 拼成多块素材上下文（参考/借鉴/热度/风险/避免）。"""
    materials = req.materials or []
    if not isinstance(materials, list) or not materials:
        return "暂无素材参考。"
    return "\n".join(filter(None, [
        _build_selected_material_reference(materials),
        _build_selected_material_borrow_focus(materials),
        _build_selected_material_heat_signals(materials),
        _build_selected_material_risk_guardrails(materials),
        _build_selected_material_do_not_copy(materials),
    ])).strip() or "暂无素材参考。"


def build_testing_issue_feedback_context(req: "TestingScriptRequest") -> str:
    """把 req.issue_feedback 拼成 “- 总结/避免/审查重点” 块。"""
    issue_feedback = req.issue_feedback or {}
    if not isinstance(issue_feedback, dict) or not issue_feedback:
        return "暂无历史问题反馈。"
    lines: list[str] = []
    summary = str(issue_feedback.get("summary") or "").strip()
    if summary:
        lines.append(f"- 总结：{summary}")
    for item in (issue_feedback.get("negative_prompt_hints") or [])[:4]:
        text = str(item or "").strip()
        if text:
            lines.append(f"- 避免：{text}")
    for item in (issue_feedback.get("review_focus") or [])[:4]:
        text = str(item or "").strip()
        if text:
            lines.append(f"- 审查重点：{text}")
    return "\n".join(lines) if lines else "暂无历史问题反馈。"


def build_testing_report_context(req: "TestingScriptRequest") -> str:
    """把 req.quality_report / compliance_report 拼成历史报告块。"""
    lines: list[str] = []
    quality = req.quality_report or {}
    compliance = req.compliance_report or {}
    if isinstance(quality, dict):
        for key, label in (("summary", "质量摘要"), ("focus", "质量重点"), ("next_fix", "下轮修复")):
            text = str(quality.get(key) or "").strip()
            if text:
                lines.append(f"- {label}：{text[:140]}")
    if isinstance(compliance, dict):
        for key, label in (("summary", "合规摘要"), ("risks", "合规风险")):
            value = compliance.get(key)
            if isinstance(value, list):
                joined = "；".join(str(item)[:60] for item in value[:3] if str(item).strip())
                if joined:
                    lines.append(f"- {label}：{joined}")
            else:
                text = str(value or "").strip()
                if text:
                    lines.append(f"- {label}：{text[:140]}")
    return "\n".join(lines) if lines else "暂无历史质量/合规报告。"
