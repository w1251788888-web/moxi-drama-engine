import json
import sqlite3


def _create_fk_test_database(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE parent_task (
                id TEXT PRIMARY KEY
            );
            CREATE TABLE child_metric (
                id INTEGER PRIMARY KEY,
                task_id TEXT NOT NULL,
                note TEXT,
                FOREIGN KEY(task_id) REFERENCES parent_task(id)
            );
            INSERT INTO parent_task(id) VALUES ('task-ok');
            INSERT INTO child_metric(task_id, note) VALUES ('task-ok', 'linked');
            INSERT INTO child_metric(task_id, note) VALUES ('task-missing-1', 'orphan one');
            INSERT INTO child_metric(task_id, note) VALUES ('task-missing-2', 'orphan two');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_foreign_key_audit_groups_violations_and_samples_child_values(tmp_path):
    from scripts.sqlite_foreign_key_audit import collect_foreign_key_audit, format_markdown_report

    db_path = tmp_path / "fk-audit.db"
    _create_fk_test_database(db_path)

    report = collect_foreign_key_audit(db_path, sample_limit=1)
    rendered = format_markdown_report(report)

    assert report["status"] == "warning"
    assert report["violation_count"] == 2
    assert report["group_count"] == 1
    assert report["summary"]["violations_by_child_table"] == {"child_metric": 2}
    group = report["groups"][0]
    assert group["child_table"] == "child_metric"
    assert group["parent_table"] == "parent_task"
    assert group["child_columns"] == ["task_id"]
    assert group["parent_columns"] == ["id"]
    assert group["sample_child_values"][0]["child_values"]["task_id"] == "task-missing-1"
    assert "SQLite Foreign Key Audit" in rendered
    assert "`child_metric`" in rendered


def test_foreign_key_audit_reports_ok_when_database_has_no_violations(tmp_path):
    from scripts.sqlite_foreign_key_audit import collect_foreign_key_audit

    db_path = tmp_path / "fk-clean.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE parent_task (id TEXT PRIMARY KEY);
            CREATE TABLE child_metric (
                id INTEGER PRIMARY KEY,
                task_id TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES parent_task(id)
            );
            INSERT INTO parent_task(id) VALUES ('task-ok');
            INSERT INTO child_metric(task_id) VALUES ('task-ok');
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = collect_foreign_key_audit(db_path)

    assert report["status"] == "ok"
    assert report["violation_count"] == 0
    assert report["groups"] == []


def test_foreign_key_audit_cli_emits_json_without_failing_on_warning(tmp_path, capsys):
    from scripts.sqlite_foreign_key_audit import main

    db_path = tmp_path / "fk-cli.db"
    _create_fk_test_database(db_path)

    exit_code = main(["--db-path", str(db_path), "--json", "--sample-limit", "1"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["status"] == "warning"
    assert payload["violation_count"] == 2
    assert main(["--db-path", str(db_path), "--fail-on-violation"]) == 1


def test_project_learning_project_identifiers_do_not_create_task_foreign_keys():
    from app.models.project_learning import (
        LearningInsight,
        ProjectMaterial,
        RuleExtractionJob,
        UserEditRecord,
        WorkflowEfficiencyMetrics,
    )

    project_scoped_columns = [
        ProjectMaterial.__table__.c.project_id,
        ProjectMaterial.__table__.c.session_id,
        UserEditRecord.__table__.c.project_id,
        UserEditRecord.__table__.c.session_id,
        RuleExtractionJob.__table__.c.project_id,
        WorkflowEfficiencyMetrics.__table__.c.project_id,
        LearningInsight.__table__.c.project_id,
    ]

    for column in project_scoped_columns:
        assert not column.foreign_keys
