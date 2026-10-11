# -*- coding: utf-8 -*-
"""Prepare a longform industrial launch-floor research workspace.

This script creates the auditable shell for 30-60 episode industrial research.
It does not generate scripts, does not score quality, and does not produce an
industrial pass. The first job is to make the longform continuity evidence
complete before any model output is treated as a launch candidate.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from scoring_common import ROOT, atomic_json_dump, now_iso


LONGFORM_ROOT = ROOT / "data" / "longform_industrial"
DEFAULT_EXPERIMENT_ID = "LONGFORM-LAUNCH-FLOOR-20260531"

TRIAL_FIELDS = [
    "experiment_id",
    "created_at",
    "episode_no",
    "episode_range",
    "episode_title",
    "episode_function",
    "start_state",
    "episode_event",
    "end_state",
    "next_hook",
    "character_state_delta",
    "plot_state_delta",
    "visual_signature",
    "visual_repeat_risk",
    "role_gate",
    "continuity_gate",
    "visual_gate",
    "hard_reject_gate",
    "script_text_path",
    "model_scorer",
    "model_score_candidate",
    "model_score_candidate_status",
    "human_score",
    "human_review_status",
    "industrial_pass",
    "industrial_pass_basis",
    "failure_gate",
    "failure_reason",
    "status",
    "notes",
]

SEED_FIELDS = [
    "seed_id",
    "seed_type",
    "setup_episode",
    "payoff_episode",
    "promise",
    "current_status",
    "notes",
]


def episode_range_label(episode_no: int) -> str:
    if episode_no <= 10:
        return "1-10_setup_and_lock"
    if episode_no <= 20:
        return "11-20_escalation_and_reversal"
    if episode_no <= 30:
        return "21-30_payoff_and_launch_floor_close"
    if episode_no <= 45:
        return "31-45_extended_escalation"
    return "46-60_final_payoff"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def empty_jsonl(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def build_trials(experiment_id: str, episode_count: int, created_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode_no in range(1, episode_count + 1):
        rows.append(
            {
                "experiment_id": experiment_id,
                "created_at": created_at,
                "episode_no": episode_no,
                "episode_range": episode_range_label(episode_no),
                "episode_title": "content_pending",
                "episode_function": "content_pending",
                "start_state": "content_pending",
                "episode_event": "content_pending",
                "end_state": "content_pending",
                "next_hook": "content_pending",
                "character_state_delta": "content_pending",
                "plot_state_delta": "content_pending",
                "visual_signature": "content_pending",
                "visual_repeat_risk": "not_checked",
                "role_gate": "not_checked",
                "continuity_gate": "not_checked",
                "visual_gate": "not_checked",
                "hard_reject_gate": "not_checked",
                "model_score_candidate_status": "not_scored",
                "human_review_status": "not_reviewed",
                "industrial_pass": "",
                "status": "episode_card_created_content_pending",
                "notes": "placeholder row; not generated text and not launch evidence",
            }
        )
    return rows


def build_series_bible(args: argparse.Namespace, created_at: str) -> dict[str, Any]:
    return {
        "artifact": "series_bible",
        "created_at": created_at,
        "status": "schema_ready_content_pending",
        "title": args.title,
        "genre": args.genre,
        "episode_count_target": args.episode_count,
        "launch_floor_goal": "30 complete episodes first, then extend to 60 episodes",
        "high_score_goal": "keep 90 as long-term target for key episodes",
        "audience": "content_pending",
        "core_hook": "content_pending",
        "commercial_promise": "content_pending",
        "source_boundary": [
            "This bible is a structure shell until user-approved story material is filled.",
            "Do not treat content_pending fields as generated evidence.",
        ],
    }


def build_character_bible(created_at: str) -> dict[str, Any]:
    return {
        "artifact": "character_bible",
        "created_at": created_at,
        "status": "schema_ready_content_pending",
        "required_fields": [
            "name",
            "identity",
            "relationship_to_core_conflict",
            "motivation",
            "secret_or_bottom_card",
            "ability_boundary",
            "emotional_arc",
            "visual_signature",
            "first_appearance_function",
        ],
        "characters": [],
        "consistency_rule": "No episode may change identity, motive, ability boundary, or relationship state without recording a character_state_delta.",
    }


def build_plot_bible(args: argparse.Namespace, created_at: str) -> dict[str, Any]:
    return {
        "artifact": "plot_bible",
        "created_at": created_at,
        "status": "schema_ready_content_pending",
        "episode_count_target": args.episode_count,
        "acts": [
            {
                "range": "1-10",
                "function": "setup_and_lock_core_conflict",
                "required_outcome": "content_pending",
            },
            {
                "range": "11-20",
                "function": "escalation_and_reversal",
                "required_outcome": "content_pending",
            },
            {
                "range": "21-30",
                "function": "payoff_and_launch_floor_close",
                "required_outcome": "content_pending",
            },
            {
                "range": "31-60",
                "function": "extension_only_after_30_episode_floor_passes",
                "required_outcome": "content_pending",
            },
        ],
        "paid_wall_candidates": [],
        "climax_candidates": [],
    }


def build_visual_bible(created_at: str) -> dict[str, Any]:
    return {
        "artifact": "visual_bible",
        "created_at": created_at,
        "status": "schema_ready_content_pending",
        "locations": [],
        "action_families": [],
        "props": [],
        "repeat_rules": [
            "Do not reuse the same location-action-emotion combination in adjacent episodes.",
            "Every episode must declare one visual_signature.",
            "Every repeated location needs a new action, prop, or power relation.",
        ],
    }


def write_workspace(args: argparse.Namespace) -> Path:
    created_at = now_iso()
    workdir = (LONGFORM_ROOT / args.experiment_id).resolve()
    if workdir.exists() and not args.overwrite:
        raise SystemExit(f"workspace already exists: {workdir} (use --overwrite to refresh generated shell files)")
    workdir.mkdir(parents=True, exist_ok=True)
    for subdir in ["bibles", "episodes", "scripts", "gates", "reports", "scores"]:
        (workdir / subdir).mkdir(parents=True, exist_ok=True)

    experiment = {
        "experiment_id": args.experiment_id,
        "created_at": created_at,
        "status": "prepared_longform_launch_floor_no_generation",
        "title": args.title,
        "genre": args.genre,
        "episode_count_target": args.episode_count,
        "research_boundary": [
            "No script text is generated by this preparation script.",
            "No human_score is produced.",
            "No industrial_pass is produced.",
            "All model scores, if later added, must remain model_score_candidate_not_validated until validation.",
        ],
        "industrial_floor": {
            "first_floor": "30 complete episodes with continuity and visual gates",
            "extension_floor": "60 episodes only after 30-episode floor passes",
            "industry_pain_points": [
                "role_consistency",
                "narrative_consistency",
                "visual_repetition_control",
            ],
        },
        "required_files": {
            "trials": "trials.csv",
            "failure_archive": "failure_archive.jsonl",
            "ledger": "ledger.md",
            "report": "report.md",
            "series_bible": "bibles/series_bible.json",
            "character_bible": "bibles/character_bible.json",
            "plot_bible": "bibles/plot_bible.json",
            "visual_bible": "bibles/visual_bible.json",
            "seed_ledger": "seed_ledger.csv",
        },
    }
    atomic_json_dump(experiment, workdir / "experiment.json")
    atomic_json_dump(build_series_bible(args, created_at), workdir / "bibles" / "series_bible.json")
    atomic_json_dump(build_character_bible(created_at), workdir / "bibles" / "character_bible.json")
    atomic_json_dump(build_plot_bible(args, created_at), workdir / "bibles" / "plot_bible.json")
    atomic_json_dump(build_visual_bible(created_at), workdir / "bibles" / "visual_bible.json")
    write_csv(workdir / "trials.csv", TRIAL_FIELDS, build_trials(args.experiment_id, args.episode_count, created_at))
    write_csv(workdir / "seed_ledger.csv", SEED_FIELDS, [])
    empty_jsonl(workdir / "failure_archive.jsonl")
    (workdir / "ledger.md").write_text(
        "\n".join(
            [
                f"# {args.experiment_id} Ledger",
                "",
                "- Status: prepared_longform_launch_floor_no_generation",
                "- Current stage: P1/P2 shell ready; story content pending.",
                "- Next: fill series, character, plot, visual, and seed bibles with approved story material.",
                "- Boundary: no human_score, no industrial_pass, no 30-episode launch claim yet.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (workdir / "report.md").write_text(
        "\n".join(
            [
                f"# {args.experiment_id} Report",
                "",
                "## Material Passport",
                "",
                "- Artifact: longform_industrial_workspace",
                f"- Created at: {created_at}",
                "- Verification Status: PREPARED",
                "- Scope: 30-60 episode launch-floor workspace shell.",
                "",
                "## Boundary",
                "",
                "- This workspace has no generated episode scripts yet.",
                "- This workspace has no human scores.",
                "- This workspace has no industrial pass decision.",
                "- It is ready to receive approved story material and generated episodes.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return workdir


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a longform industrial launch-floor workspace.")
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID)
    parser.add_argument("--title", default="pending_longform_project")
    parser.add_argument("--genre", default="pending")
    parser.add_argument("--episode-count", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.episode_count < 30 or args.episode_count > 60:
        raise SystemExit("episode-count must be between 30 and 60 for this launch-floor protocol")
    workdir = write_workspace(args)
    print(json.dumps({"event": "prepared", "workdir": str(workdir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
