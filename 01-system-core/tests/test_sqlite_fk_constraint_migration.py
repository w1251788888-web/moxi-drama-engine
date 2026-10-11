import sqlite3


def _create_legacy_fk_database(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE task (id TEXT PRIMARY KEY);
            CREATE TABLE sub_task (id TEXT PRIMARY KEY);
            CREATE TABLE rule (id TEXT PRIMARY KEY);
            CREATE TABLE episode_segments (id TEXT PRIMARY KEY);

            CREATE TABLE project_materials (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                session_id TEXT,
                material_type TEXT NOT NULL,
                source_segment_id TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY(source_segment_id) REFERENCES episode_segments(id),
                FOREIGN KEY(session_id) REFERENCES task(id),
                FOREIGN KEY(project_id) REFERENCES task(id)
            );
            CREATE INDEX ix_project_materials_project_id ON project_materials(project_id);

            CREATE TABLE user_edit_records (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                session_id TEXT,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                material_id TEXT,
                FOREIGN KEY(material_id) REFERENCES project_materials(id),
                FOREIGN KEY(session_id) REFERENCES task(id),
                FOREIGN KEY(project_id) REFERENCES task(id)
            );

            CREATE TABLE rule_extraction_jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                applied_to_rule_id TEXT,
                FOREIGN KEY(applied_to_rule_id) REFERENCES rule(id),
                FOREIGN KEY(project_id) REFERENCES task(id)
            );

            CREATE TABLE workflow_efficiency_metrics (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                date TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES task(id)
            );

            CREATE TABLE learning_insights (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                insight_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES task(id)
            );

            CREATE TABLE issue_record (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                sub_task_id TEXT,
                issue_key TEXT NOT NULL,
                title TEXT NOT NULL,
                category_path TEXT NOT NULL,
                scope_level TEXT NOT NULL,
                status TEXT NOT NULL,
                severity TEXT NOT NULL,
                FOREIGN KEY(sub_task_id) REFERENCES sub_task(id),
                FOREIGN KEY(task_id) REFERENCES task(id)
            );

            INSERT INTO rule(id) VALUES ('rule-ok');
            INSERT INTO project_materials(id, project_id, session_id, material_type, source_segment_id, title, content)
            VALUES ('mat-1', 'project-1', 'session-1', 'hook', 'segment-missing', 'title', 'content');
            INSERT INTO user_edit_records(id, project_id, session_id, target_type, target_id, material_id)
            VALUES ('edit-1', 'project-1', 'session-1', 'segment', 'seg-1', 'mat-1');
            INSERT INTO rule_extraction_jobs(id, project_id, applied_to_rule_id)
            VALUES ('job-1', 'project-1', 'rule-ok');
            INSERT INTO workflow_efficiency_metrics(id, project_id, date)
            VALUES ('metric-1', 'project-1', '2026-05-10');
            INSERT INTO learning_insights(id, project_id, insight_type, title, description)
            VALUES ('insight-1', 'project-1', 'pattern', 'title', 'desc');
            INSERT INTO issue_record(id, task_id, issue_key, title, category_path, scope_level, status, severity)
            VALUES ('issue-1', 'task-missing', 'key', 'title', 'cat', 'project', 'open', 'medium');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_fk_constraint_migration_dry_run_does_not_mutate_database(tmp_path):
    from scripts.migrate_sqlite_fk_constraints import migrate_fk_constraints

    db_path = tmp_path / "legacy-fk.db"
    _create_legacy_fk_database(db_path)

    report = migrate_fk_constraints(db_path)

    assert report["status"] == "planned"
    assert {item["table"] for item in report["tables"]} == {
        "project_materials",
        "user_edit_records",
        "rule_extraction_jobs",
        "workflow_efficiency_metrics",
        "learning_insights",
        "issue_record",
    }
    conn = sqlite3.connect(db_path)
    try:
        assert len(conn.execute("PRAGMA foreign_key_check").fetchall()) == 9
    finally:
        conn.close()


def test_fk_constraint_migration_removes_incorrect_constraints_and_preserves_data(tmp_path):
    from scripts.migrate_sqlite_fk_constraints import migrate_fk_constraints

    db_path = tmp_path / "legacy-fk-apply.db"
    _create_legacy_fk_database(db_path)

    report = migrate_fk_constraints(db_path, apply=True, allow_no_backup=True)

    assert report["status"] == "ok"
    assert report["post_migration_foreign_key_violation_count"] == 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM project_materials").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM issue_record").fetchone()[0] == 1
        material_fks = [dict(row) for row in conn.execute("PRAGMA foreign_key_list(project_materials)").fetchall()]
        issue_fks = [dict(row) for row in conn.execute("PRAGMA foreign_key_list(issue_record)").fetchall()]
        edit_fks = [dict(row) for row in conn.execute("PRAGMA foreign_key_list(user_edit_records)").fetchall()]
        assert material_fks == []
        assert {row["table"] for row in issue_fks} == {"sub_task"}
        assert {row["table"] for row in edit_fks} == {"project_materials"}
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert "ix_project_materials_project_id" in indexes
    finally:
        conn.close()


def test_issue_record_task_id_is_retained_as_text_reference_not_fk():
    from app.models.issue_record import IssueRecord

    assert not IssueRecord.__table__.c.task_id.foreign_keys
    assert IssueRecord.__table__.c.sub_task_id.foreign_keys
