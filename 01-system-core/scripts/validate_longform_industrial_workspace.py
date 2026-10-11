# -*- coding: utf-8 -*-
"""Validate a longform industrial launch-floor workspace.

The validator checks evidence completeness and field discipline. It deliberately
does not turn candidate model scores into human scores or industrial decisions.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from prepare_longform_industrial_workspace import TRIAL_FIELDS


REQUIRED_FILES = [
    "experiment.json",
    "trials.csv",
    "failure_archive.jsonl",
    "ledger.md",
    "report.md",
    "seed_ledger.csv",
    "bibles/series_bible.json",
    "bibles/character_bible.json",
    "bibles/plot_bible.json",
    "bibles/visual_bible.json",
]

PENDING_MARKERS = {"", "content_pending", "not_checked", "not_scored", "not_reviewed"}
DEFAULT_FLOOR_ANCHOR = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "industrial_floor" / "MINGYUE-DUZHAO-LOWER-BOUND-20260531"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_trials(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [field for field in TRIAL_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"trials.csv missing columns: {missing}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def summarize_floor_anchor(anchor_dir: Path | None) -> dict[str, Any]:
    if not anchor_dir:
        return {
            "ready": False,
            "reason": "floor_anchor_not_requested",
        }
    anchor_dir = anchor_dir.expanduser().resolve()
    trials_path = anchor_dir / "trials.csv"
    experiment_path = anchor_dir / "experiment.json"
    if not trials_path.exists() or not experiment_path.exists():
        return {
            "ready": False,
            "anchor_dir": str(anchor_dir),
            "reason": "missing_floor_anchor_files",
        }
    rows: list[dict[str, str]] = []
    with trials_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    scores: list[float] = []
    for row in rows:
        try:
            scores.append(float(row.get("human_floor_score") or ""))
        except Exception:
            continue
    if not scores:
        return {
            "ready": False,
            "anchor_dir": str(anchor_dir),
            "reason": "no_human_floor_scores",
        }
    experiment = load_json(experiment_path)
    score_mean = round(sum(scores) / len(scores), 3)
    calibrated_floor = experiment.get("data_calibrated_floor_score") or {}
    user_prior = experiment.get("user_holistic_prior_score") or {}
    floor_pass_score = calibrated_floor.get("recommended_comparison_value")
    floor_score_basis = calibrated_floor.get("score_basis") or "data_calibrated_floor_score"
    if floor_pass_score is None:
        floor_pass_score = score_mean
        floor_score_basis = "legacy_mean_human_floor_score"
    anchor_semantics = experiment.get("anchor_semantics") or {}
    return {
        "ready": True,
        "anchor_dir": str(anchor_dir),
        "sample_id": experiment.get("experiment_id") or rows[0].get("sample_id") or "",
        "title": experiment.get("title") or rows[0].get("title") or "",
        "episode_count": len(scores),
        "mean_human_floor_score": score_mean,
        "floor_pass_score": floor_pass_score,
        "floor_score_basis": floor_score_basis,
        "data_calibrated_floor_score": calibrated_floor,
        "user_holistic_prior_score": user_prior,
        "user_holistic_prior_range": [user_prior.get("min"), user_prior.get("max")] if user_prior else [],
        "min_human_floor_score": min(scores),
        "max_human_floor_score": max(scores),
        "below_50_count": sum(1 for score in scores if score < 50),
        "below_60_count": sum(1 for score in scores if score < 60),
        "anchor_type": anchor_semantics.get("anchor_type", ""),
        "floor_dimensions": anchor_semantics.get("floor_dimensions", []),
        "prohibited_uses": anchor_semantics.get("prohibited_uses", []),
        "score_field": "human_floor_score",
        "boundary": "lower_bound_anchor_only_not_model_score_not_industrial_pass",
    }


def has_pending_content(row: dict[str, str]) -> bool:
    content_fields = [
        "episode_title",
        "episode_function",
        "start_state",
        "episode_event",
        "end_state",
        "next_hook",
        "character_state_delta",
        "plot_state_delta",
        "visual_signature",
    ]
    return any(row.get(field, "") in PENDING_MARKERS for field in content_fields)


def validate_workspace(
    workspace: Path,
    require_content: bool = False,
    floor_anchor: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace.expanduser().resolve()
    missing_files = [name for name in REQUIRED_FILES if not (workspace / name).exists()]
    experiment = load_json(workspace / "experiment.json") if not missing_files else {}
    rows = read_trials(workspace / "trials.csv") if (workspace / "trials.csv").exists() else []
    expected_count = int(experiment.get("episode_count_target") or 0)
    wrong_episode_count = expected_count and len(rows) != expected_count
    human_score_violations = [row["episode_no"] for row in rows if row.get("human_score")]
    industrial_pass_violations = [row["episode_no"] for row in rows if row.get("industrial_pass")]
    candidate_status_violations = [
        row["episode_no"]
        for row in rows
        if row.get("model_score_candidate") and row.get("model_score_candidate_status") != "model_score_candidate_not_validated"
    ]
    pending_rows = [row["episode_no"] for row in rows if has_pending_content(row)]
    gate_rows_not_ready = [
        row["episode_no"]
        for row in rows
        if row.get("role_gate") != "pass" or row.get("continuity_gate") != "pass" or row.get("visual_gate") != "pass"
    ]
    bible_payloads = {
        "series": load_json(workspace / "bibles" / "series_bible.json") if (workspace / "bibles" / "series_bible.json").exists() else {},
        "character": load_json(workspace / "bibles" / "character_bible.json") if (workspace / "bibles" / "character_bible.json").exists() else {},
        "plot": load_json(workspace / "bibles" / "plot_bible.json") if (workspace / "bibles" / "plot_bible.json").exists() else {},
        "visual": load_json(workspace / "bibles" / "visual_bible.json") if (workspace / "bibles" / "visual_bible.json").exists() else {},
    }
    bible_schema_ready = all(payload.get("status") for payload in bible_payloads.values())
    floor_ready = (
        not missing_files
        and not wrong_episode_count
        and not human_score_violations
        and not industrial_pass_violations
        and not candidate_status_violations
        and not pending_rows
        and not gate_rows_not_ready
    )
    if not require_content:
        floor_ready = False
    floor_anchor_summary = summarize_floor_anchor(floor_anchor)
    return {
        "event": "validated",
        "workspace": str(workspace),
        "schema_ready": not missing_files and not wrong_episode_count and bible_schema_ready,
        "launch_floor_ready": floor_ready,
        "require_content": require_content,
        "expected_episode_count": expected_count,
        "actual_episode_count": len(rows),
        "missing_files": missing_files,
        "human_score_violations": human_score_violations,
        "industrial_pass_violations": industrial_pass_violations,
        "candidate_status_violations": candidate_status_violations,
        "pending_content_count": len(pending_rows),
        "gate_not_ready_count": len(gate_rows_not_ready),
        "floor_anchor": floor_anchor_summary,
        "scientific_boundary": "schema_ready is not launch_floor_ready; pending content cannot be claimed as generated episodes",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate longform industrial workspace.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--require-content", action="store_true")
    parser.add_argument("--floor-anchor", type=Path, default=DEFAULT_FLOOR_ANCHOR)
    parser.add_argument("--no-floor-anchor", action="store_true")
    args = parser.parse_args()
    floor_anchor = None if args.no_floor_anchor else args.floor_anchor
    result = validate_workspace(args.workspace, require_content=args.require_content, floor_anchor=floor_anchor)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["missing_files"] or result["human_score_violations"] or result["industrial_pass_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
