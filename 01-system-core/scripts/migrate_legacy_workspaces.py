#!/usr/bin/env python3
"""Migrate legacy project workspaces from 新建项目 to new-projects.

Default mode is dry-run. Use --apply to move directories. Use --update-db to
also rewrite exact project_v2.workspace_path values in a SQLite database.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_LIBRARY_ROOT = REPO_ROOT / "03-project-library"
NEW_ROOT_NAME = "new-projects"
LEGACY_ROOT_NAME = "新建项目"


@dataclass
class MigrationItem:
    name: str
    source: str
    destination: str
    status: str
    reason: str = ""


@dataclass
class MigrationReport:
    dry_run: bool
    project_library_root: str
    legacy_root: str
    new_root: str
    items: list[MigrationItem]
    db_updated: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["items"] = [asdict(item) for item in self.items]
        return data


def _load_index(index_file: Path) -> dict[str, Any]:
    if not index_file.exists():
        return {"projects": []}
    try:
        payload = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return {"projects": []}
    if isinstance(payload, list):
        return {"projects": payload}
    if isinstance(payload, dict):
        projects = payload.get("projects")
        if not isinstance(projects, list):
            payload["projects"] = []
        return payload
    return {"projects": []}


def _write_index(index_file: Path, index: dict[str, Any]) -> None:
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_legacy_index(legacy_root: Path, new_root: Path, moved: list[MigrationItem]) -> None:
    if not moved:
        return

    moved_by_source = {item.source: item.destination for item in moved if item.status == "moved"}
    legacy_index = _load_index(legacy_root / "_index.json")
    new_index = _load_index(new_root / "_index.json")
    retained: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_entry(entry: dict[str, Any]) -> None:
        key = (
            str(entry.get("id") or ""),
            str(entry.get("name") or ""),
            str(entry.get("path") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        retained.append(entry)

    for entry in new_index.get("projects", []):
        if isinstance(entry, dict):
            add_entry(dict(entry))

    for entry in legacy_index.get("projects", []):
        if not isinstance(entry, dict):
            continue
        migrated = dict(entry)
        old_path = str(migrated.get("path") or "")
        if old_path in moved_by_source:
            migrated["path"] = moved_by_source[old_path]
            add_entry(migrated)

    new_index["projects"] = retained
    _write_index(new_root / "_index.json", new_index)


def _update_db_paths(db_path: Path, moved: list[MigrationItem]) -> int:
    if not db_path.exists():
        return 0
    updates = [(item.destination, item.source) for item in moved if item.status == "moved"]
    if not updates:
        return 0

    updated = 0
    with sqlite3.connect(db_path) as conn:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='project_v2'"
        ).fetchone()
        if not table_exists:
            return 0
        for new_path, old_path in updates:
            cursor = conn.execute(
                "UPDATE project_v2 SET workspace_path = ? WHERE workspace_path = ?",
                (new_path, old_path),
            )
            updated += cursor.rowcount
        conn.commit()
    return updated


def migrate_legacy_workspaces(
    *,
    project_library_root: Path = PROJECT_LIBRARY_ROOT,
    apply: bool = False,
    update_db: bool = False,
    db_path: Path | None = None,
) -> MigrationReport:
    project_library_root = Path(project_library_root).expanduser().resolve()
    legacy_root = project_library_root / LEGACY_ROOT_NAME
    new_root = project_library_root / NEW_ROOT_NAME
    items: list[MigrationItem] = []

    if not legacy_root.exists():
        return MigrationReport(
            dry_run=not apply,
            project_library_root=str(project_library_root),
            legacy_root=str(legacy_root),
            new_root=str(new_root),
            items=[],
        )

    for source in sorted(legacy_root.iterdir(), key=lambda item: item.name):
        if source.name.startswith(".") or source.name == "_index.json":
            continue
        destination = new_root / source.name
        if not source.is_dir():
            items.append(MigrationItem(source.name, str(source), str(destination), "skipped", "not_directory"))
            continue
        if destination.exists():
            items.append(MigrationItem(source.name, str(source), str(destination), "skipped", "destination_exists"))
            continue
        status = "moved" if apply else "would_move"
        items.append(MigrationItem(source.name, str(source), str(destination), status))

    if apply:
        new_root.mkdir(parents=True, exist_ok=True)
        moved: list[MigrationItem] = []
        for item in items:
            if item.status != "moved":
                continue
            shutil.move(item.source, item.destination)
            moved.append(item)
        _merge_legacy_index(legacy_root, new_root, moved)
        db_updated = _update_db_paths(db_path, moved) if update_db and db_path else 0
    else:
        db_updated = 0

    return MigrationReport(
        dry_run=not apply,
        project_library_root=str(project_library_root),
        legacy_root=str(legacy_root),
        new_root=str(new_root),
        items=items,
        db_updated=db_updated,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy Moxi workspaces")
    parser.add_argument("--project-library-root", type=Path, default=PROJECT_LIBRARY_ROOT)
    parser.add_argument("--apply", action="store_true", help="Actually move directories")
    parser.add_argument("--update-db", action="store_true", help="Update exact project_v2.workspace_path values")
    parser.add_argument("--db-path", type=Path, default=REPO_ROOT / "01-system-core" / "data" / "tasks.db")
    args = parser.parse_args()

    report = migrate_legacy_workspaces(
        project_library_root=args.project_library_root,
        apply=args.apply,
        update_db=args.update_db,
        db_path=args.db_path,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
