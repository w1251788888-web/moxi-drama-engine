"""数据一致性体检：DB / 文件夹 / _index.json 三边对账。

使用：
    cd 01-system-core
    source .venv/bin/activate
    python scripts/check_consistency.py            # 只读报告
    python scripts/check_consistency.py --fix      # 自动补齐 _index.json，标记孤儿目录

退出码：
    0  三边一致
    1  有不一致（按报告处理）
    2  脚本执行错误
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services import workspace_service

WORKSPACE_ROOT = workspace_service.WORKSPACE_ROOT
INDEX_FILE = WORKSPACE_ROOT / "_index.json"
EPISODE_DIR_RE = re.compile(r"^ep(?P<episode>\d+)$")
SCENE_VERSION_RE = re.compile(r"^sc(?P<scene>\d+)_(?P<version>v\d+)\.md$")


def expected_workspace_path(project_name: str) -> Path:
    return WORKSPACE_ROOT / workspace_service.safe_project_dir_name(project_name)


def read_db_projects() -> dict[str, dict[str, str]]:
    from app.database import SessionLocal
    from app.models.project_v2 import ProjectV2

    with SessionLocal() as db:
        return {
            row.name: {
                "id": row.id,
                "workspace_path": row.workspace_path or "",
                "status": row.status or "active",
            }
            for row in db.query(ProjectV2).all()
        }


def read_db_names() -> set[str]:
    return set(read_db_projects())


def read_index_projects() -> dict[str, dict]:
    roots = [INDEX_FILE]
    if WORKSPACE_ROOT.exists():
        roots.extend(path for path in WORKSPACE_ROOT.rglob("_index.json") if path != INDEX_FILE)
    projects: dict[str, dict] = {}
    for index_file in roots:
        if not index_file.exists():
            continue
        try:
            raw = json.loads(index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("projects", [])
        else:
            items = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item.get("name"):
                continue
            copied = dict(item)
            copied.setdefault("_index_file", str(index_file))
            projects[copied["name"]] = copied
    return projects


def read_index_names() -> set[str]:
    return set(read_index_projects())


def read_dir_projects() -> dict[str, Path]:
    if not WORKSPACE_ROOT.exists():
        return {}
    projects: dict[str, Path] = {}
    for project_file in WORKSPACE_ROOT.rglob("project.json"):
        workspace = project_file.parent
        if workspace.name.startswith("_"):
            continue
        payload = workspace_service.read_json_file(project_file)
        name = str(payload.get("name") or workspace.name).strip()
        if name:
            projects[name] = workspace
    return projects


def read_dir_names() -> set[str]:
    return set(read_dir_projects())


def _workspace_path_mismatches(
    db_projects: dict[str, dict[str, str]],
    fs: set[str],
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    fs_projects = read_dir_projects()
    for name, project in db_projects.items():
        if name not in fs:
            continue
        expected = fs_projects.get(name)
        if expected is None:
            try:
                expected = expected_workspace_path(name)
            except ValueError:
                continue
        current_text = str(project.get("workspace_path") or "")
        if not current_text:
            current = Path("")
        else:
            current = Path(current_text).expanduser()
        if current.resolve(strict=False) == expected.resolve(strict=False):
            continue
        mismatches.append({
            "name": name,
            "id": project.get("id", ""),
            "db_path": current_text,
            "expected_path": str(expected),
        })
    return sorted(mismatches, key=lambda item: item["name"])


def reconcile(
    db: set[str],
    idx: set[str],
    fs: set[str],
    db_projects: dict[str, dict[str, str]] | None = None,
) -> dict:
    return {
        "in_db_only": sorted(db - idx - fs),
        "in_idx_only": sorted(idx - db - fs),
        "in_fs_only": sorted(fs - db - idx),
        "missing_from_idx": sorted((db & fs) - idx),
        "missing_from_fs": sorted((db & idx) - fs),
        "missing_from_db": sorted((idx & fs) - db),
        "consistent": sorted(db & idx & fs),
        "workspace_path_mismatches": _workspace_path_mismatches(db_projects or {}, fs),
    }


def fix_index(report: dict) -> int:
    """把 fs 里有、idx 里缺的项目补回 _index.json。不会动 DB 和文件系统。"""
    to_add = report["missing_from_idx"] + report["in_fs_only"]
    if not to_add:
        return 0
    fs_projects = read_dir_projects()
    now = datetime.now().isoformat()
    added = 0
    for name in to_add:
        workspace = fs_projects.get(name) or expected_workspace_path(name)
        index_file = workspace.parent / "_index.json"
        if index_file.exists():
            raw = json.loads(index_file.read_text(encoding="utf-8"))
            index = raw if isinstance(raw, dict) else {"projects": raw or []}
        else:
            index = {"projects": []}
        if not isinstance(index.get("projects"), list):
            index["projects"] = []
        existing_names = {p["name"] for p in index["projects"] if isinstance(p, dict)}
        if name in existing_names:
            continue
        index["projects"].append({
            "name": name,
            "path": str(workspace),
            "created": now,
            "last_active": now,
            "status": "active",
        })
        index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        added += 1
    return added


def fix_db_workspace_paths(report: dict) -> int:
    mismatches = report.get("workspace_path_mismatches") or []
    if not mismatches:
        return 0

    from app.database import SessionLocal
    from app.models.project_v2 import ProjectV2

    updated = 0
    with SessionLocal() as db:
        for item in mismatches:
            expected = Path(item["expected_path"])
            if not expected.exists() or not expected.is_dir():
                continue
            project = db.query(ProjectV2).filter(ProjectV2.id == item.get("id")).first()
            if not project:
                project = db.query(ProjectV2).filter(ProjectV2.name == item["name"]).first()
            if not project:
                continue
            project.workspace_path = str(expected)
            project_payload = workspace_service.read_project_json(expected)
            project_payload.update({
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "project_type": project.project_type,
                "audience_axis": project.audience_axis,
                "genre_main": project.genre_main,
                "genre_sub": project.genre_sub,
                "total_episodes": project.total_episodes,
                "status": project.status,
                "updated_at": datetime.now().isoformat(),
            })
            workspace_service.write_project_json(
                expected,
                project_payload,
                allowed_roots=(WORKSPACE_ROOT,),
                create=True,
            )
            updated += 1
        if updated:
            db.commit()
        else:
            db.rollback()
    return updated


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _coerce_int(value: object, default: int, *, minimum: int = 0, maximum: int = 10_000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _load_workspace_project(name: str) -> tuple[Path, dict]:
    workspace = read_dir_projects().get(name) or expected_workspace_path(name)
    project_file = workspace / "project.json"
    if not project_file.exists():
        return workspace, {}
    return workspace, workspace_service.read_json_file(project_file)


def _iter_scene_version_files(workspace: Path) -> list[dict]:
    versions: list[dict] = []
    episodes_root = workspace / "episodes"
    if not episodes_root.exists():
        return versions
    for ep_dir in sorted(episodes_root.iterdir()):
        if not ep_dir.is_dir():
            continue
        ep_match = EPISODE_DIR_RE.match(ep_dir.name)
        if not ep_match:
            continue
        episode_number = int(ep_match.group("episode"))
        scenes_dir = ep_dir / "scenes"
        if not scenes_dir.exists():
            continue
        for scene_file in sorted(scenes_dir.glob("*.md")):
            scene_match = SCENE_VERSION_RE.match(scene_file.name)
            if not scene_match:
                continue
            versions.append({
                "episode_number": episode_number,
                "scene_number": int(scene_match.group("scene")),
                "version_code": scene_match.group("version"),
                "path": scene_file,
            })
    return versions


def _group_versions_by_episode_scene(versions: list[dict]) -> dict[int, dict[int, list[dict]]]:
    grouped: dict[int, dict[int, list[dict]]] = {}
    for item in versions:
        grouped.setdefault(item["episode_number"], {}).setdefault(item["scene_number"], []).append(item)
    for scenes in grouped.values():
        for items in scenes.values():
            items.sort(key=lambda item: item["version_code"])
    return grouped


def _checkpoint_files(workspace: Path) -> list[Path]:
    checkpoint_root = workspace / "checkpoints"
    if not checkpoint_root.exists():
        return []
    return sorted(path for path in checkpoint_root.glob("*.json") if path.is_file())


def build_restore_plan(report: dict) -> list[dict]:
    names = sorted(set(report.get("missing_from_db") or []) | set(report.get("in_fs_only") or []))
    plan: list[dict] = []
    for name in names:
        workspace, project_data = _load_workspace_project(name)
        versions = _iter_scene_version_files(workspace)
        grouped = _group_versions_by_episode_scene(versions)
        checkpoints = _checkpoint_files(workspace)
        plan.append({
            "name": name,
            "workspace_path": str(workspace),
            "can_restore": bool(project_data and workspace.exists()),
            "episodes": len(grouped),
            "scenes": sum(len(scenes) for scenes in grouped.values()),
            "versions": len(versions),
            "checkpoints": len(checkpoints),
            "reason": "" if project_data and workspace.exists() else "missing project.json or workspace",
        })
    return plan


def _update_index_project_id(name: str, project_id: str, workspace: Path, project_data: dict) -> None:
    index_file = workspace.parent / "_index.json"
    raw = workspace_service.read_json_file(index_file)
    index = raw if raw else {"projects": []}
    if not isinstance(index.get("projects"), list):
        index["projects"] = []
    now = datetime.now().isoformat()
    updated = False
    for item in index["projects"]:
        if not isinstance(item, dict) or item.get("name") != name:
            continue
        item["id"] = project_id
        item["path"] = str(workspace)
        item["status"] = item.get("status") or "active"
        item["created"] = item.get("created") or project_data.get("created_at") or now
        item["last_active"] = now
        updated = True
        break
    if not updated:
        index["projects"].append({
            "id": project_id,
            "name": name,
            "path": str(workspace),
            "created": project_data.get("created_at") or now,
            "last_active": now,
            "status": "active",
        })
    workspace_service.write_json_file(index_file, index)


def restore_missing_db_projects(report: dict, *, apply: bool = False) -> list[dict]:
    plan = build_restore_plan(report)
    if not apply:
        for item in plan:
            item["status"] = "would_restore" if item["can_restore"] else "skipped"
        return plan

    from app.database import SessionLocal
    from app.models.project_v2 import Checkpoint, ContentVersion, Episode, ProjectV2, Scene

    restored: list[dict] = []
    with SessionLocal() as db:
        for item in plan:
            name = item["name"]
            if not item["can_restore"]:
                item["status"] = "skipped"
                restored.append(item)
                continue
            if db.query(ProjectV2).filter(ProjectV2.name == name).first():
                item["status"] = "already_exists"
                restored.append(item)
                continue

            workspace, project_data = _load_workspace_project(name)
            config = project_data.get("config") if isinstance(project_data.get("config"), dict) else {}
            total_episodes = _coerce_int(
                project_data.get("total_episodes") or config.get("total_episodes") or item["episodes"] or 80,
                80,
                minimum=1,
                maximum=200,
            )
            project = ProjectV2(
                name=name,
                description=str(project_data.get("description") or ""),
                project_type=str(project_data.get("project_type") or "真人短剧-男频"),
                audience_axis=str(project_data.get("audience_axis") or "男频"),
                genre_main=str(project_data.get("genre_main") or "都市"),
                genre_sub=str(project_data.get("genre_sub") or "逆袭"),
                total_episodes=total_episodes,
                completed_episodes=item["episodes"],
                current_episode=max(1, min(total_episodes, item["episodes"] + 1)),
                status=str(project_data.get("status") or "active"),
                workspace_path=str(workspace),
                created_at=_parse_datetime(project_data.get("created_at")) or datetime.now(),
                updated_at=_parse_datetime(project_data.get("updated_at")) or datetime.now(),
            )
            project.set_config(config)
            db.add(project)
            db.flush()

            grouped = _group_versions_by_episode_scene(_iter_scene_version_files(workspace))
            for episode_number, scenes in grouped.items():
                latest_episode_version = "v000"
                for scene_versions in scenes.values():
                    if scene_versions:
                        latest_episode_version = max(latest_episode_version, scene_versions[-1]["version_code"])
                episode = Episode(
                    project_id=project.id,
                    episode_number=episode_number,
                    title=f"第{episode_number}集",
                    summary="",
                    status="completed" if scenes else "draft",
                    total_scenes=len(scenes),
                    completed_scenes=len(scenes),
                    current_version=latest_episode_version,
                )
                db.add(episode)
                db.flush()

                for scene_number, scene_versions in scenes.items():
                    latest = scene_versions[-1]
                    content = latest["path"].read_text(encoding="utf-8")
                    scene = Scene(
                        episode_id=episode.id,
                        scene_number=scene_number,
                        scene_code=f"{episode_number}-{scene_number}",
                        content=content,
                        content_path=str(latest["path"]),
                        word_count=len(content),
                        status="completed",
                        primary_author="workspace_restore",
                    )
                    db.add(scene)

                    for version_item in scene_versions:
                        version_content = version_item["path"].read_text(encoding="utf-8")
                        db.add(ContentVersion(
                            project_id=project.id,
                            episode_number=episode_number,
                            scene_number=scene_number,
                            version_code=version_item["version_code"],
                            parent_version="",
                            editor_type="system",
                            editor_id="workspace_restore",
                            editor_name="workspace_restore",
                            content_path=str(version_item["path"]),
                            content_hash=hashlib.sha256(version_content.encode()).hexdigest(),
                            diff_stats=json.dumps({"restored": True}, ensure_ascii=False),
                            contribution_score=0,
                            change_note="从 workspace 文件恢复 DB 索引",
                        ))

            for checkpoint_file in _checkpoint_files(workspace):
                payload = workspace_service.read_json_file(checkpoint_file)
                db.add(Checkpoint(
                    project_id=project.id,
                    checkpoint_code=checkpoint_file.stem[:20],
                    episode_number=_coerce_int(payload.get("episode_number"), 0),
                    scene_number=_coerce_int(payload.get("scene_number"), 0),
                    data_path=str(checkpoint_file),
                    note=str(payload.get("note") or "从 workspace 文件恢复 checkpoint 索引")[:500],
                    auto_created=True,
                    created_by=str(payload.get("created_by") or "workspace_restore"),
                ))

            project_data.update({
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "project_type": project.project_type,
                "audience_axis": project.audience_axis,
                "genre_main": project.genre_main,
                "genre_sub": project.genre_sub,
                "total_episodes": project.total_episodes,
                "status": project.status,
                "updated_at": datetime.now().isoformat(),
            })
            workspace_service.write_project_json(
                workspace,
                project_data,
                allowed_roots=(WORKSPACE_ROOT,),
                create=True,
            )
            _update_index_project_id(name, project.id, workspace, project_data)
            item["status"] = "restored"
            item["project_id"] = project.id
            restored.append(item)
        db.commit()
    return restored


def render(report: dict) -> str:
    lines = []
    lines.append(f"数据库项目数: {len(report['consistent']) + len(report['missing_from_idx']) + len(report['missing_from_fs']) + len(report['in_db_only'])}")
    lines.append(f"_index.json 项目数: {len(report['consistent']) + len(report['missing_from_db']) + len(report['missing_from_fs']) + len(report['in_idx_only'])}")
    lines.append(f"文件夹项目数: {len(report['consistent']) + len(report['missing_from_db']) + len(report['missing_from_idx']) + len(report['in_fs_only'])}")
    lines.append(f"三边一致: {len(report['consistent'])}")
    lines.append("")
    for key, label in [
        ("missing_from_idx", "❗DB+文件夹有但 _index.json 缺（建议补 index）"),
        ("missing_from_fs", "❗DB+_index 有但文件夹缺（孤儿 DB 记录）"),
        ("missing_from_db", "❗文件夹+_index 有但 DB 缺（孤儿文件）"),
        ("in_db_only", "❗只在 DB 里（重灾区，DB 失联）"),
        ("in_idx_only", "❗只在 _index.json 里（陈旧索引）"),
        ("in_fs_only", "❗只在文件夹里（未登记项目）"),
    ]:
        items = report[key]
        if items:
            lines.append(f"{label}: {len(items)}")
            for name in items:
                lines.append(f"  - {name}")
    mismatches = report.get("workspace_path_mismatches") or []
    if mismatches:
        lines.append(f"❗DB workspace_path 与当前项目库目录不一致: {len(mismatches)}")
        for item in mismatches:
            lines.append(f"  - {item['name']}")
            lines.append(f"    DB: {item['db_path']}")
            lines.append(f"    应为: {item['expected_path']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="项目三边一致性体检")
    parser.add_argument("--fix", action="store_true", help="自动补齐 _index.json")
    parser.add_argument("--fix-db-paths", action="store_true", help="把已存在项目文件夹对应的 DB workspace_path 修到当前 new-projects")
    parser.add_argument("--plan-restore-db", action="store_true", help="只输出文件侧孤儿项目恢复为 DB 索引的计划，不写库")
    parser.add_argument("--restore-missing-db", action="store_true", help="把文件夹+_index 中存在但 DB 缺失的项目恢复为 DB 索引")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    try:
        db_projects = read_db_projects()
        db = set(db_projects)
    except Exception as exc:  # pragma: no cover
        print(f"读取数据库失败: {exc}", file=sys.stderr)
        return 2

    idx = read_index_names()
    fs = read_dir_names()
    report = reconcile(db, idx, fs, db_projects)

    inconsistent = any(
        report[k]
        for k in ("missing_from_idx", "missing_from_fs", "missing_from_db", "in_db_only", "in_idx_only", "in_fs_only", "workspace_path_mismatches")
    )

    if args.fix and (report["missing_from_idx"] or report["in_fs_only"]):
        added = fix_index(report)
        print(f"已补齐 _index.json：新增 {added} 条")
        idx = read_index_names()
        report = reconcile(db, idx, fs, db_projects)
        inconsistent = any(
            report[k]
            for k in ("missing_from_idx", "missing_from_fs", "missing_from_db", "in_db_only", "in_idx_only", "in_fs_only", "workspace_path_mismatches")
        )

    if args.fix_db_paths and report["workspace_path_mismatches"]:
        updated = fix_db_workspace_paths(report)
        print(f"已修复 DB workspace_path：更新 {updated} 条")
        db_projects = read_db_projects()
        db = set(db_projects)
        report = reconcile(db, idx, fs, db_projects)
        inconsistent = any(
            report[k]
            for k in ("missing_from_idx", "missing_from_fs", "missing_from_db", "in_db_only", "in_idx_only", "in_fs_only", "workspace_path_mismatches")
        )

    restore_plan = None
    if args.plan_restore_db:
        restore_plan = restore_missing_db_projects(report, apply=False)
        if not args.json:
            print(json.dumps({"restore_plan": restore_plan}, ensure_ascii=False, indent=2))

    if args.restore_missing_db and (report["missing_from_db"] or report["in_fs_only"]):
        restore_plan = restore_missing_db_projects(report, apply=True)
        restored_count = sum(1 for item in restore_plan if item.get("status") == "restored")
        print(f"已恢复文件侧孤儿项目到 DB：新增 {restored_count} 个项目")
        db_projects = read_db_projects()
        db = set(db_projects)
        idx = read_index_names()
        fs = read_dir_names()
        report = reconcile(db, idx, fs, db_projects)
        inconsistent = any(
            report[k]
            for k in ("missing_from_idx", "missing_from_fs", "missing_from_db", "in_db_only", "in_idx_only", "in_fs_only", "workspace_path_mismatches")
        )

    if args.json:
        output = dict(report)
        if restore_plan is not None:
            output["restore_plan"] = restore_plan
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(render(report))

    return 1 if inconsistent else 0


if __name__ == "__main__":
    sys.exit(main())
