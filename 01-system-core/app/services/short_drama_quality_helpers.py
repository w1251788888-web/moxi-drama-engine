"""短剧质量门禁 / 步骤结果提示词辅助（从 short_drama_writing.py 抽出）。

- coerce_generation_text: 把 dict/list/str 标准化为字符串
- normalize_quality_dimension: 把"节奏分"/"节奏" 等中英文别名归一为标准维度名
- derive_quality_step_guidance: 根据 quality_report.verdict + revision_instructions 推断 repair_scope
- build_step_result_extras: 给 StepResult 补充 gate_warning/quality_verdict/repair_scope 字段
- build_acceptance_gate_warning: 根据 acceptance_checks 拼接量化验收未通过提示
- extract_step_text: 从 step_payload 取 context_output / full_output
- project_config_value: project.config[key] 优先，其次 project[key]

所有函数均为纯数据变换，无 IO 依赖。
"""
from __future__ import annotations

import json
from typing import Any

from app.services.short_drama_workflow_config import STEP_ID


def coerce_generation_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2).strip()
    return ""


def normalize_quality_dimension(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    aliases = {
        "节奏分": "rhythm",
        "节奏": "rhythm",
        "rhythm": "rhythm",
        "对白分": "dialogue",
        "对白": "dialogue",
        "dialogue": "dialogue",
        "格式分": "format",
        "格式": "format",
        "format": "format",
        "连贯性分": "continuity",
        "连贯性": "continuity",
        "continuity": "continuity",
        "商业性分": "commercial_viability",
        "商业性": "commercial_viability",
        "commercial_viability": "commercial_viability",
        "爽感密度分": "satisfaction_density",
        "爽感密度": "satisfaction_density",
        "satisfaction_density": "satisfaction_density",
        "原著保真度分": "novel_fidelity",
        "原著保真度": "novel_fidelity",
        "novel_fidelity": "novel_fidelity",
    }
    return aliases.get(text, text)


def derive_quality_step_guidance(payload: dict[str, Any]) -> dict[str, str]:
    report = payload.get("quality_report") or {}
    if not isinstance(report, dict):
        return {
            "quality_verdict": "",
            "repair_scope": "",
            "revision_summary": "",
        }

    verdict = str(report.get("verdict") or "").strip().lower()
    instructions = report.get("revision_instructions") or []
    if not isinstance(instructions, list):
        instructions = []

    normalized_dims = [
        normalize_quality_dimension(item.get("dimension"))
        for item in instructions
        if isinstance(item, dict)
    ]

    patchable_dims = {"format", "dialogue", "rhythm"}
    upstream_dims = {"continuity", "novel_fidelity"}

    advanced = report.get("advanced_diagnostics") or {}
    if not isinstance(advanced, dict):
        advanced = {}
    failed_chain_checks = sum(
        1
        for key in ("relationship_progress", "info_chain_continuity", "power_shift_visibility")
        if isinstance(advanced.get(key), dict) and not bool(advanced.get(key, {}).get("passed", True))
    )

    repair_scope = ""
    if verdict == "pass":
        repair_scope = "none"
    elif normalized_dims and all(dim in patchable_dims for dim in normalized_dims if dim):
        repair_scope = "patchable"
    elif any(dim in upstream_dims for dim in normalized_dims) or failed_chain_checks >= 2:
        repair_scope = "upstream_retry"
    else:
        repair_scope = "rewrite_current_step"

    summary_parts: list[str] = []
    for item in instructions[:3]:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        problem = str(item.get("problem") or "").strip()
        fix = str(item.get("fix") or "").strip()
        if problem or fix:
            summary_parts.append("：".join(part for part in [dimension, problem or fix] if part))
    if not summary_parts and verdict == "pass":
        pass_notes = str(report.get("pass_notes") or "").strip()
        if pass_notes:
            summary_parts.append(pass_notes)

    return {
        "quality_verdict": verdict,
        "repair_scope": repair_scope,
        "revision_summary": "；".join(summary_parts[:2]),
    }


def build_step_result_extras(
    step_id: STEP_ID,
    payload: dict[str, Any],
    *,
    gate_warning: str = "",
) -> dict[str, str]:
    extras = {
        "gate_warning": str(gate_warning or "").strip(),
        "quality_verdict": "",
        "repair_scope": "",
        "revision_summary": "",
    }
    if step_id == "quality_check":
        extras.update(derive_quality_step_guidance(payload))
    return extras


def build_acceptance_gate_warning(
    acceptance_checks: dict[str, Any],
    existing_warning: str = "",
) -> str:
    if not isinstance(acceptance_checks, dict):
        return str(existing_warning or "").strip()
    if acceptance_checks.get("overall_passed") is True:
        return str(existing_warning or "").strip()

    label_map = {
        "emotion_variance": "情感波动",
        "emotion_pattern": "情感模式",
        "character_density": "角色密度",
        "duplicate_check": "重复内容",
    }
    failed_checks: list[str] = []
    missing_dependencies: list[str] = []

    checks = acceptance_checks.get("checks") if isinstance(acceptance_checks.get("checks"), dict) else {}
    for key, raw in checks.items():
        if not isinstance(raw, dict) or raw.get("passed") is True:
            continue
        label = label_map.get(str(key), str(key))
        reason = str(raw.get("reason") or "未通过").strip()
        if raw.get("dependency_missing"):
            dependency_name = str(raw.get("dependency_name") or label).strip()
            missing_dependencies.append(f"{dependency_name}（{reason}）")
        else:
            failed_checks.append(f"{label}：{reason[:50]}")

    parts: list[str] = []
    warning_prefix = str(existing_warning or "").strip()
    if warning_prefix:
        parts.append(warning_prefix)
    if failed_checks:
        parts.append("量化验收未通过：" + "；".join(failed_checks[:3]))
    if missing_dependencies:
        parts.append("验收依赖缺失：" + "；".join(dict.fromkeys(missing_dependencies)))
    return " ".join(part for part in parts if part).strip()


def extract_step_text(step_payload: dict | None) -> str:
    if not isinstance(step_payload, dict):
        return ""
    return (
        coerce_generation_text(step_payload.get("context_output"))
        or coerce_generation_text(step_payload.get("full_output"))
    )


def project_config_value(project: dict[str, Any], key: str) -> Any:
    config_payload = project.get("config") or {}
    if isinstance(config_payload, dict) and key in config_payload:
        return config_payload.get(key)
    return project.get(key)
