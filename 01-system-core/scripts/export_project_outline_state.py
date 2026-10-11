# -*- coding: utf-8 -*-
"""Export explicit project outline state from SQLite project databases.

This script is read-only. It helps connect the real product database to the
longform industrial workspace without inventing missing story material.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from scoring_common import ROOT, atomic_json_dump, now_iso


DEFAULT_TENANT_ROOT = ROOT / "data" / "tenant-dbs"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "longform_industrial" / "source_exports"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def discover_databases(root: Path) -> list[Path]:
    root = root.expanduser()
    if root.is_file():
        return [root]
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*/tenant.db") if path.is_file())


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select name from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _project_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    if not table_exists(conn, "project_v2"):
        return []
    rows = conn.execute(
        """
        select
          id, name, description, config, project_type, audience_axis,
          genre_main, genre_sub, total_episodes, completed_episodes,
          current_episode, status, created_at, updated_at, created_by
        from project_v2
        order by datetime(coalesce(updated_at, created_at, '1970-01-01')) desc
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _outline_state_from_config(config: dict[str, Any]) -> dict[str, Any]:
    workflow = config.get("workflow_context") if isinstance(config.get("workflow_context"), dict) else {}
    outline_state = workflow.get("outline_state") if isinstance(workflow.get("outline_state"), dict) else {}
    if outline_state:
        return outline_state
    direct = config.get("outline_state") if isinstance(config.get("outline_state"), dict) else {}
    return direct


def _outline_data_from_config(config: dict[str, Any], outline_state: dict[str, Any]) -> dict[str, Any]:
    for value in (
        outline_state.get("outline_data"),
        config.get("outline_data"),
        config.get("outlineData"),
        config.get("outline"),
    ):
        if isinstance(value, dict):
            return value
    return {}


def _outline_characters_from_config(config: dict[str, Any], outline_state: dict[str, Any]) -> list[dict[str, Any]]:
    for value in (
        outline_state.get("outline_characters"),
        outline_state.get("outlineCharacters"),
        config.get("outline_characters"),
        config.get("outlineCharacters"),
        config.get("characters"),
    ):
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _episode_count(outline_data: dict[str, Any]) -> int:
    episodes = outline_data.get("episodes")
    return len(episodes) if isinstance(episodes, list) else 0


def project_candidate(db_path: Path, row: dict[str, Any]) -> dict[str, Any]:
    config = _safe_json(row.get("config"))
    outline_state = _outline_state_from_config(config)
    outline_data = _outline_data_from_config(config, outline_state)
    outline_characters = _outline_characters_from_config(config, outline_state)
    workflow = config.get("workflow_context") if isinstance(config.get("workflow_context"), dict) else {}
    return {
        "db_path": str(db_path),
        "project_id": _text(row.get("id")),
        "name": _text(row.get("name")),
        "status": _text(row.get("status")),
        "updated_at": _text(row.get("updated_at")),
        "total_episodes": row.get("total_episodes") or 0,
        "main_chain_committed": bool(outline_state.get("main_chain_committed")),
        "main_chain_dirty": bool(outline_state.get("main_chain_dirty")),
        "outline_episode_count": _episode_count(outline_data),
        "outline_character_count": len(outline_characters),
        "has_workflow_context": bool(workflow),
        "has_outline_state": bool(outline_state),
        "has_exportable_outline": bool(outline_data or outline_characters),
    }


