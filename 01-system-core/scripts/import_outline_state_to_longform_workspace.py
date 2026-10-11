# -*- coding: utf-8 -*-
"""Import an explicit outline state into a longform industrial workspace.

This is a bridge between the real product chain and the research workspace:
outline/chat state -> series/character/plot/visual bibles -> episode ledger.

It deliberately does not infer characters from prose, does not generate script
text, does not score quality, and does not write industrial pass decisions.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import prepare_longform_industrial_workspace as prepare
from scoring_common import atomic_json_dump, now_iso


DEFAULT_EXPERIMENT_ID = "LONGFORM-OUTLINE-BRIDGE-20260531"
PENDING = "content_pending"


def _text(value: Any, *, limit: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, list):
        text = "；".join(_text(item) for item in value if _text(item))
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = " ".join(text.replace("\r", "\n").split())
    if limit and len(text) > limit:
        return text[:limit].rstrip()
    return text.strip()


def _first_text(payload: dict[str, Any], keys: tuple[str, ...], *, limit: int = 0) -> str:
    for key in keys:
        value = payload.get(key)
        text = _text(value, limit=limit)
        if text:
            return text
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def load_snapshot(path: Path) -> dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise SystemExit("outline snapshot must be a JSON object")
    return payload


def outline_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    direct = _as_dict(snapshot.get("outline_state"))
    if direct:
        return direct
    workflow_context = _as_dict(snapshot.get("workflow_context"))
    return _as_dict(workflow_context.get("outline_state"))


def outline_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = outline_state(snapshot)
    for value in (
        snapshot.get("outline_data"),
        snapshot.get("outlineData"),
        state.get("outline_data"),
        state.get("outlineData"),
        snapshot.get("outline"),
    ):
        if isinstance(value, dict):
            return value
    return {}


def selling_points(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = outline_data(snapshot)
    for value in (
        snapshot.get("sellingPoints"),
        snapshot.get("selling_points"),
        data.get("sellingPoints"),
        data.get("selling_points"),
    ):
        if isinstance(value, dict):
            return value
    return {}


def explicit_characters(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only explicit character arrays; never infer from raw prose."""
    state = outline_state(snapshot)
    candidates = (
        snapshot.get("outline_characters"),
        snapshot.get("outlineCharacters"),
        state.get("outline_characters"),
        state.get("outlineCharacters"),
        snapshot.get("characters"),
    )
    for value in candidates:
        rows = _as_list(value)
        if rows:
            return rows
    return []


def explicit_episodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    data = outline_data(snapshot)
    candidates = (
        data.get("episodes"),
        snapshot.get("episodes"),
        snapshot.get("episode_outlines"),
    )
    for value in candidates:
        rows = _as_list(value)
        if rows:
            return rows
    return []


