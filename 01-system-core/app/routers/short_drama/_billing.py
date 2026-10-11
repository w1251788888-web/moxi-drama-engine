"""Billing helpers shared by short-drama user-facing LLM routes."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor
from app.routers.projects._helpers import _get_project_for_actor_or_404
from app.services.saas_access_service import (
    charge_access_key_for_generation,
    ensure_access_key_can_spend,
    record_generation_failure_without_charge,
)


def ensure_short_drama_project_access(
    db: Session,
    project_id: str,
    actor: ProjectAccessActor,
    *,
    require_credit: bool = True,
) -> None:
    if actor.is_admin:
        return
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise HTTPException(status_code=403, detail="缺少项目上下文，无法校验用户访问权限")
    _get_project_for_actor_or_404(db, normalized_project_id, actor)
    if require_credit:
        try:
            ensure_access_key_can_spend(db, actor.access_key_id)
        except ValueError as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc


def usage_has_billable_call(usage_metrics: dict[str, Any]) -> bool:
    return (
        int(usage_metrics.get("call_count") or 0) > 0
        or int(usage_metrics.get("input_tokens") or 0) > 0
        or int(usage_metrics.get("output_tokens") or 0) > 0
        or int(usage_metrics.get("total_tokens") or 0) > 0
    )


def _provider_model_from_usage(
    usage_metrics: dict[str, Any],
    *,
    provider: str = "",
    model: str = "",
) -> tuple[str, str]:
    calls = usage_metrics.get("calls")
    if isinstance(calls, list) and calls:
        last = calls[-1]
        if isinstance(last, dict):
            provider = provider or str(last.get("provider") or "")
            model = model or str(last.get("model") or "")
    return provider, model


def charge_short_drama_usage(
    db: Session,
    actor: ProjectAccessActor,
    usage_metrics: dict[str, Any],
    *,
    generation_type: str,
    reason: str,
    provider: str = "",
    model: str = "",
) -> None:
    if not actor.is_user or not usage_has_billable_call(usage_metrics):
        return
    provider, model = _provider_model_from_usage(usage_metrics, provider=provider, model=model)
    try:
        charge_access_key_for_generation(
            db,
            actor.access_key_id,
            prompt_tokens=int(usage_metrics.get("input_tokens") or 0),
            completion_tokens=int(usage_metrics.get("output_tokens") or 0),
            provider=provider,
            model=model,
            generation_type=generation_type,
            reason=reason,
        )
    except ValueError as exc:
        record_generation_failure_without_charge(
            db,
            actor.access_key_id,
            provider=provider,
            model=model,
            generation_type=generation_type,
            reason=f"{reason}失败，未返回结果：{exc}",
        )
        raise HTTPException(status_code=402, detail=str(exc)) from exc


def record_short_drama_failure(
    db: Session,
    actor: ProjectAccessActor,
    *,
    generation_type: str,
    reason: str,
    provider: str = "",
    model: str = "",
) -> None:
    if not actor.is_user:
        return
    record_generation_failure_without_charge(
        db,
        actor.access_key_id,
        provider=provider,
        model=model,
        generation_type=generation_type,
        reason=reason,
    )
