"""高级生成模式的 LangChain/LangGraph 编排适配层。

LangChain / LangGraph 是可选依赖：可用时编译 writer-reviewer-decision 探针；
不可用时返回内置顺序状态机预览，避免阻断现有主链路。
"""

from __future__ import annotations

import importlib
from typing import Any, TypedDict

from app.services.short_drama_advanced_generation import (
    MODE_ID,
    MODE_LABEL,
    build_advanced_generation_plan,
    resolve_step_generation_route,
)


WORKFLOW_ID = "writer_reviewer_decision"
WORKFLOW_LABEL = "Writer / Reviewer / Decision 编排"
DEFAULT_MAX_REVIEW_ROUNDS = 2


class _ProbeState(TypedDict, total=False):
    trace: list[str]
    review_passed: bool
    round: int
    max_review_rounds: int
    final: str


def get_orchestration_status() -> dict[str, Any]:
    """返回 LangChain/LangGraph 编排能力状态。"""
    deps = _dependency_status()
    compiled = False
    probe_error = ""
    if deps["available"]:
        probe = _compile_langgraph_probe(DEFAULT_MAX_REVIEW_ROUNDS)
        compiled = bool(probe.get("compiled"))
        probe_error = str(probe.get("error") or "")
        if not compiled:
            deps = {
                **deps,
                "available": False,
                "backend": "builtin_fallback",
                "degraded": True,
                "error": probe_error or deps.get("error", ""),
            }
    return {
        "workflow_id": WORKFLOW_ID,
        "workflow_label": WORKFLOW_LABEL,
        "available": bool(deps["available"]),
        "backend": deps["backend"],
        "degraded": bool(deps["degraded"]),
        "langchain_available": bool(deps["langchain_available"]),
        "langgraph_available": bool(deps["langgraph_available"]),
        "langchain_version": deps.get("langchain_version", ""),
        "langgraph_version": deps.get("langgraph_version", ""),
        "compiled": compiled,
        "error": probe_error or deps.get("error", ""),
    }


def build_writer_reviewer_decision_orchestration(
    metadata: dict[str, Any],
    base_generation_kwargs: dict[str, Any] | None = None,
    max_review_rounds: int = DEFAULT_MAX_REVIEW_ROUNDS,
) -> dict[str, Any]:
    """构建 writer-reviewer-decision 编排预览，不触发真实 LLM 调用。"""
    base_kwargs = _clean_base_generation_kwargs(base_generation_kwargs)
    max_rounds = _clamp_rounds(max_review_rounds)
    route_plan = build_advanced_generation_plan(metadata, base_kwargs)
    writer_route = resolve_step_generation_route("script_draft", metadata, base_kwargs)
    reviewer_route = resolve_step_generation_route("quality_check", metadata, base_kwargs)

    deps = _dependency_status()
    compiled = False
    probe_trace: list[str] = []
    error = str(deps.get("error") or "")
    if deps["available"]:
        probe = _compile_langgraph_probe(max_rounds)
        compiled = bool(probe.get("compiled"))
        probe_trace = [str(item) for item in probe.get("trace") or []]
        error = str(probe.get("error") or error)
        if not compiled:
            deps = {
                **deps,
                "available": False,
                "backend": "builtin_fallback",
                "degraded": True,
            }

    nodes = _workflow_nodes(writer_route, reviewer_route)
    edges = _workflow_edges(max_rounds)
    fallback_trace = ["writer", "reviewer", "decision"]
    return {
        "workflow_id": WORKFLOW_ID,
        "workflow_label": WORKFLOW_LABEL,
        "mode_id": MODE_ID,
        "mode_label": MODE_LABEL,
        "enabled": bool(route_plan.get("enabled")),
        "profile_id": route_plan.get("profile_id", "short_drama"),
        "profile_label": route_plan.get("profile_label", "短剧"),
        "backend": deps["backend"],
        "available": bool(deps["available"]),
        "degraded": bool(deps["degraded"]),
        "compiled": compiled,
        "error": error,
        "max_review_rounds": max_rounds,
        "entrypoint": "writer",
        "nodes": nodes,
        "edges": edges,
        "probe_trace": probe_trace or fallback_trace,
        "routes": route_plan.get("routes", []),
    }


def _dependency_status() -> dict[str, Any]:
    langchain = _optional_import("langchain")
    langgraph = _optional_import("langgraph.graph")
    errors = [item["error"] for item in (langchain, langgraph) if item["error"]]
    available = not errors
    return {
        "available": available,
        "backend": "langgraph" if available else "builtin_fallback",
        "degraded": not available,
        "langchain_available": langchain["available"],
        "langgraph_available": langgraph["available"],
        "langchain_version": langchain["version"],
        "langgraph_version": langgraph["version"],
        "error": "；".join(errors),
    }


