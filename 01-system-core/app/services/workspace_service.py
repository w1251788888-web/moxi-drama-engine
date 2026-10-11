"""Workspace path and JSON persistence helpers.

This module is intentionally small and framework-free so routers and services can
share one boundary policy without importing FastAPI internals.
"""
from __future__ import annotations

import json
import hashlib
import fcntl
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_LIBRARY_ROOT = REPO_ROOT / "03-project-library"
WORKSPACE_ROOT = PROJECT_LIBRARY_ROOT / "new-projects"
LEGACY_WORKSPACE_ROOT = PROJECT_LIBRARY_ROOT / "新建项目"
ACCEPTANCE_ARTIFACT_DIR_NAME = "墨戏生花验收"
GENERATION_ARTIFACT_DIR_NAME = "generation-jobs"


class WorkspaceError(ValueError):
    """Base error for controlled workspace operations."""


class WorkspaceBoundaryError(WorkspaceError):
    """Raised when a path is outside the allowed workspace roots."""


class WorkspaceMissingError(WorkspaceError):
    """Raised when a required workspace path is missing."""


def path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_project_dir_name(project_name: str) -> str:
    """Return a single safe directory name for a project."""
    name = str(project_name or "").strip()
    if not name or "/" in name or "\\" in name or "\x00" in name:
        raise WorkspaceBoundaryError("项目名称不能包含路径分隔符")
    candidate = Path(name)
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.parts[0] in {".", ".."}:
        raise WorkspaceBoundaryError("项目名称不能包含路径分隔符")
    return name


def ensure_path_within_roots(path: str | Path, *, allowed_roots: Iterable[Path]) -> Path:
    target = Path(path).expanduser()
    if not str(target):
        raise WorkspaceMissingError("workspace_path 不能为空")

    resolved_target = target.resolve(strict=False)
    resolved_roots = tuple(root.expanduser().resolve(strict=False) for root in allowed_roots)
    is_allowed = any(
        resolved_target != root and path_is_relative_to(resolved_target, root)
        for root in resolved_roots
    )
    if not is_allowed:
        roots_text = ", ".join(str(root) for root in resolved_roots)
        raise WorkspaceBoundaryError(f"路径不在受控工作区内: {target}；允许根: {roots_text}")
    return resolved_target


