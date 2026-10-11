#!/usr/bin/env python3
"""SQLite runtime diagnostics for the active Moxi database."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CORE_EXPECTED_INDEXES: dict[str, list[str]] = {
    "task": [
        "ix_task_status_created",
        "ix_task_status_updated",
        "ix_task_type_created",
    ],
    "module": [
        "ix_module_task_created",
        "ix_module_task_name",
    ],
    "sub_task": [
        "ix_sub_task_agent_status",
        "ix_sub_task_task_created",
        "ix_sub_task_task_status_created",
        "ix_sub_task_module_created",
        "ix_sub_task_module_status_created",
        "ix_sub_task_agent_status_created",
    ],
    "activity_log": [
        "ix_activity_log_created",
        "ix_activity_log_action_created",
        "ix_activity_log_agent_created",
        "ix_activity_log_sub_task_created",
    ],
    "knowledge_chunks": [
        "idx_knowledge_chunk_source",
        "idx_knowledge_chunk_hash",
        "idx_knowledge_chunk_updated",
    ],
    "skill_registry": [
        "idx_skill_registry_category_status",
        "idx_skill_registry_enabled_status",
        "idx_skill_registry_updated",
    ],
    "skill_binding": [
        "idx_skill_binding_type_key",
        "idx_skill_binding_skill",
        "idx_skill_binding_priority",
    ],
    "skill_invocation": [
        "idx_skill_invocation_skill_created",
        "idx_skill_invocation_status_created",
        "idx_skill_invocation_context",
    ],
    "skill_artifact": [
        "idx_skill_artifact_invocation",
        "idx_skill_artifact_skill",
    ],
}

TABLE_COUNT_LIMIT = 25


def get_default_database_path() -> Path:
    from app.config import config

    path = Path(config.database_path)
    return path if path.is_absolute() else (ROOT / path).resolve()


def collect_sqlite_diagnostics(
    db_path: str | Path | None = None,
    *,
    apply_runtime_pragmas: bool = True,
    expected_indexes: dict[str, list[str]] | None = None,
    large_table_rows: int = 50_000,
) -> dict[str, Any]:
    """Collect a side-effect-light diagnostic snapshot for a SQLite database."""
    path = Path(db_path) if db_path is not None else get_default_database_path()
    path = path.resolve()
    report: dict[str, Any] = {
        "status": "ok",
        "database_path": str(path),
        "database_exists": path.exists(),
        "database_size_bytes": path.stat().st_size if path.exists() else 0,
        "wal_size_bytes": _file_size(path.with_name(f"{path.name}-wal")),
        "shm_size_bytes": _file_size(path.with_name(f"{path.name}-shm")),
        "pragmas": {},
        "schema": {},
        "table_counts": {},
        "index_checks": {},
        "slow_query_candidates": [],
        "warnings": [],
        "errors": [],
    }
    if not path.exists():
        report["status"] = "error"
        report["errors"].append(f"database not found: {path}")
        return report

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if apply_runtime_pragmas:
            from app.database import configure_sqlite_connection

            configure_sqlite_connection(conn, enable_wal=True)

        report["pragmas"] = _collect_pragmas(conn)
        report["schema"] = _collect_schema_summary(conn)
        report["table_counts"] = _collect_table_counts(conn)
        report["index_checks"] = _collect_index_checks(conn, expected_indexes or CORE_EXPECTED_INDEXES)
        report["integrity"] = _collect_integrity(conn)
        _collect_slow_query_candidates(report, large_table_rows=large_table_rows)
        _classify_report(report)
        return report
    finally:
        conn.close()


def format_text_report(report: dict[str, Any]) -> str:
    lines = [
        "SQLite Runtime Diagnostics",
        f"status: {report.get('status')}",
        f"database: {report.get('database_path')}",
        f"size_bytes: {report.get('database_size_bytes')}",
        f"wal_size_bytes: {report.get('wal_size_bytes')}",
    ]
    pragmas = report.get("pragmas") or {}
    if pragmas:
        lines.append("pragmas:")
        for key in ("journal_mode", "synchronous", "busy_timeout", "foreign_keys", "cache_size", "temp_store"):
            lines.append(f"  {key}: {pragmas.get(key)}")

    schema = report.get("schema") or {}
    if schema:
        lines.append("schema:")
        lines.append(f"  tables: {schema.get('table_count')}")
        lines.append(f"  indexes: {schema.get('index_count')}")

    table_counts = report.get("table_counts") or {}
    if table_counts:
        lines.append("top_tables:")
        for item in table_counts.get("top_tables", []):
            lines.append(f"  {item['table']}: {item['rows']}")

    missing_indexes = [
        f"{table}.{index_name}"
        for table, item in (report.get("index_checks") or {}).items()
        for index_name in item.get("missing", [])
    ]
    if missing_indexes:
        lines.append("missing_indexes:")
        lines.extend(f"  {item}" for item in missing_indexes)

    if report.get("warnings"):
        lines.append("warnings:")
        lines.extend(f"  - {item}" for item in report["warnings"])
    if report.get("errors"):
        lines.append("errors:")
        lines.extend(f"  - {item}" for item in report["errors"])
    return "\n".join(lines)


def _collect_pragmas(conn: sqlite3.Connection) -> dict[str, Any]:
    keys = [
        "journal_mode",
        "synchronous",
        "busy_timeout",
        "foreign_keys",
        "cache_size",
        "temp_store",
        "page_size",
        "page_count",
        "freelist_count",
    ]
    return {key: conn.execute(f"PRAGMA {key}").fetchone()[0] for key in keys}


def _collect_schema_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT type, name, tbl_name
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'view', 'trigger')
        ORDER BY type, name
        """
    ).fetchall()
    by_type: dict[str, int] = {}
    for row in rows:
        by_type[row["type"]] = by_type.get(row["type"], 0) + 1
    user_tables = [
        row["name"]
        for row in rows
        if row["type"] == "table" and not str(row["name"]).startswith("sqlite_")
    ]
    return {
        "table_count": by_type.get("table", 0),
        "index_count": by_type.get("index", 0),
        "view_count": by_type.get("view", 0),
        "trigger_count": by_type.get("trigger", 0),
        "user_table_count": len(user_tables),
        "user_tables": user_tables,
    }


