"""短剧写作的 RAG 注入工具（从 short_drama_writing.py 抽出）。

- augment_2026_rule_rag_query：给 2026 规则卡相关 dataset 补"平台/时长"的高信噪关键词
- apply_rag_injection：按 config.yaml 中 rag.dify.step_bindings[step_id] 配置执行检索 + 注入

step_id 这里只用于查 config，类型用 str（主 router 那边的 STEP_ID Literal 仅用于静态检查）。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.duration_profile_service import infer_duration_profile

RAG_2026_RULE_DATASETS = {
    "writing_tutorials_2026",
    "manga_platform_rules_2026",
    "satisfaction_taxonomy_45",
    "tutorial_case_patterns",
}

# Dify hit-testing API currently rejects query strings longer than 250 chars.
# Keep a margin so user-facing generation never waits on an avoidable 400.
DIFY_QUERY_SAFE_MAX_CHARS = 220

_DIFY_QUERY_FIELD_BUDGETS = {
    "brief": 70,
    "concept": 70,
    "episode_summary": 78,
    "episode_conflict": 66,
    "episode_hook": 54,
    "character_names": 42,
    "genre_main": 24,
    "genre_sub": 24,
    "subgenre_track": 36,
    "sample_track": 36,
}


def augment_2026_rule_rag_query(
    dataset: str,
    query: str,
    variables: dict[str, str],
    project: dict[str, Any],
) -> str:
    """给 2026 规则卡相关 dataset 的检索 query 补充平台/时长高信噪词。"""
    if dataset not in RAG_2026_RULE_DATASETS:
        return query

    parts = [str(query or "").strip()]
    for key in ("project_type", "format_type", "audience_axis", "subgenre_track"):
        value = str(variables.get(key) or project.get(key) or "").strip()
        if value and value not in " ".join(parts):
            parts.append(value)

    try:
        episode_minutes = float(variables.get("episode_minutes") or project.get("episode_minutes") or 1.5)
    except Exception:
        episode_minutes = 1.5
    try:
        explicit_min = int(variables.get("word_count_min") or project.get("word_count_min") or 0) or None
    except Exception:
        explicit_min = None
    try:
        explicit_max = int(variables.get("word_count_max") or project.get("word_count_max") or 0) or None
    except Exception:
        explicit_max = None
    try:
        explicit_target = int(variables.get("word_count_target") or project.get("word_count_target") or 0) or None
    except Exception:
        explicit_target = None
    profile = infer_duration_profile(
        episode_minutes=episode_minutes,
        explicit_min=explicit_min,
        explicit_max=explicit_max,
        explicit_target=explicit_target,
    )
    parts.append(f"{profile.duration_seconds}秒 {profile.min_chars}-{profile.max_chars}纯字符 90秒=1200纯字符换算")

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = str(part or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return " ".join(deduped).strip()


async def apply_rag_injection(
    step_id: str,
    metadata: dict,
    variables: dict[str, str],
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """
    按 config.yaml 中 rag.dify / rag.knowledge_chunks 的步骤绑定执行 RAG 检索，
    将结果注入到 variables[inject_as]，并返回可展示/可审计的紧凑证据。
    未配置 / 后端不可达 / 检索失败时安全降级，保证主流程不受影响。
    """
    try:
        from app.config import get_config
    except Exception:
        return []

    cfg = (get_config() or {}).get("rag", {}) or {}
    evidence: list[dict[str, Any]] = []
    evidence.extend(await _apply_dify_rag_injection(step_id, metadata, variables, cfg))
    evidence.extend(_apply_knowledge_chunk_injection(step_id, metadata, variables, cfg, db))
    return evidence


async def _apply_dify_rag_injection(
    step_id: str,
    metadata: dict,
    variables: dict[str, str],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        from app.services.rag_service import get_rag_retriever
    except Exception:
        return []

    bindings = (((cfg.get("dify") or {}).get("step_bindings") or {}).get(step_id) or [])
    if not bindings:
        return []

    retriever = get_rag_retriever()
    if not retriever.enabled:
        # 仍为可能引用 ${rag_*} 占位符的模板填空，避免 ${rag_xxx} 原样输出
        for binding in bindings:
            key = binding.get("inject_as")
            if key and key not in variables:
                variables[key] = ""
        return []

    project = (metadata.get("project") or {})
    project_id = str(project.get("project_id") or project.get("id") or "").strip()
    tasks = [
        _retrieve_dify_binding(binding, retriever, metadata, variables, project, project_id)
        for binding in bindings
    ]
    results = await asyncio.gather(*tasks)
    evidence: list[dict[str, Any]] = []

    for result in results:
        inject_as = result.get("inject_as")
        if inject_as:
            _append_injection_value(variables, str(inject_as), result.get("text"))
        if result.get("evidence"):
            evidence.append(result["evidence"])
    return evidence


async def _retrieve_dify_binding(
    binding: dict[str, Any],
    retriever: Any,
    metadata: dict,
    variables: dict[str, str],
    project: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    inject_as = str(binding.get("inject_as") or "").strip()
    if not inject_as:
        return {}
    dataset = binding.get("dataset")
    dynamic = binding.get("dynamic_dataset")
    if dynamic and project_id:
        dataset = dynamic.format(project_id=project_id)
    if not dataset:
        return {"inject_as": inject_as, "text": ""}

    full_query_parts = _query_parts_from_binding(binding, metadata, variables)
    full_raw_query = augment_2026_rule_rag_query(
        str(dataset or ""),
        " ".join(full_query_parts).strip(),
        variables,
        project,
    )
    query_parts = _query_parts_from_binding(binding, metadata, variables, compact_for_dify=True)
    compact_raw_query = " ".join(query_parts).strip()
    compact_raw_query = augment_2026_rule_rag_query(str(dataset or ""), compact_raw_query, variables, project)
    query = _fit_dify_query(compact_raw_query, max_chars=DIFY_QUERY_SAFE_MAX_CHARS)
    if not query:
        return {"inject_as": inject_as, "text": ""}

    top_k = int(binding.get("top_k") or 5)
    try:
        score_threshold = float(binding.get("score_threshold") or 0.0)
    except Exception:
        score_threshold = 0.0
    header = binding.get("header") or f"# RAG 参考（{inject_as}）"
    diagnostics: dict[str, Any] = {}
    try:
        if hasattr(retriever, "retrieve_as_text_with_diagnostics"):
            text, diagnostics = await retriever.retrieve_as_text_with_diagnostics(
                dataset=dataset,
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                header=header,
            )
        else:
            try:
                text = await retriever.retrieve_as_text(
                    dataset=dataset,
                    query=query,
                    top_k=top_k,
                    score_threshold=score_threshold,
                    header=header,
                )
            except TypeError:
                text = await retriever.retrieve_as_text(
                    dataset=dataset,
                    query=query,
                    top_k=top_k,
                    header=header,
                )
    except TypeError:
        text = await retriever.retrieve_as_text(
            dataset=dataset,
            query=query,
            top_k=top_k,
            header=header,
        )
    except Exception as exc:
        text = ""
        diagnostics = {"status": "exception", "error": f"{type(exc).__name__}: {str(exc)[:180]}"}

    diagnostic_count = diagnostics.get("count")
    try:
        evidence_count = int(diagnostic_count)
    except Exception:
        evidence_count = 1 if str(text or "").strip() else 0
    evidence = {
        "kind": "dify",
        "backend": "dify",
        "source": str(dataset),
        "inject_as": inject_as,
        "query": query,
        "query_chars": len(query),
        "raw_query_chars": len(full_raw_query),
        "query_compacted": len(full_raw_query) != len(query),
        "top_k": top_k,
        "score_threshold": score_threshold,
        "header": str(header),
        "count": max(0, evidence_count),
        "status": str((diagnostics or {}).get("status") or ("ok" if str(text or "").strip() else "empty_or_failed")),
        "items": [],
    }
    if diagnostics.get("method"):
        evidence["method"] = str(diagnostics.get("method"))
    if diagnostics.get("error"):
        evidence["error"] = str(diagnostics.get("error"))[:180]
    if diagnostics.get("status_code"):
        evidence["status_code"] = diagnostics.get("status_code")
    return {"inject_as": inject_as, "text": text, "evidence": evidence}


def _normalize_query_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _clip_query_part(field: str, value: str) -> str:
    cleaned = _normalize_query_text(value)
    if not cleaned:
        return ""
    limit = _DIFY_QUERY_FIELD_BUDGETS.get(field)
    if not limit or len(cleaned) <= limit:
        return cleaned
    # Prefer the first sentence-like unit because user-entered outlines usually
    # put the current episode's strongest premise up front.
    pieces = [part.strip() for part in re.split(r"[。！？!?；;\n]", cleaned) if part.strip()]
    head = pieces[0] if pieces else cleaned
    if len(head) > limit:
        head = head[:max(1, limit - 1)]
    return head.rstrip("，,、：:；;。！？!?") + "…"


def _fit_dify_query(query: str, *, max_chars: int = DIFY_QUERY_SAFE_MAX_CHARS) -> str:
    cleaned = _normalize_query_text(query)
    if len(cleaned) <= max_chars:
        return cleaned
    parts = [part for part in cleaned.split(" ") if part]
    fitted: list[str] = []
    used = 0
    for part in parts:
        sep = 1 if fitted else 0
        if used + sep + len(part) <= max_chars:
            fitted.append(part)
            used += sep + len(part)
            continue
        remaining = max_chars - used - sep
        if remaining >= 12:
            fitted.append(part[:max(1, remaining - 1)].rstrip("，,、：:；;。！？!?") + "…")
        break
    return " ".join(fitted).strip() or cleaned[:max_chars].rstrip()


def _apply_knowledge_chunk_injection(
    step_id: str,
    metadata: dict,
    variables: dict[str, str],
    cfg: dict[str, Any],
    db: Session | None,
) -> list[dict[str, Any]]:
    local_cfg = (cfg.get("knowledge_chunks") or {})
    if not db or local_cfg.get("enabled") is False:
        _set_empty_for_local_bindings(step_id, variables, local_cfg)
        return []

    bindings = ((local_cfg.get("step_bindings") or {}).get(step_id) or [])
    if not bindings:
        return []

    try:
        from app.services.knowledge_chunk_service import build_knowledge_chunk_context
    except Exception:
        _set_empty_for_bindings(bindings, variables)
        return []

    evidence: list[dict[str, Any]] = []
    for binding in bindings:
        inject_as = str(binding.get("inject_as") or "").strip()
        if not inject_as:
            continue

        query_parts = _query_parts_from_binding(binding, metadata, variables)
        queries = _dedupe_query_candidates([" ".join(query_parts).strip(), *query_parts])
        if not queries:
            variables.setdefault(inject_as, "")
            continue

        doc_types = _normalize_binding_list(binding.get("doc_types") or binding.get("types"))
        top_k = _safe_int(binding.get("top_k"), default=4, minimum=1, maximum=12)
        max_chars = _safe_int(binding.get("max_chars"), default=2400, minimum=500, maximum=8000)
        header = str(binding.get("header") or "# 本地知识分块参考").strip()

        context_text = ""
        matched_result: dict[str, Any] = {}
        matched_query = ""
        for query in queries:
            try:
                result = build_knowledge_chunk_context(
                    db,
                    query,
                    doc_types=doc_types,
                    limit=top_k,
                    max_chars=max_chars,
                    header=header,
                    auto_rebuild=False,
                )
            except Exception:
                result = {}
            if result.get("count"):
                context_text = str(result.get("text") or "").strip()
                matched_result = result
                matched_query = query
                break

        _append_injection_value(variables, inject_as, context_text)
        if context_text and matched_result.get("count"):
            evidence.append({
                "kind": "local_knowledge_chunk",
                "backend": str(matched_result.get("backend") or "knowledge_chunks_like"),
                "source": "knowledge_chunks",
                "inject_as": inject_as,
                "query": matched_query,
                "doc_types": doc_types or [],
                "top_k": top_k,
                "max_chars": max_chars,
                "header": header,
                "count": int(matched_result.get("count") or 0),
                "items": _compact_chunk_evidence_items(matched_result.get("items") or []),
            })
    return evidence


def _query_parts_from_binding(
    binding: dict[str, Any],
    metadata: dict,
    variables: dict[str, str],
    *,
    compact_for_dify: bool = False,
) -> list[str]:
    query_fields = binding.get("query_fields") or []
    if isinstance(query_fields, str):
        query_fields = [query_fields]

    # 对 draft_episode 做语义化增强 —— 单纯一个数字"5"对 RAG 检索语义价值低，
    # 改成"第5集 蓄势段/爬升段/风暴段/高潮段"作为更具语义的检索词
    query_parts: list[str] = []
    try:
        project_meta = metadata.get("project") or {}
        total_eps = int(project_meta.get("confirmed_total_episodes") or project_meta.get("episode_count") or 0)
    except Exception:
        total_eps = 0
    for field in query_fields:
        f = str(field or "").strip()
        v = str(variables.get(f, "")).strip()
        if not v:
            continue
        if f == "draft_episode":
            query_parts.append(_episode_query_label(v, total_eps) if total_eps else f"第{v}集")
        else:
            query_parts.append(_clip_query_part(f, v) if compact_for_dify else v)
    return [part for part in query_parts if part]


def _episode_query_label(value: str, total_eps: int) -> str:
    try:
        ep_n = int(value)
    except Exception:
        ep_n = 0
    if ep_n <= 0:
        return value
    pct = ep_n / max(1, total_eps)
    if pct <= 0.15:
        seg_label = "蓄势段 开场建立"
    elif pct <= 0.45:
        seg_label = "爬升段 拉扯试探"
    elif pct <= 0.80:
        seg_label = "风暴段 反转爆点 付费墙"
    else:
        seg_label = "高潮段 收束爆发"
    return f"第{ep_n}集 {seg_label}"


def _append_injection_value(variables: dict[str, str], inject_as: str, text: str | None) -> None:
    existing = str(variables.get(inject_as) or "").strip()
    incoming = str(text or "").strip()
    if existing and incoming:
        variables[inject_as] = f"{existing}\n\n---\n\n{incoming}"
    elif incoming:
        variables[inject_as] = incoming
    else:
        variables.setdefault(inject_as, "")


def _set_empty_for_local_bindings(step_id: str, variables: dict[str, str], local_cfg: dict[str, Any]) -> None:
    bindings = ((local_cfg.get("step_bindings") or {}).get(step_id) or [])
    _set_empty_for_bindings(bindings, variables)


def _set_empty_for_bindings(bindings: list[dict[str, Any]], variables: dict[str, str]) -> None:
    for binding in bindings:
        key = binding.get("inject_as")
        if key and key not in variables:
            variables[key] = ""


def _normalize_binding_list(value: Any) -> list[str] | None:
    if not value:
        return None
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        for part in str(item).split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
    return normalized or None


def _dedupe_query_candidates(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _compact_chunk_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        source_path = str(item.get("source_path") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        title = str(item.get("title") or source_path or source_id).strip()
        content = str(item.get("content") or "").strip()
        compacted.append({
            "source_type": str(item.get("source_type") or "").strip(),
            "source_id": source_id,
            "source_path": source_path,
            "chunk_index": int(item.get("chunk_index") or 0),
            "title": title[:120],
            "excerpt": content[:180],
        })
    return compacted