def ensure_project_workspace(
    path: str | Path,
    *,
    allowed_roots: Iterable[Path],
    create: bool = False,
) -> Path:
    workspace = ensure_path_within_roots(path, allowed_roots=allowed_roots)
    if workspace.exists() and not workspace.is_dir():
        raise WorkspaceBoundaryError(f"workspace_path 不是目录: {workspace}")
    if not workspace.exists():
        if not create:
            raise WorkspaceMissingError(f"workspace_path 不存在: {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def safe_rmtree(path: str | Path, *, allowed_roots: Iterable[Path]) -> bool:
    """Delete a directory only when it is a child of an allowed root."""
    target = Path(path).expanduser()
    if not target.exists():
        return False
    if not target.is_dir():
        raise WorkspaceBoundaryError(f"拒绝删除非目录路径: {target}")

    resolved_target = ensure_path_within_roots(target, allowed_roots=allowed_roots)
    shutil.rmtree(resolved_target)
    return True


def read_json_file(path: str | Path) -> dict[str, Any]:
    json_file = Path(path)
    if not json_file.exists():
        return {}
    try:
        payload = json.loads(json_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_file(path: str | Path, data: dict[str, Any]) -> None:
    json_file = Path(path)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def project_workspace_path(project_name: str) -> Path:
    return WORKSPACE_ROOT / safe_project_dir_name(project_name)


def project_workspace_roots(*, include_legacy: bool = True) -> tuple[Path, ...]:
    roots = [WORKSPACE_ROOT]
    if include_legacy and LEGACY_WORKSPACE_ROOT != WORKSPACE_ROOT:
        roots.append(LEGACY_WORKSPACE_ROOT)
    return tuple(roots)


def read_project_json(workspace: str | Path) -> dict[str, Any]:
    return read_json_file(Path(workspace) / "project.json")


def write_project_json(
    workspace: str | Path,
    data: dict[str, Any],
    *,
    allowed_roots: Iterable[Path],
    create: bool = True,
) -> Path:
    project_workspace = ensure_project_workspace(
        workspace,
        allowed_roots=allowed_roots,
        create=create,
    )
    project_file = project_workspace / "project.json"
    write_json_file(project_file, data)
    return project_file


def update_project_json_atomically(
    workspace: str | Path,
    updater: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    allowed_roots: Iterable[Path],
    create: bool = True,
) -> dict[str, Any]:
    """Lock, reread, update and atomically replace one project.json file."""
    project_workspace = ensure_project_workspace(
        workspace,
        allowed_roots=allowed_roots,
        create=create,
    )
    project_file = project_workspace / "project.json"
    lock_file = project_workspace / ".project.json.lock"
    with lock_file.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        temporary_path: Path | None = None
        try:
            current = read_json_file(project_file)
            updated = updater(dict(current))
            if not isinstance(updated, dict):
                raise WorkspaceError("project.json 更新函数必须返回对象")
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=project_workspace,
                prefix=".project.json.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(updated, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, project_file)
            temporary_path = None
            directory_fd = os.open(project_workspace, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return updated
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def imports_root(category: str = "") -> Path:
    root = PROJECT_LIBRARY_ROOT / "imports"
    if category:
        root = root / safe_file_part(category)
    return root


def acceptance_artifacts_root() -> Path:
    return PROJECT_LIBRARY_ROOT / ACCEPTANCE_ARTIFACT_DIR_NAME


def ensure_acceptance_artifacts_root() -> Path:
    root = acceptance_artifacts_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def generation_artifacts_root() -> Path:
    return PROJECT_LIBRARY_ROOT / GENERATION_ARTIFACT_DIR_NAME


def ensure_generation_artifacts_root() -> Path:
    root = generation_artifacts_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def artifact_path(file_name: str, *, root: Path | None = None) -> Path:
    safe_name = safe_file_part(Path(file_name).stem) + Path(file_name).suffix
    return (root or ensure_acceptance_artifacts_root()) / safe_name


def episode_dir(workspace: str | Path, episode_number: int, *, create: bool = False) -> Path:
    safe_episode_number = max(1, int(episode_number))
    target = Path(workspace) / "episodes" / f"ep{safe_episode_number:02d}"
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def scene_version_path(
    workspace: str | Path,
    *,
    episode_number: int,
    scene_number: int,
    version_code: str,
) -> Path:
    raw_scene_number = int(scene_number)
    safe_scene_number = 0 if raw_scene_number == 0 else max(1, raw_scene_number)
    safe_version_code = safe_file_part(version_code)
    scenes_dir = episode_dir(workspace, episode_number, create=True) / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    return scenes_dir / f"sc{safe_scene_number:02d}_{safe_version_code}.md"


def checkpoint_path(workspace: str | Path, checkpoint_code: str) -> Path:
    safe_code = safe_file_part(checkpoint_code)
    checkpoint_dir = Path(workspace) / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir / f"{safe_code}.json"


def generation_job_artifact_path(
    workspace: str | Path | None,
    *,
    job_id: str,
    artifact_type: str,
    suffix: str,
) -> Path:
    safe_job_id = safe_file_part(job_id)
    safe_artifact_type = safe_file_part(artifact_type)
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    if workspace:
        root = Path(workspace) / "generation_jobs"
    else:
        root = ensure_generation_artifacts_root()
    target_dir = root / safe_artifact_type
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{safe_job_id}{safe_suffix}"


def safe_file_part(value: str) -> str:
    name = str(value or "").strip()
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)
    name = name.strip("._-")
    return name or "untitled"


def import_file_to_library(
    source_path: str | Path,
    *,
    category: str,
    allowed_suffixes: Iterable[str],
) -> Path:
    source = Path(source_path).expanduser()
    if not source.exists():
        raise WorkspaceMissingError(f"导入文件不存在: {source}")
    if not source.is_file():
        raise WorkspaceBoundaryError(f"导入目标不是文件: {source}")

    suffix = source.suffix.lower()
    allowed = tuple(item.lower() for item in allowed_suffixes)
    if suffix not in allowed:
        raise WorkspaceBoundaryError(f"不支持的导入文件类型: {source.suffix}")

    resolved_source = source.resolve()
    digest = hashlib.sha256(resolved_source.read_bytes()).hexdigest()[:12]
    safe_stem = safe_file_part(resolved_source.stem)
    target_root = imports_root(category)
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / f"{safe_stem}-{digest}{suffix}"
    if resolved_source != target.resolve(strict=False):
        shutil.copy2(resolved_source, target)
    return target
