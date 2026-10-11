import sqlite3

import pytest
from sqlalchemy import create_engine, text


def test_sqlite_runtime_pragmas_are_applied_to_file_database(tmp_path):
    from app.database import configure_sqlite_connection

    db_path = tmp_path / "runtime.db"
    conn = sqlite3.connect(db_path)
    try:
        configure_sqlite_connection(conn, enable_wal=True)

        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2
        assert conn.execute("PRAGMA cache_size").fetchone()[0] < 0
    finally:
        conn.close()


def test_configured_database_path_is_current_single_source():
    from app.config import config

    assert config.database_type == "sqlite"
    assert config.database_path.replace("\\", "/").endswith("data/tasks.db")


def test_sqlite_performance_indexes_are_backfilled_for_existing_database(tmp_path):
    from app.database import ensure_sqlite_performance_indexes

    db_path = tmp_path / "indexes.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, status TEXT, type TEXT, created_at TEXT, updated_at TEXT)"))
        conn.execute(text("CREATE TABLE module (id TEXT PRIMARY KEY, task_id TEXT, name TEXT, created_at TEXT)"))
        conn.execute(text("CREATE TABLE sub_task (id TEXT PRIMARY KEY, task_id TEXT, module_id TEXT, status TEXT, assigned_agent TEXT, created_at TEXT)"))
        conn.execute(text("CREATE TABLE activity_log (id TEXT PRIMARY KEY, agent_id TEXT, sub_task_id TEXT, action TEXT, created_at TEXT)"))
        ensure_sqlite_performance_indexes(conn, existing_tables={"task", "module", "sub_task", "activity_log"})

    conn = sqlite3.connect(db_path)
    try:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "ix_task_status_created" in indexes
        assert "ix_module_task_created" in indexes
        assert "ix_sub_task_task_status_created" in indexes
        assert "ix_activity_log_action_created" in indexes
    finally:
        conn.close()


def test_project_v2_name_uniqueness_is_scoped_to_owner(tmp_path):
    from app.database import ensure_project_v2_owner_name_uniqueness

    db_path = tmp_path / "project-owner-name.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE project_v2 ("
                "id TEXT PRIMARY KEY, "
                "name VARCHAR(200) NOT NULL, "
                "created_by VARCHAR(36) DEFAULT '', "
                "workspace_path TEXT DEFAULT ''"
                ")"
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX ix_project_v2_name ON project_v2(name)"))
        conn.execute(
            text(
                "INSERT INTO project_v2(id, name, created_by, workspace_path) "
                "VALUES ('p1', '同名项目', 'key-a', '/tmp/a')"
            )
        )
        ensure_project_v2_owner_name_uniqueness(conn)

    conn = sqlite3.connect(db_path)
    try:
        indexes = {
            row[1]: {"unique": row[2], "columns": [info[2] for info in conn.execute(f'PRAGMA index_info("{row[1]}")')]}
            for row in conn.execute("PRAGMA index_list('project_v2')").fetchall()
        }
        assert indexes["ix_project_v2_name"]["unique"] == 0
        assert indexes["ix_project_v2_owner_name"]["unique"] == 1
        assert indexes["ix_project_v2_owner_name"]["columns"] == ["created_by", "name"]

        conn.execute(
            "INSERT INTO project_v2(id, name, created_by, workspace_path) VALUES (?, ?, ?, ?)",
            ("p2", "同名项目", "key-b", "/tmp/b"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO project_v2(id, name, created_by, workspace_path) VALUES (?, ?, ?, ?)",
                ("p3", "同名项目", "key-b", "/tmp/c"),
            )
    finally:
        conn.close()


def test_sqlite_performance_index_backfill_respects_explicit_empty_table_set(tmp_path):
    from app.database import ensure_sqlite_performance_indexes

    db_path = tmp_path / "empty-indexes.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        ensure_sqlite_performance_indexes(conn, existing_tables=set())


def test_sqlite_runtime_diagnostics_reports_pragmas_indexes_and_counts(tmp_path):
    from app.database import configure_sqlite_connection
    from scripts.sqlite_runtime_diagnostics import collect_sqlite_diagnostics, format_text_report

    db_path = tmp_path / "diagnostics.db"
    conn = sqlite3.connect(db_path)
    try:
        configure_sqlite_connection(conn, enable_wal=True)
        conn.executescript(
            """
            CREATE TABLE task (
                id TEXT PRIMARY KEY,
                status TEXT,
                type TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE INDEX ix_task_status_created ON task(status, created_at);
            CREATE TABLE module (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                name TEXT,
                created_at TEXT
            );
            CREATE INDEX ix_module_task_created ON module(task_id, created_at);
            INSERT INTO task(id, status, type, created_at, updated_at)
            VALUES ('task-1', 'active', 'once', '2026-05-10', '2026-05-10');
            INSERT INTO module(id, task_id, name, created_at)
            VALUES ('module-1', 'task-1', 'demo', '2026-05-10');
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = collect_sqlite_diagnostics(
        db_path,
        expected_indexes={
            "task": ["ix_task_status_created"],
            "module": ["ix_module_task_created"],
        },
    )
    text = format_text_report(report)

    assert report["status"] == "ok"
    assert report["pragmas"]["journal_mode"].lower() == "wal"
    assert report["pragmas"]["busy_timeout"] >= 5000
    assert report["index_checks"]["task"]["missing"] == []
    assert report["index_checks"]["module"]["missing"] == []
    assert {"table": "task", "rows": 1} in report["table_counts"]["all_tables"]
    assert "SQLite Runtime Diagnostics" in text
    assert "ix_task_status_created" not in text


def test_sqlite_runtime_diagnostics_flags_missing_indexes(tmp_path):
    from app.database import configure_sqlite_connection
    from scripts.sqlite_runtime_diagnostics import collect_sqlite_diagnostics

    db_path = tmp_path / "missing-index.db"
    conn = sqlite3.connect(db_path)
    try:
        configure_sqlite_connection(conn, enable_wal=True)
        conn.execute(
            """
            CREATE TABLE task (
                id TEXT PRIMARY KEY,
                status TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute("INSERT INTO task(id, status, created_at) VALUES ('task-1', 'active', '2026-05-10')")
        conn.commit()
    finally:
        conn.close()

    report = collect_sqlite_diagnostics(
        db_path,
        expected_indexes={"task": ["ix_task_status_created"]},
    )

    assert report["status"] == "warning"
    assert report["index_checks"]["task"]["missing"] == ["ix_task_status_created"]
    assert report["slow_query_candidates"][0]["reason"] == "missing_expected_indexes"
    assert any("expected index missing: task.ix_task_status_created" in item for item in report["warnings"])