def _optional_import(module_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
        root_name = module_name.split(".", 1)[0]
        root_module = importlib.import_module(root_name)
        version = str(
            getattr(root_module, "__version__", "")
            or getattr(module, "__version__", "")
            or ""
        )
        return {"available": True, "version": version, "error": ""}
    except Exception as exc:
        return {
            "available": False,
            "version": "",
            "error": f"{module_name} unavailable: {exc}",
        }


def _compile_langgraph_probe(max_review_rounds: int) -> dict[str, Any]:
    try:
        from langgraph.graph import END, StateGraph  # type: ignore

        def writer(state: _ProbeState) -> _ProbeState:
            trace = list(state.get("trace") or [])
            return {
                **state,
                "trace": trace + ["writer"],
                "round": int(state.get("round") or 0) + 1,
            }

        def reviewer(state: _ProbeState) -> _ProbeState:
            trace = list(state.get("trace") or [])
            return {**state, "trace": trace + ["reviewer"]}

        def decision(state: _ProbeState) -> _ProbeState:
            trace = list(state.get("trace") or [])
            if state.get("review_passed"):
                final = "approved"
            elif int(state.get("round") or 0) >= int(state.get("max_review_rounds") or 1):
                final = "escalated"
            else:
                final = "revise"
            return {**state, "trace": trace + ["decision"], "final": final}

        def branch(state: _ProbeState) -> str:
            final = state.get("final")
            if final == "approved":
                return "approved"
            if final == "revise":
                return "revise"
            return "escalated"

        graph = StateGraph(_ProbeState)
        graph.add_node("writer", writer)
        graph.add_node("reviewer", reviewer)
        graph.add_node("decision", decision)
        graph.set_entry_point("writer")
        graph.add_edge("writer", "reviewer")
        graph.add_edge("reviewer", "decision")
        graph.add_conditional_edges(
            "decision",
            branch,
            {"approved": END, "revise": "writer", "escalated": END},
        )
        compiled_graph = graph.compile()
        result = compiled_graph.invoke({
            "trace": [],
            "review_passed": True,
            "round": 0,
            "max_review_rounds": _clamp_rounds(max_review_rounds),
        })
        return {
            "compiled": True,
            "trace": list(result.get("trace") or []),
            "error": "",
        }
    except Exception as exc:
        return {
            "compiled": False,
            "trace": [],
            "error": f"langgraph probe failed: {exc}",
        }


def _workflow_nodes(writer_route, reviewer_route) -> list[dict[str, Any]]:
    return [
        _route_node(
            "writer",
            "创作执行",
            "script_draft",
            writer_route,
            "生成剧本初稿或修订稿",
        ),
        _route_node(
            "reviewer",
            "质量评审",
            "quality_check",
            reviewer_route,
            "检查钩子、节奏、人物、可拍性和规则约束",
        ),
        {
            "id": "decision",
            "role": "decision",
            "role_label": "决策收口",
            "step_id": "decision",
            "label": "决策收口",
            "provider": "",
            "model": "",
            "temperature": None,
            "purpose": "根据 reviewer 结论决定通过、返工或升级人工处理",
        },
    ]


def _route_node(node_id: str, label: str, step_id: str, route, purpose: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "role": route.role,
        "role_label": route.role_label,
        "step_id": step_id,
        "label": label,
        "provider": route.generation_kwargs.get("provider", ""),
        "model": route.generation_kwargs.get("model", ""),
        "temperature": route.temperature,
        "purpose": purpose,
    }


def _workflow_edges(max_review_rounds: int) -> list[dict[str, str]]:
    return [
        {"from": "writer", "to": "reviewer", "condition": "draft_created"},
        {"from": "reviewer", "to": "decision", "condition": "review_completed"},
        {"from": "decision", "to": "done", "condition": "approved"},
        {
            "from": "decision",
            "to": "writer",
            "condition": f"needs_revision_and_rounds_lt_{max_review_rounds}",
        },
        {
            "from": "decision",
            "to": "manual_review",
            "condition": f"needs_revision_and_rounds_gte_{max_review_rounds}",
        },
    ]


def _clean_base_generation_kwargs(raw: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in ("provider", "model"):
        value = str((raw or {}).get(key) or "").strip()
        if value:
            cleaned[key] = value
    return cleaned


def _clamp_rounds(value: int) -> int:
    try:
        rounds = int(value)
    except Exception:
        rounds = DEFAULT_MAX_REVIEW_ROUNDS
    return max(1, min(rounds, 5))
