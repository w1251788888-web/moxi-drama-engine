#!/usr/bin/env python3
"""Rebuild legacy SQLite tables to remove incorrect foreign-key constraints."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FkRemovalSpec = tuple[tuple[str, ...], str]


FK_REMOVALS: dict[str, tuple[FkRemovalSpec, ...]] = {
    "project_materials": (
        (("source_segment_id",), "episode_segments"),
        (("session_id",), "task"),
        (("project_id",), "task"),
    ),
    "user_edit_records": (
        (("session_id",), "task"),
        (("project_id",), "task"),
    ),
    "rule_extraction_jobs": (
        (("project_id",), "task"),
    ),
    "workflow_efficiency_metrics": (
        (("project_id",), "task"),
    ),
    "learning_insights": (
        (("project_id",), "task"),
    ),
    "issue_record": (
        (("task_id",), "task"),
    ),
}


def get_default_database_path() -> Path:
    from app.config import config

    path = Path(config.database_path)
    return path if path.is_absolute() else (ROOT / path).resolve()


def migrate_fk_constraints(
    db_path: str | Path | None = None,
    *,
    apply: bool = False,
    backup_path: str | Path | None = None,
    allow_no_backup: bool = False,
) -> dict[str, Any]:
    path = Path(db_path) if db_path is not None else get_default_database_path()
    path = path.resolve()
    report: dict[str, Any] = {
        "status": "ok",
        "database_path": str(path),
        "apply": apply,
        "backup_path": str(Path(backup_path).resolve()) if backup_path else "",
        "tables": [],
        "warnings": [],
        "errors": [],
    }
    if not path.exists():
        report["status"] = "error"
        report["errors"].append(f"database not found: {path}")
        return report
    if apply and not allow_no_backup:
        if not backup_path:
            report["status"] = "error"
            report["errors"].append("--backup-path is required when applying this migration")
            return report
        if not Path(backup_path).exists():
            report["status"] = "error"
            report["errors"].append(f"backup not found: {backup_path}")
            return report

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        table_plans = [_build_table_plan(conn, table, removals) for table, removals in FK_REMOVALS.items()]
        table_plans = [plan for plan in table_plans if plan["table_exists"] and plan["removed_fk_ids"]]
        report["tables"] = table_plans
        if not table_plans:
            return report
        if not apply:
            report["status"] = "planned"
            return report

        _apply_rebuild(conn, table_plans)
        remaining = conn.execute("PRAGMA foreign_key_check").fetchall()
        report["post_migration_foreign_key_violation_count"] = len(remaining)
        if remaining:
            report["status"] = "warning"
            report["warnings"].append(f"foreign key violations remain: {len(remaining)}")
            report["remaining_foreign_key_violations_sample"] = [dict(row) for row in remaining[:10]]
        return report
    except sqlite3.DatabaseError as exc:
        report["status"] = "error"
        report["errors"].append(str(exc))
        return report
    finally:
        conn.close()


def _build_table_plan(conn: sqlite3.Connection, table: str, removals: tuple[FkRemovalSpec, ...]) -> dict[str, Any]:
    existing_tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if table not in existing_tables:
        return {
            "table": table,
            "table_exists": False,
            "removed_fk_ids": [],
            "kept_fk_ids": [],
            "row_count": 0,
        }

    fk_rows = conn.execute(f"PRAGMA foreign_key_list({_quote_identifier(table)})").fetchall()
    fk_ids = {int(row["id"]) for row in fk_rows}
    removal_specs = set(removals)
    removed = sorted(
        fk_id
        for fk_id, rows in _group_foreign_keys(fk_rows).items()
        if _foreign_key_signature(rows) in removal_specs
    )
    kept = sorted(fk_ids - set(removed))
    row_count = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
    return {
        "table": table,
        "table_exists": True,
        "removed_fk_ids": removed,
        "kept_fk_ids": kept,
        "row_count": int(row_count),
        "removed_foreign_keys": _describe_foreign_keys(fk_rows, removed),
        "kept_foreign_keys": _describe_foreign_keys(fk_rows, kept),
    }


def _apply_rebuild(conn: sqlite3.Connection, plans: list[dict[str, Any]]) -> None:
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for plan in plans:
            _rebuild_table(conn, plan["table"], kept_fk_ids=set(plan["kept_fk_ids"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _rebuild_table(conn: sqlite3.Connection, table: str, *, kept_fk_ids: set[int]) -> None:
    temp_table = f"__moxi_rebuild_{table}"
    conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(temp_table)}")
    columns = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    if not columns:
        raise sqlite3.DatabaseError(f"table has no columns: {table}")

    foreign_keys = conn.execute(f"PRAGMA foreign_key_list({_quote_identifier(table)})").fetchall()
    create_sql = _build_create_table_sql(temp_table, columns, foreign_keys, kept_fk_ids)
    index_sql = [
        row["sql"]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL ORDER BY name",
            (table,),
        ).fetchall()
        if row["sql"]
    ]
    column_names = [row["name"] for row in columns]
    quoted_columns = ", ".join(_quote_identifier(name) for name in column_names)

    conn.execute(create_sql)
    conn.execute(
        f"INSERT INTO {_quote_identifier(temp_table)} ({quoted_columns}) "
        f"SELECT {quoted_columns} FROM {_quote_identifier(table)}"
    )
    conn.execute(f"DROP TABLE {_quote_identifier(table)}")
    conn.execute(f"ALTER TABLE {_quote_identifier(temp_table)} RENAME TO {_quote_identifier(table)}")
    for statement in index_sql:
        conn.execute(statement)


def _build_create_table_sql(
    table: str,
    columns: list[sqlite3.Row],
    foreign_keys: list[sqlite3.Row],
    kept_fk_ids: set[int],
) -> str:
    definitions = [_column_definition(row) for row in columns]
    definitions.extend(_foreign_key_definitions(foreign_keys, kept_fk_ids))
    return f"CREATE TABLE {_quote_identifier(table)} (\n  " + ",\n  ".join(definitions) + "\n)"


def _column_definition(row: sqlite3.Row) -> str:
    parts = [_quote_identifier(str(row["name"])), str(row["type"] or "TEXT")]
    if int(row["pk"] or 0) == 1:
        parts.append("PRIMARY KEY")
    if int(row["notnull"] or 0) and not int(row["pk"] or 0):
        parts.append("NOT NULL")
    if row["dflt_value"] is not None:
        parts.append(f"DEFAULT {row['dflt_value']}")
    return " ".join(parts)


def _foreign_key_definitions(foreign_keys: list[sqlite3.Row], kept_fk_ids: set[int]) -> list[str]:
    by_id = {
        fk_id: rows
        for fk_id, rows in _group_foreign_keys(foreign_keys).items()
        if fk_id in kept_fk_ids
    }

    definitions: list[str] = []
    for fk_id in sorted(by_id):
        rows = sorted(by_id[fk_id], key=lambda item: int(item["seq"]))
        first = rows[0]
        child_columns = ", ".join(_quote_identifier(str(row["from"])) for row in rows)
        parent_columns = ", ".join(_quote_identifier(str(row["to"] or "")) for row in rows)
        statement = (
            f"FOREIGN KEY ({child_columns}) "
            f"REFERENCES {_quote_identifier(str(first['table']))} ({parent_columns})"
        )
        if str(first["on_update"]).upper() != "NO ACTION":
            statement += f" ON UPDATE {first['on_update']}"
        if str(first["on_delete"]).upper() != "NO ACTION":
            statement += f" ON DELETE {first['on_delete']}"
        definitions.append(statement)
    return definitions


def _describe_foreign_keys(rows: list[sqlite3.Row], ids: list[int]) -> list[dict[str, Any]]:
    by_id = {
        fk_id: grouped_rows
        for fk_id, grouped_rows in _group_foreign_keys(rows).items()
        if fk_id in ids
    }
    descriptions: list[dict[str, Any]] = []
    for fk_id in ids:
        items = sorted(by_id.get(fk_id, []), key=lambda item: int(item["seq"]))
        if not items:
            continue
        first = items[0]
        descriptions.append({
            "fk_id": fk_id,
            "parent_table": first["table"],
            "child_columns": [row["from"] for row in items],
            "parent_columns": [row["to"] for row in items],
        })
    return descriptions


def _group_foreign_keys(rows: list[sqlite3.Row]) -> dict[int, list[sqlite3.Row]]:
    by_id: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_id[int(row["id"])].append(row)
    return by_id


def _foreign_key_signature(rows: list[sqlite3.Row]) -> FkRemovalSpec:
    ordered = sorted(rows, key=lambda item: int(item["seq"]))
    first = ordered[0]
    return (tuple(str(row["from"]) for row in ordered), str(first["table"]))


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove known incorrect SQLite FK constraints by table rebuild.")
    parser.add_argument("--db-path", default="", help="SQLite database path. Defaults to config.database.path.")
    parser.add_argument("--apply", action="store_true", help="Apply the migration. Default is dry-run plan.")
    parser.add_argument("--backup-path", default="", help="Required for --apply unless --allow-no-backup is used.")
    parser.add_argument("--allow-no-backup", action="store_true", help="Allow --apply without backup path, intended for tests only.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    report = migrate_fk_constraints(
        args.db_path or None,
        apply=args.apply,
        backup_path=args.backup_path or None,
        allow_no_backup=args.allow_no_backup,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["status"] == "error":
        return 2
    if report["status"] == "warning":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