def scan_projects(db_paths: list[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception:
            continue
        try:
            for row in _project_rows(conn):
                candidates.append(project_candidate(db_path, row))
        finally:
            conn.close()
    return candidates


def _load_project_row(db_path: Path, project_id: str = "") -> dict[str, Any] | None:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = _project_rows(conn)
    finally:
        conn.close()
    if project_id:
        return next((row for row in rows if _text(row.get("id")) == project_id), None)
    return rows[0] if rows else None


def choose_project(candidates: list[dict[str, Any]], project_id: str = "") -> dict[str, Any] | None:
    if project_id:
        return next((item for item in candidates if item["project_id"] == project_id), None)
    committed = [
        item for item in candidates
        if item["main_chain_committed"] and not item["main_chain_dirty"] and item["has_exportable_outline"]
    ]
    if committed:
        return committed[0]
    exportable = [item for item in candidates if item["has_exportable_outline"]]
    if exportable:
        return exportable[0]
    return candidates[0] if candidates else None


def build_export_payload(db_path: Path, row: dict[str, Any]) -> dict[str, Any]:
    config = _safe_json(row.get("config"))
    outline_state = _outline_state_from_config(config)
    outline_data = _outline_data_from_config(config, outline_state)
    outline_characters = _outline_characters_from_config(config, outline_state)
    workflow = config.get("workflow_context") if isinstance(config.get("workflow_context"), dict) else {}
    project = {
        "id": _text(row.get("id")),
        "name": _text(row.get("name")),
        "description": _text(row.get("description")),
        "project_type": _text(row.get("project_type")),
        "audience_axis": _text(row.get("audience_axis")),
        "genre_main": _text(row.get("genre_main")),
        "genre_sub": _text(row.get("genre_sub")),
        "total_episodes": row.get("total_episodes") or 0,
        "completed_episodes": row.get("completed_episodes") or 0,
        "current_episode": row.get("current_episode") or 0,
        "status": _text(row.get("status")),
        "updated_at": _text(row.get("updated_at")),
    }
    return {
        "artifact": "project_outline_state_export",
        "created_at": now_iso(),
        "source_db": str(db_path),
        "project": project,
        "project_rules": {
            "total_episodes": row.get("total_episodes") or outline_data.get("episode_count") or len(outline_data.get("episodes") or []),
            "audience_axis": row.get("audience_axis") or outline_data.get("audience_axis") or "",
            "genre_main": row.get("genre_main") or outline_data.get("genre_main") or "",
            "genre_sub": row.get("genre_sub") or "",
        },
        "workflow_context": workflow,
        "outline_state": outline_state,
        "outline_data": outline_data,
        "outline_characters": outline_characters,
        "scientific_boundary": [
            "This export is a database snapshot only.",
            "It does not generate missing story material.",
            "It does not produce human_score or industrial_pass.",
        ],
    }


def export_project(args: argparse.Namespace) -> dict[str, Any]:
    db_paths = [args.db.expanduser()] if args.db else discover_databases(args.tenant_root)
    candidates = scan_projects(db_paths)
    output_dir = args.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "artifact": "project_outline_state_scan_manifest",
        "created_at": now_iso(),
        "db_count": len(db_paths),
        "project_count": len(candidates),
        "candidates": candidates,
    }
    atomic_json_dump(manifest, output_dir / "project_outline_state_scan_manifest.json")
    chosen = choose_project(candidates, args.project_id)
    if not chosen:
        return {
            "event": "no_project_found",
            "db_count": len(db_paths),
            "project_count": 0,
            "manifest": str(output_dir / "project_outline_state_scan_manifest.json"),
        }
    row = _load_project_row(Path(chosen["db_path"]), chosen["project_id"])
    if not row:
        return {
            "event": "project_row_not_found",
            "project_id": chosen["project_id"],
            "manifest": str(output_dir / "project_outline_state_scan_manifest.json"),
        }
    payload = build_export_payload(Path(chosen["db_path"]), row)
    output_path = args.output or output_dir / f"outline_state_{chosen['project_id']}.json"
    atomic_json_dump(payload, output_path)
    return {
        "event": "exported_project_outline_state",
        "project_id": chosen["project_id"],
        "name": chosen["name"],
        "output": str(output_path),
        "manifest": str(output_dir / "project_outline_state_scan_manifest.json"),
        "main_chain_committed": chosen["main_chain_committed"],
        "outline_episode_count": chosen["outline_episode_count"],
        "outline_character_count": chosen["outline_character_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export project outline state from product SQLite databases.")
    parser.add_argument("--tenant-root", type=Path, default=DEFAULT_TENANT_ROOT)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = export_project(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
