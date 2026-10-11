"""体检脚本核心 reconcile 逻辑的单元测试。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_consistency.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_consistency", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_consistency"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_reconcile_all_consistent():
    mod = _load_module()
    db = idx = fs = {"a", "b"}
    r = mod.reconcile(db, idx, fs)
    assert r["consistent"] == ["a", "b"]
    assert r["missing_from_idx"] == []
    assert r["missing_from_fs"] == []
    assert r["missing_from_db"] == []


def test_reconcile_missing_from_index():
    mod = _load_module()
    r = mod.reconcile({"a"}, set(), {"a"})
    assert r["missing_from_idx"] == ["a"]


def test_reconcile_orphan_in_filesystem():
    mod = _load_module()
    r = mod.reconcile(set(), set(), {"orphan"})
    assert r["in_fs_only"] == ["orphan"]


def test_reconcile_orphan_in_db():
    mod = _load_module()
    r = mod.reconcile({"ghost"}, set(), set())
    assert r["in_db_only"] == ["ghost"]


def test_reconcile_partial_overlap():
    mod = _load_module()
    r = mod.reconcile({"a", "b"}, {"b", "c"}, {"a", "c"})
    assert r["consistent"] == []
    assert r["missing_from_idx"] == ["a"]
    assert r["missing_from_db"] == ["c"]
    assert r["missing_from_fs"] == ["b"]


def test_consistency_script_uses_current_new_projects_root():
    mod = _load_module()
    assert mod.WORKSPACE_ROOT.name == "new-projects"


def test_reconcile_reports_workspace_path_mismatch(tmp_path, monkeypatch):
    mod = _load_module()
    workspace_root = tmp_path / "03-project-library" / "new-projects"
    (workspace_root / "项目A").mkdir(parents=True)
    monkeypatch.setattr(mod, "WORKSPACE_ROOT", workspace_root)

    r = mod.reconcile(
        {"项目A"},
        {"项目A"},
        {"项目A"},
        {"项目A": {"id": "p1", "workspace_path": str(tmp_path / "03-项目库" / "新建项目" / "项目A")}},
    )

    assert r["consistent"] == ["项目A"]
    assert r["workspace_path_mismatches"] == [
        {
            "name": "项目A",
            "id": "p1",
            "db_path": str(tmp_path / "03-项目库" / "新建项目" / "项目A"),
            "expected_path": str(workspace_root / "项目A"),
        }
    ]


def test_consistency_script_reads_actor_scoped_workspaces(tmp_path, monkeypatch):
    mod = _load_module()
    workspace_root = tmp_path / "03-project-library" / "new-projects"
    project_dir = workspace_root / "users" / "key-a" / "项目A"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(
        json.dumps({"name": "项目A", "owner_scope": "users/key-a"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (project_dir.parent / "_index.json").write_text(
        json.dumps({"projects": [{"name": "项目A", "path": str(project_dir)}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(mod, "INDEX_FILE", workspace_root / "_index.json")

    assert mod.read_dir_names() == {"项目A"}
    assert mod.read_index_names() == {"项目A"}
    report = mod.reconcile(
        {"项目A"},
        mod.read_index_names(),
        mod.read_dir_names(),
        {"项目A": {"id": "p1", "workspace_path": str(project_dir)}},
    )
    assert report["consistent"] == ["项目A"]
    assert report["in_fs_only"] == []
    assert report["workspace_path_mismatches"] == []


def test_restore_missing_db_projects_rebuilds_project_episode_scene_version_and_checkpoint(tmp_path, monkeypatch):
    mod = _load_module()
    workspace_root = tmp_path / "03-project-library" / "new-projects"
    project_dir = workspace_root / "项目A"
    scene_dir = project_dir / "episodes" / "ep01" / "scenes"
    checkpoint_dir = project_dir / "checkpoints"
    scene_dir.mkdir(parents=True)
    checkpoint_dir.mkdir()
    (project_dir / "project.json").write_text(
        json.dumps(
            {
                "name": "项目A",
                "created_at": "2026-05-01T10:00:00",
                "updated_at": "2026-05-01T11:00:00",
                "config": {"total_episodes": 3, "episode_seconds": 90},
                "characters": [{"name": "主角"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (scene_dir / "sc01_v001.md").write_text("第一版", encoding="utf-8")
    (scene_dir / "sc01_v002.md").write_text("第二版", encoding="utf-8")
    (checkpoint_dir / "cp001.json").write_text(
        json.dumps({"episode_number": 1, "scene_number": 1, "note": "测试断点"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (workspace_root / "_index.json").write_text(
        json.dumps({"projects": [{"name": "项目A", "path": str(project_dir)}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(mod, "INDEX_FILE", workspace_root / "_index.json")

    from app import database
    from app.models.project_v2 import Checkpoint, ContentVersion, Episode, ProjectV2, Scene
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'restore.db'}", connect_args={"check_same_thread": False})
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "SessionLocal", session)
    for model in (ProjectV2, Episode, Scene, ContentVersion, Checkpoint):
        model.__table__.create(bind=engine)

    report = {
        "missing_from_db": ["项目A"],
        "in_fs_only": [],
        "missing_from_idx": [],
        "missing_from_fs": [],
        "in_db_only": [],
        "in_idx_only": [],
        "workspace_path_mismatches": [],
        "consistent": [],
    }

    dry_run = mod.restore_missing_db_projects(report, apply=False)
    assert dry_run[0]["status"] == "would_restore"
    assert dry_run[0]["episodes"] == 1
    assert dry_run[0]["versions"] == 2

    restored = mod.restore_missing_db_projects(report, apply=True)
    assert restored[0]["status"] == "restored"

    with session() as db:
        project = db.query(ProjectV2).filter(ProjectV2.name == "项目A").one()
        assert project.workspace_path == str(project_dir)
        assert db.query(Episode).filter(Episode.project_id == project.id).count() == 1
        scene = db.query(Scene).one()
        assert scene.content == "第二版"
        assert db.query(ContentVersion).filter(ContentVersion.project_id == project.id).count() == 2
        assert db.query(Checkpoint).filter(Checkpoint.project_id == project.id).count() == 1

    index = json.loads((workspace_root / "_index.json").read_text(encoding="utf-8"))
    assert index["projects"][0]["id"]
    project_json = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert project_json["id"] == index["projects"][0]["id"]