def explicit_relationship_table(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    data = outline_data(snapshot)
    candidates = (
        data.get("relationship_table"),
        data.get("relationshipTable"),
        snapshot.get("relationship_table"),
        snapshot.get("relationshipTable"),
    )
    for value in candidates:
        rows = _as_list(value)
        if rows:
            return rows
    return []


def _episode_no(raw: dict[str, Any], fallback: int) -> int:
    try:
        value = int(raw.get("ep") or raw.get("episodeNumber") or raw.get("episode_no") or raw.get("episode") or fallback)
    except Exception:
        value = fallback
    return max(1, value)


def normalize_episode(raw: dict[str, Any], index: int) -> dict[str, Any]:
    ep_no = _episode_no(raw, index)
    return {
        "episode_no": ep_no,
        "title": _first_text(raw, ("title", "episode_title", "name"), limit=120),
        "summary": _first_text(raw, ("summary", "episode_outline", "main_event", "event", "plot", "beat"), limit=1000),
        "conflict": _first_text(raw, ("conflict", "main_conflict", "episode_conflict"), limit=700),
        "turning": _first_text(raw, ("turning", "turning_point", "burst", "explosion"), limit=700),
        "hook": _first_text(raw, ("hook", "cliffhanger", "next_hook", "ending_hook"), limit=700),
        "main_scene": _first_text(raw, ("main_scene", "mainScene", "scene", "location"), limit=300),
        "relationship_change": _first_text(raw, ("relationship_change", "relationship_delta"), limit=700),
        "info_revealed": _first_text(raw, ("info_revealed", "information_delta"), limit=700),
        "satisfaction_type": _first_text(raw, ("satisfaction_type", "emotional_payoff"), limit=200),
        "stage": _first_text(raw, ("stage", "episode_range", "function"), limit=200),
        "start_state": _first_text(raw, ("start_state", "opening_state", "incoming_hook"), limit=700),
        "end_state": _first_text(raw, ("end_state", "ending_state", "outgoing_state"), limit=700),
        "existing_script": _first_text(raw, ("existing_script", "script_text", "script"), limit=20000),
    }


def normalize_character(raw: dict[str, Any], index: int) -> dict[str, Any]:
    info = _first_text(raw, ("info", "background", "bio", "profile", "notes"), limit=2000)
    bio = _as_dict(raw.get("bio"))
    merged = {**bio, **raw}
    return {
        "id": _text(raw.get("id")) or f"char-{index}",
        "name": _first_text(raw, ("name", "character_name"), limit=80),
        "role": _first_text(raw, ("role", "character_role"), limit=80) or "supporting",
        "identity": _first_text(merged, ("identity", "surface_identity", "occupation", "info", "background", "profile"), limit=700),
        "info": info,
        "occupation": _first_text(raw, ("occupation",), limit=160),
        "appearance": _first_text(raw, ("appearance", "visual_signature"), limit=300),
        "motivation": _first_text(raw, ("motivation", "goal", "external_goal"), limit=500),
        "relationship_to_core_conflict": _first_text(
            merged,
            ("relationship_to_core_conflict", "relationship_tension", "relationship_pressure"),
            limit=700,
        ),
        "secret_or_bottom_card": _first_text(
            merged,
            ("secret_or_bottom_card", "hidden_identity_or_secret", "secret", "hidden_secret"),
            limit=700,
        ),
        "ability_boundary": _first_text(merged, ("ability_boundary", "limit_or_cost", "boundary", "resource"), limit=700),
        "emotional_arc": _first_text(merged, ("emotional_arc", "arc", "character_arc"), limit=700),
        "personality": _first_text(raw, ("personality", "traits"), limit=500),
        "voiceprint": _first_text(merged, ("voiceprint", "voice_style", "voiceStyle"), limit=500),
        "inner_need": _first_text(merged, ("inner_need", "innerNeed"), limit=500),
        "resource": _first_text(merged, ("resource",), limit=500),
        "first_appearance_function": _first_text(
            merged,
            ("first_appearance_function", "first_scene_function", "firstSceneFunction"),
            limit=500,
        ),
        "relationship_tension": _first_text(
            merged,
            ("relationship_tension", "relationship_pressure"),
            limit=500,
        ),
        "relationships": raw.get("relationships") if isinstance(raw.get("relationships"), list) else [],
        "source_rule": "explicit_character_array_only_no_prose_guessing",
    }


def normalize_relationship(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": _first_text(raw, ("source", "from", "from_character", "source_name"), limit=80),
        "target": _first_text(raw, ("target", "to", "to_character", "target_name"), limit=80),
        "type": _first_text(raw, ("type", "relationship_type"), limit=120),
        "description": _first_text(raw, ("description", "desc", "note", "relationship"), limit=700),
        "strength": _text(raw.get("strength"), limit=80),
    }


def attach_relationship_table(
    characters: list[dict[str, Any]],
    relationship_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = [
        item
        for item in (normalize_relationship(row) for row in relationship_rows)
        if item["source"] and item["target"]
    ]
    if not normalized:
        return characters
    by_name = {character.get("name"): character for character in characters if character.get("name")}
    for character in characters:
        name = character.get("name")
        if not name:
            continue
        existing = character.get("relationships") if isinstance(character.get("relationships"), list) else []
        merged = list(existing)
        seen = {
            (
                _text(item.get("source")),
                _text(item.get("target")),
                _text(item.get("type")),
                _text(item.get("description")),
            )
            for item in merged
            if isinstance(item, dict)
        }
        for relation in normalized:
            if relation["source"] != name and relation["target"] != name:
                continue
            entry = dict(relation)
            entry["direction"] = "outgoing" if relation["source"] == name else "incoming"
            key = (entry["source"], entry["target"], entry["type"], entry["description"])
            if key not in seen:
                merged.append(entry)
                seen.add(key)
        character["relationships"] = merged
    return list(by_name.values()) if len(by_name) == len(characters) else characters


def resolve_series_fields(snapshot: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    data = outline_data(snapshot)
    selling = selling_points(snapshot)
    project = _as_dict(snapshot.get("project"))
    rules = _as_dict(snapshot.get("project_rules") or snapshot.get("projectRules"))
    genre = _as_dict(snapshot.get("genre"))
    title = args.title or _text(project.get("name")) or _text(snapshot.get("title")) or "pending_longform_project"
    genre_text = (
        args.genre
        or _text(data.get("genre_main"))
        or _text(data.get("genre"))
        or _text(genre.get("category"))
        or "pending"
    )
    target = args.episode_count or rules.get("total_episodes") or data.get("episode_count") or data.get("episodeCount")
    try:
        episode_count = int(target)
    except Exception:
        episode_count = 0
    if episode_count <= 0:
        episode_count = len(explicit_episodes(snapshot)) or 30
    episode_count = min(60, max(30, episode_count))
    return {
        "title": title,
        "genre": genre_text,
        "episode_count": episode_count,
        "audience": _text(data.get("audience_axis") or data.get("target") or selling.get("target")),
        "logline": _text(data.get("logline") or selling.get("logline"), limit=1000),
        "worldview": _text(data.get("worldview") or selling.get("worldview"), limit=1200),
        "golden_finger": _text(data.get("goldenFinger") or data.get("golden_finger") or selling.get("uniqueness"), limit=1200),
        "conflict": _text(data.get("conflict") or selling.get("conflict"), limit=1200),
    }


def write_imported_existing_script(workdir: Path, episode: dict[str, Any]) -> str:
    script = episode.get("existing_script") or ""
    if not script:
        return ""
    path = workdir / "scripts" / f"ep{int(episode['episode_no']):03d}_imported_existing_script.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script + "\n", encoding="utf-8")
    return path.relative_to(workdir).as_posix()


def build_trial_rows(
    experiment_id: str,
    created_at: str,
    episode_count: int,
    episodes: list[dict[str, Any]],
    workdir: Path,
) -> list[dict[str, Any]]:
    by_no = {int(ep["episode_no"]): ep for ep in episodes if int(ep["episode_no"]) >= 1}
    rows: list[dict[str, Any]] = []
    for episode_no in range(1, episode_count + 1):
        ep = by_no.get(episode_no)
        if not ep:
            rows.append(prepare.build_trials(experiment_id, 1, created_at)[0] | {"episode_no": episode_no, "episode_range": prepare.episode_range_label(episode_no)})
            continue
        script_path = write_imported_existing_script(workdir, ep)
        rows.append(
            {
                "experiment_id": experiment_id,
                "created_at": created_at,
                "episode_no": episode_no,
                "episode_range": prepare.episode_range_label(episode_no),
                "episode_title": ep["title"] or PENDING,
                "episode_function": ep["stage"] or ep["satisfaction_type"] or PENDING,
                "start_state": ep["start_state"] or PENDING,
                "episode_event": ep["summary"] or PENDING,
                "end_state": ep["end_state"] or PENDING,
                "next_hook": ep["hook"] or ep["turning"] or PENDING,
                "character_state_delta": ep["relationship_change"] or PENDING,
                "plot_state_delta": ep["info_revealed"] or PENDING,
                "visual_signature": ep["main_scene"] or PENDING,
                "visual_repeat_risk": "not_checked",
                "role_gate": "not_checked",
                "continuity_gate": "not_checked",
                "visual_gate": "not_checked",
                "hard_reject_gate": "not_checked",
                "script_text_path": script_path,
                "model_scorer": "",
                "model_score_candidate": "",
                "model_score_candidate_status": "not_scored",
                "human_score": "",
                "human_review_status": "not_reviewed",
                "industrial_pass": "",
                "industrial_pass_basis": "",
                "failure_gate": "",
                "failure_reason": "",
                "status": "outline_card_imported_script_pending",
                "notes": "imported from explicit outline state; gates and script generation still pending",
            }
        )
    return rows


def build_bibles(
    series: dict[str, Any],
    characters: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    relationship_table: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    episode_cards = [
        {
            key: ep.get(key, "")
            for key in (
                "episode_no",
                "title",
                "summary",
                "conflict",
                "turning",
                "hook",
                "main_scene",
                "relationship_change",
                "info_revealed",
                "satisfaction_type",
                "stage",
            )
        }
        for ep in episodes
    ]
    locations = sorted({ep["main_scene"] for ep in episodes if ep.get("main_scene")})
    return {
        "series_bible": {
            "artifact": "series_bible",
            "created_at": created_at,
            "status": "imported_from_explicit_outline_state",
            "title": series["title"],
            "genre": series["genre"],
            "episode_count_target": series["episode_count"],
            "audience": series["audience"] or PENDING,
            "core_hook": series["logline"] or PENDING,
            "worldview": series["worldview"] or PENDING,
            "golden_finger": series["golden_finger"] or PENDING,
            "core_conflict": series["conflict"] or PENDING,
            "source_boundary": [
                "Imported only from explicit outline/project fields.",
                "No missing story content was invented by this bridge.",
            ],
        },
        "character_bible": {
            "artifact": "character_bible",
            "created_at": created_at,
            "status": "imported_from_explicit_character_records" if characters else "schema_ready_no_explicit_characters",
            "characters": characters,
            "relationship_table": relationship_table,
            "consistency_rule": "No character may be created from dialogue or action prose without an explicit character record.",
        },
        "plot_bible": {
            "artifact": "plot_bible",
            "created_at": created_at,
            "status": "imported_from_explicit_episode_cards" if episodes else "schema_ready_content_pending",
            "episode_count_target": series["episode_count"],
            "episodes": episode_cards,
            "paid_wall_candidates": [],
            "climax_candidates": [],
        },
        "visual_bible": {
            "artifact": "visual_bible",
            "created_at": created_at,
            "status": "imported_from_explicit_episode_cards" if locations else "schema_ready_content_pending",
            "locations": locations,
            "visual_signatures": [
                {"episode_no": ep["episode_no"], "main_scene": ep["main_scene"]}
                for ep in episodes
                if ep.get("main_scene")
            ],
            "repeat_rules": [
                "Do not reuse the same location-action-emotion combination in adjacent episodes.",
                "Every repeated location needs a new action, prop, or power relation.",
                "This bridge only imports source scenes; visual repeat risk still requires gate checking.",
            ],
        },
    }


def import_outline_state(snapshot: dict[str, Any], args: argparse.Namespace, source_path: str = "") -> Path:
    created_at = now_iso()
    series = resolve_series_fields(snapshot, args)
    workspace_args = SimpleNamespace(
        experiment_id=args.experiment_id,
        title=series["title"],
        genre=series["genre"],
        episode_count=series["episode_count"],
        overwrite=args.overwrite,
    )
    workdir = prepare.write_workspace(workspace_args)
    characters = [
        item
        for item in (normalize_character(raw, index + 1) for index, raw in enumerate(explicit_characters(snapshot)))
        if item["name"]
    ]
    relationship_table = [
        item
        for item in (normalize_relationship(raw) for raw in explicit_relationship_table(snapshot))
        if item["source"] and item["target"]
    ]
    characters = attach_relationship_table(characters, relationship_table)
    episodes = [
        item
        for item in (normalize_episode(raw, index + 1) for index, raw in enumerate(explicit_episodes(snapshot)))
        if 1 <= int(item["episode_no"]) <= series["episode_count"]
    ]
    bibles = build_bibles(series, characters, episodes, relationship_table, created_at)
    for name, payload in bibles.items():
        atomic_json_dump(payload, workdir / "bibles" / f"{name}.json")
    prepare.write_csv(
        workdir / "trials.csv",
        prepare.TRIAL_FIELDS,
        build_trial_rows(args.experiment_id, created_at, series["episode_count"], episodes, workdir),
    )
    prepare.write_csv(workdir / "seed_ledger.csv", prepare.SEED_FIELDS, [])
    summary = {
        "artifact": "outline_state_import_summary",
        "created_at": created_at,
        "source_path": source_path,
        "experiment_id": args.experiment_id,
        "episode_count_target": series["episode_count"],
        "explicit_character_count": len(characters),
        "explicit_relationship_count": len(relationship_table),
        "explicit_episode_count": len(episodes),
        "existing_script_count": sum(1 for ep in episodes if ep.get("existing_script")),
        "main_chain_committed": outline_state(snapshot).get("main_chain_committed"),
        "scientific_boundary": "Imported source evidence only; no generation, no human_score, no industrial_pass.",
    }
    atomic_json_dump(summary, workdir / "source_snapshot_summary.json")
    (workdir / "ledger.md").write_text(
        "\n".join(
            [
                f"# {args.experiment_id} Ledger",
                "",
                "- Status: imported_outline_state_no_generation",
                f"- Source: {source_path or 'in-memory snapshot'}",
                f"- Explicit characters: {len(characters)}",
                f"- Explicit episode cards: {len(episodes)}/{series['episode_count']}",
                "- Current stage: P1/P2 source import complete; gates and script generation pending.",
                "- Boundary: no human_score, no industrial_pass, no launch claim.",
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
                "- Artifact: longform_outline_state_bridge_workspace",
                f"- Created at: {created_at}",
                "- Verification Status: IMPORTED_NOT_GENERATED",
                "- Scope: explicit outline state to longform industrial ledger.",
                "",
                "## Boundary",
                "",
                "- This import copied explicit source fields only.",
                "- It did not infer characters from prose.",
                "- It did not generate missing episode scripts.",
                "- It did not produce human scores or industrial pass decisions.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return workdir


def main() -> int:
    parser = argparse.ArgumentParser(description="Import explicit outline state into a longform industrial workspace.")
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID)
    parser.add_argument("--title", default="")
    parser.add_argument("--genre", default="")
    parser.add_argument("--episode-count", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    snapshot = load_snapshot(args.source_json)
    workdir = import_outline_state(snapshot, args, source_path=str(args.source_json.expanduser()))
    print(json.dumps({"event": "imported_outline_state", "workdir": str(workdir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
