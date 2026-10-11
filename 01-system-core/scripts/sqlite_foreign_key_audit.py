#!/usr/bin/env python3
"""Read-only SQLite foreign-key violation audit."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def get_default_database_path() -> Path:
    from app.config import config

    path = Path(config.database_path)
    return path if path.is_absolute() else (ROOT / path).resolve()


def collect_foreign_key_audit(
    db_path: str | Path | None = None,
    *,
    sample_limit: int = 5,
) -> dict[str, Any]:
    """Collect a read-only grouping of SQLite foreign-key violations."""
    path = Path(db_path) if db_path is not None else get_default_database_path()
    path = path.resolve()
    report: dict[str, Any] = {
        "status": "ok",
        "database_path": str(path),
        "database_exists": path.exists(),
        "violation_count": 0,
        "group_count": 0,
        "groups": [],
        "summary": {
            "affected_child_tables": [],
            "affected_parent_tables": [],
            "violations_by_child_table": {},
            "violations_by_parent_table": {},
            "top_groups": [],
        },
        "warnings": [],
        "errors": [],
    }
    if not path.exists():
        report["status"] = "error"
        report["errors"].append(f"database not found: {path}")
        return report

    conn = _connect_read_only(path)
    conn.row_factory = sqlite3.Row
    try:
        violations = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        report["violation_count"] = len(violations)
        if not violations:
            return report

        grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for violation in violations:
            child_table = str(violation.get("table") or "")
            parent_table = str(violation.get("parent") or "")
            fk_id = int(violation.get("fkid") or 0)
            grouped[(child_table, parent_table, fk_id)].append(violation)

        fk_metadata_cache: dict[str, dict[int, dict[str, Any]]] = {}
        groups: list[dict[str, Any]] = []
        for (child_table, parent_table, fk_id), items in sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]), item[0][0], item[0][1], item[0][2]),
        ):
            if child_table not in fk_metadata_cache:
                fk_metadata_cache[child_table] = _foreign_key_metadata(conn, child_table)
            metadata = fk_metadata_cache[child_table].get(fk_id, {})
            child_columns = metadata.get("child_columns") or []
            rowids = [item.get("rowid") for item in items[:sample_limit]]
            groups.append({
                "child_table": child_table,
                "parent_table": parent_table,
                "fk_id": fk_id,
                "violation_count": len(items),
                "child_columns": child_columns,
                "parent_columns": metadata.get("parent_columns") or [],
                "on_delete": metadata.get("on_delete", ""),
                "on_update": metadata.get("on_update", ""),
                "sample_rowids": rowids,
                "sample_child_values": _sample_child_values(
                    conn,
                    child_table=child_table,
                    rowids=rowids,
                    child_columns=child_columns,
                ),
                "recommended_next_step": "review_relink_archive_or_delete_after_backup",
            })

        report["groups"] = groups
        report["group_count"] = len(groups)
        _populate_summary(report)
        report["warnings"].append(f"foreign key violations detected: {len(violations)}")
        report["status"] = "warning"
        return report
    except sqlite3.DatabaseError as exc:
        report["status"] = "error"
        report["errors"].append(str(exc))
        return report
    finally:
        conn.close()


def format_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# SQLite Foreign Key Audit",
        "",
        f"- status: `{report.get('status')}`",
        f"- database: `{report.get('database_path')}`",
        f"- violations: `{report.get('violation_count')}`",
        f"- groups: `{report.get('group_count')}`",
    ]
    summary = report.get("summary") or {}
    child_counts = summary.get("violations_by_child_table") or {}
    if child_counts:
        lines.extend(["", "## Violations By Child Table", ""])
        for table, count in child_counts.items():
            lines.append(f"- `{table}`: `{count}`")

    groups = report.get("groups") or []
    if groups:
        lines.extend(["", "## Groups", ""])
        lines.append("| child_table | parent_table | fk_id | count | child_columns | sample_rowids |")
        lines.append("|---|---|---:|---:|---|---|")
        for group in groups:
            child_columns = ", ".join(group.get("child_columns") or [])
            sample_rowids = ", ".join(str(item) for item in (group.get("sample_rowids") or []))
            lines.append(
                "| "
                f"`{group.get('child_table')}` | "
                f"`{group.get('parent_table')}` | "
                f"{group.get('fk_id')} | "
                f"{group.get('violation_count')} | "
                f"`{child_columns}` | "
                f"`{sample_rowids}` |"
            )

    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in report["warnings"])
    if report.get("errors"):
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {item}" for item in report["errors"])
    return "\n".join(lines)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _foreign_key_metadata(conn: sqlite3.Connection, table: str) -> dict[int, dict[str, Any]]:
    metadata: dict[int, dict[str, Any]] = {}
    try:
        rows = conn.execute(f"PRAGMA foreign_key_list({_quote_identifier(table)})").fetchall()
    except sqlite3.DatabaseError:
        return metadata
    by_id: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_id[int(row["id"])].append(row)
    for fk_id, items in by_id.items():
        ordered = sorted(items, key=lambda row: int(row["seq"]))
        first = ordered[0]
        metadata[fk_id] = {
            "parent_table": first["table"],
            "child_columns": [str(row["from"]) for row in ordered],
            "parent_columns": [str(row["to"] or "") for row in ordered],
            "on_update": first["on_update"],
            "on_delete": first["on_delete"],
            "match": first["match"],
        }
    return metadata


def _sample_child_values(
    conn: sqlite3.Connection,
    *,
    child_table: str,
    rowids: list[Any],
    child_columns: list[str],
) -> list[dict[str, Any]]:
    if not child_columns:
        return []
    columns = [_quote_identifier(column) for column in child_columns]
    sql = (
        f"SELECT rowid AS _rowid, {', '.join(columns)} "
        f"FROM {_quote_identifier(child_table)} "
        "WHERE rowid = ?"
    )
    samples: list[dict[str, Any]] = []
    for rowid in rowids:
        if rowid is None:
            continue
        try:
            row = conn.execute(sql, (rowid,)).fetchone()
        except sqlite3.DatabaseError as exc:
            samples.append({"rowid": rowid, "error": str(exc)})
            continue
        if row is None:
            samples.append({"rowid": rowid, "missing_child_row": True})
            continue
        samples.append({
            "rowid": row["_rowid"],
            "child_values": {column: row[column] for column in child_columns},
        })
    return samples


def _populate_summary(report: dict[str, Any]) -> None:
    groups = report.get("groups") or []
    by_child = Counter()
    by_parent = Counter()
    for group in groups:
        by_child[group["child_table"]] += int(group["violation_count"])
        by_parent[group["parent_table"]] += int(group["violation_count"])
    report["summary"] = {
        "affected_child_tables": sorted(by_child),
        "affected_parent_tables": sorted(by_parent),
        "violations_by_child_table": dict(by_child.most_common()),
        "violations_by_parent_table": dict(by_parent.most_common()),
        "top_groups": [
            {
                "child_table": group["child_table"],
                "parent_table": group["parent_table"],
                "fk_id": group["fk_id"],
                "violation_count": group["violation_count"],
            }
            for group in groups[:10]
        ],
    }


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SQLite foreign-key violation audit.")
    parser.add_argument("--db-path", default="", help="SQLite database path. Defaults to config.database.path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--sample-limit", type=int, default=5, help="Sample child rowids per violation group.")
    parser.add_argument("--out", default="", help="Optional output path for the rendered report.")
    parser.add_argument("--fail-on-violation", action="store_true", help="Exit 1 when violations are found.")
    args = parser.parse_args(argv)

    report = collect_foreign_key_audit(args.db_path or None, sample_limit=max(args.sample_limit, 0))
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.json
        else format_markdown_report(report)
    )
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    if report["status"] == "error":
        return 2
    if args.fail_on_violation and int(report.get("violation_count") or 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
