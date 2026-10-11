"""Research-only stage tracing for the short-drama generation chain.

The tracer is inactive unless ``MOXI_RESEARCH_STAGE_TRACE_PATH`` is set by a
local experiment script. It gives timeout investigations a durable breadcrumb
trail even when the generation subprocess is killed.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


TRACE_PATH_ENV = "MOXI_RESEARCH_STAGE_TRACE_PATH"
TRACE_ID_ENV = "MOXI_RESEARCH_STAGE_TRACE_ID"


def _trace_path() -> Path | None:
    raw = str(os.environ.get(TRACE_PATH_ENV) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _safe_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    if not extra:
        return {}
    try:
        json.dumps(extra, ensure_ascii=False, default=str)
        return dict(extra)
    except Exception:
        return {key: str(value) for key, value in extra.items()}


def _request_meta(req: "TestingScriptRequest" | None) -> dict[str, Any]:
    if req is None:
        return {}
    return {
        "mode": str(getattr(req, "mode", "") or ""),
        "episode_no": int(getattr(req, "episode_no", 0) or 0),
        "scene_no": int(getattr(req, "scene_no", 0) or 0),
        "segment_id": str(getattr(req, "segment_id", "") or ""),
        "provider": str(getattr(req, "generation_provider", "") or ""),
        "model": str(getattr(req, "generation_model", "") or ""),
    }


def record_stage_trace(
    req: "TestingScriptRequest" | None,
    stage: str,
    event: str,
    *,
    attempt: int | None = None,
    duration_seconds: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    path = _trace_path()
    if path is None:
        return
    row: dict[str, Any] = {
        "trace_id": str(os.environ.get(TRACE_ID_ENV) or "").strip(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage or "").strip(),
        "event": str(event or "").strip(),
        **_request_meta(req),
    }
    if attempt is not None:
        row["attempt"] = int(attempt)
    if duration_seconds is not None:
        row["duration_seconds"] = round(float(duration_seconds), 3)
    row.update(_safe_extra(extra))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # Tracing must never break the user-facing generation flow.
        return


@contextmanager
def timed_stage(
    req: "TestingScriptRequest" | None,
    stage: str,
    *,
    attempt: int | None = None,
    extra: dict[str, Any] | None = None,
) -> Iterator[None]:
    started = time.perf_counter()
    record_stage_trace(req, stage, "start", attempt=attempt, extra=extra)
    try:
        yield
    except Exception as exc:
        record_stage_trace(
            req,
            stage,
            "error",
            attempt=attempt,
            duration_seconds=time.perf_counter() - started,
            extra={"error": f"{type(exc).__name__}: {str(exc)[:160]}", **_safe_extra(extra)},
        )
        raise
    record_stage_trace(
        req,
        stage,
        "end",
        attempt=attempt,
        duration_seconds=time.perf_counter() - started,
        extra=extra,
    )