def _collect_table_counts(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = _user_tables(conn)
    counts: list[dict[str, Any]] = []
    for table in tables:
        try:
            rows = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            counts.append({"table": table, "rows": None, "error": str(exc)})
            continue
        counts.append({"table": table, "rows": int(rows)})
    counts.sort(key=lambda item: item["rows"] if isinstance(item["rows"], int) else -1, reverse=True)
    return {
        "all_tables": counts,
        "top_tables": counts[:TABLE_COUNT_LIMIT],
    }


def _collect_index_checks(
    conn: sqlite3.Connection,
    expected_indexes: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    existing_tables = set(_user_tables(conn))
    result: dict[str, dict[str, Any]] = {}
    for table, expected in expected_indexes.items():
        if table not in existing_tables:
            result[table] = {
                "table_exists": False,
                "expected": list(expected),
                "present": [],
                "missing": list(expected),
                "extra": [],
            }
            continue
        indexes = [
            row["name"]
            for row in conn.execute(f"PRAGMA index_list({_quote_identifier(table)})").fetchall()
            if row["name"]
        ]
        result[table] = {
            "table_exists": True,
            "expected": list(expected),
            "present": sorted(indexes),
            "missing": [index_name for index_name in expected if index_name not in indexes],
            "extra": sorted(index_name for index_name in indexes if index_name not in expected),
        }
    return result


def _collect_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    return {
        "quick_check": quick_check,
        "foreign_key_violation_count": len(foreign_key_rows),
        "foreign_key_violations_sample": [dict(row) for row in foreign_key_rows[:10]],
    }


def _collect_slow_query_candidates(report: dict[str, Any], *, large_table_rows: int) -> None:
    row_counts = {
        item["table"]: item["rows"]
        for item in (report.get("table_counts") or {}).get("all_tables", [])
        if isinstance(item.get("rows"), int)
    }
    for table, check in (report.get("index_checks") or {}).items():
        rows = row_counts.get(table, 0)
        missing = check.get("missing") or []
        if missing:
            report["slow_query_candidates"].append({
                "table": table,
                "reason": "missing_expected_indexes",
                "rows": rows,
                "missing_indexes": missing,
            })
        elif rows >= large_table_rows:
            report["slow_query_candidates"].append({
                "table": table,
                "reason": "large_table_watch",
                "rows": rows,
                "missing_indexes": [],
            })


def _classify_report(report: dict[str, Any]) -> None:
    pragmas = report.get("pragmas") or {}
    integrity = report.get("integrity") or {}
    warnings = report["warnings"]
    errors = report["errors"]

    if str(pragmas.get("journal_mode", "")).lower() != "wal":
        warnings.append(f"journal_mode is {pragmas.get('journal_mode')}, expected wal")
    if int(pragmas.get("busy_timeout") or 0) < 5000:
        warnings.append(f"busy_timeout is {pragmas.get('busy_timeout')}, expected >= 5000")
    if int(pragmas.get("foreign_keys") or 0) != 1:
        warnings.append("foreign_keys is not enabled")
    if int(pragmas.get("temp_store") or 0) != 2:
        warnings.append(f"temp_store is {pragmas.get('temp_store')}, expected MEMORY(2)")
    if int(pragmas.get("cache_size") or 0) >= 0:
        warnings.append(f"cache_size is {pragmas.get('cache_size')}, expected negative KB value")

    page_count = int(pragmas.get("page_count") or 0)
    freelist_count = int(pragmas.get("freelist_count") or 0)
    if page_count and freelist_count / page_count >= 0.25:
        warnings.append(f"freelist_count ratio is high: {freelist_count}/{page_count}")

    for table, item in (report.get("index_checks") or {}).items():
        if not item.get("table_exists"):
            warnings.append(f"expected table missing: {table}")
        for index_name in item.get("missing", []):
            warnings.append(f"expected index missing: {table}.{index_name}")

    if integrity.get("quick_check") != "ok":
        errors.append(f"quick_check failed: {integrity.get('quick_check')}")
    if int(integrity.get("foreign_key_violation_count") or 0) > 0:
        warnings.append(f"foreign key violations detected: {integrity.get('foreign_key_violation_count')}")

    if errors:
        report["status"] = "error"
    elif warnings:
        report["status"] = "warning"
    else:
        report["status"] = "ok"


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect active SQLite runtime health.")
    parser.add_argument("--db-path", default="", help="SQLite database path. Defaults to config.database.path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit 1 when diagnostics contain warnings.")
    parser.add_argument("--no-apply-runtime-pragmas", action="store_true", help="Do not apply app runtime PRAGMAs before inspection.")
    parser.add_argument("--large-table-rows", type=int, default=50_000, help="Row count threshold for large-table watch items.")
    args = parser.parse_args(argv)

    report = collect_sqlite_diagnostics(
        args.db_path or None,
        apply_runtime_pragmas=not args.no_apply_runtime_pragmas,
        large_table_rows=args.large_table_rows,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_text_report(report))

    if report["status"] == "error":
        return 2
    if args.fail_on_warning and report["status"] == "warning":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
