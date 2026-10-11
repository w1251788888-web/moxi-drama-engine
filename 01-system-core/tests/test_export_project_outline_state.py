import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import export_project_outline_state as export_outline  # noqa: E402


def _create_project_db(path: Path, config: dict):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            create table project_v2 (
              id text primary key,
              name text not null,
              description text,
              config text,
              project_type text,
              audience_axis text,
              genre_main text,
              genre_sub text,
              total_episodes integer,
              completed_episodes integer,
              current_episode integer,
              status text,
              created_at text,
              updated_at text,
              created_by text
            )
            """
        )
        conn.execute(
            """
            insert into project_v2 (
              id, name, description, config, project_type, audience_axis,
              genre_main, genre_sub, total_episodes, completed_episodes,
              current_episode, status, created_at, updated_at, created_by
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "project-1",
                "测试项目",
                "真实项目快照测试",
                json.dumps(config, ensure_ascii=False),
                "短剧",
                "混合",
                "都市悬疑",
                "",
                30,
                0,
                1,
                "draft",
                "2026-05-31T00:00:00",
                "2026-05-31T01:00:00",
                "user-1",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _args(db: Path, output_dir: Path):
    return SimpleNamespace(
        tenant_root=output_dir,
        db=db,
        project_id="",
        output_dir=output_dir,
        output=None,
    )


def test_export_project_outline_state_preserves_explicit_outline(tmp_path):
    db = tmp_path / "tenant.db"
    output_dir = tmp_path / "exports"
    config = {
        "workflow_context": {
            "outline_state": {
                "main_chain_committed": True,
                "main_chain_dirty": False,
                "outline_data": {
                    "logline": "何铮保护证人并反查家族系统。",
                    "episodes": [
                        {
                            "ep": 1,
                            "title": "雨夜档案",
                            "summary": "何铮在档案室发现证人吴雪被追杀。",
                        }
                    ],
                },
                "outline_characters": [
                    {"name": "何铮", "role": "protagonist", "info": "继承人，被迫查案。"}
                ],
            }
        }
    }
    _create_project_db(db, config)

    result = export_outline.export_project(_args(db, output_dir))
    payload = json.loads(Path(result["output"]).read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "project_outline_state_scan_manifest.json").read_text(encoding="utf-8"))

    assert result["event"] == "exported_project_outline_state"
    assert result["main_chain_committed"] is True
    assert result["outline_episode_count"] == 1
    assert result["outline_character_count"] == 1
    assert payload["project"]["name"] == "测试项目"
    assert payload["outline_state"]["main_chain_committed"] is True
    assert payload["outline_data"]["episodes"][0]["title"] == "雨夜档案"
    assert payload["outline_characters"][0]["name"] == "何铮"
    assert manifest["project_count"] == 1


def test_export_project_outline_state_reports_empty_project_db(tmp_path):
    db = tmp_path / "tenant.db"
    output_dir = tmp_path / "exports"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            create table project_v2 (
              id text primary key,
              name text not null,
              description text,
              config text,
              project_type text,
              audience_axis text,
              genre_main text,
              genre_sub text,
              total_episodes integer,
              completed_episodes integer,
              current_episode integer,
              status text,
              created_at text,
              updated_at text,
              created_by text
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    result = export_outline.export_project(_args(db, output_dir))
    manifest = json.loads((output_dir / "project_outline_state_scan_manifest.json").read_text(encoding="utf-8"))

    assert result["event"] == "no_project_found"
    assert result["project_count"] == 0
    assert manifest["project_count"] == 0
