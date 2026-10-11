#!/usr/bin/env python3
"""Build the minimal runtime bundle used for server deployment.

This intentionally packages only the files needed by the deployed product:
backend app code, built frontend static assets, prompt/rule files, Dify
knowledge metadata, integrated skill definitions, empty project-library
scaffolds, and deployment smoke tooling. It excludes local databases, user
projects, logs, tests, caches, build outputs, and the large Dify runtime
service directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]

INCLUDE_PATHS = (
    Path("01-system-core/app"),
    Path("01-system-core/static"),
    Path("01-system-core/prompts"),
    Path("01-system-core/requirements.txt"),
    Path("01-system-core/config.yaml.example"),
    Path("01-system-core/.env.example"),
    Path("01-system-core/scripts/package_runtime_bundle.py"),
    Path("01-system-core/scripts/production_smoke_test.py"),
    Path("02-creation-rules"),
    Path("03-project-library/README.md"),
    Path("03-project-library/new-projects/README.md"),
    Path("03-project-library/new-projects/_index.json"),
    Path("05-skill-plugins"),
)

EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "data",
    "logs",
    "backups",
    "runtime",
    "benchmark",
    "tests",
    "dify-rag-runtime",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".DS_Store",
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".log",
}

EXCLUDED_NAMES = {
    "._",
    ".coverage",
}


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_PARTS:
        return True
    if path.name.startswith("._"):
        return True
    if path.name in EXCLUDED_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def _iter_runtime_files(root: Path) -> Iterable[Path]:
    for include in INCLUDE_PATHS:
        base = root / include
        if not base.exists():
            continue
        if base.is_file() or base.is_symlink():
            if not _is_excluded(include):
                yield include
            continue
        for item in sorted(base.rglob("*")):
            rel = item.relative_to(root)
            if _is_excluded(rel):
                continue
            if item.is_file() or item.is_symlink():
                yield rel


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for rel in _iter_runtime_files(root):
        path = root / rel
        if path.is_symlink():
            files.append({
                "path": rel.as_posix(),
                "type": "symlink",
                "target": str(path.readlink()),
            })
            continue
        files.append({
            "path": rel.as_posix(),
            "type": "file",
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root": str(root),
        "file_count": len(files),
        "files": files,
        "excluded": {
            "parts": sorted(EXCLUDED_PARTS),
            "suffixes": sorted(EXCLUDED_SUFFIXES),
        },
    }


def create_bundle(root: Path, output: Path) -> dict[str, object]:
    manifest = build_manifest(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
        manifest_path = Path(fh.name)
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    try:
        with tarfile.open(output, "w:gz", dereference=False) as tar:
            for rel in _iter_runtime_files(root):
                tar.add(root / rel, arcname=rel.as_posix(), recursive=False)
            tar.add(manifest_path, arcname="DEPLOYMENT_RUNTIME_MANIFEST.json")
    finally:
        manifest_path.unlink(missing_ok=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 墨戏生花 runtime deployment bundle")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root")
    parser.add_argument(
        "--output",
        default="/tmp/moxi_runtime_bundle.tar.gz",
        help="Output tar.gz path",
    )
    parser.add_argument("--manifest-only", action="store_true", help="Print manifest JSON without creating a tarball")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.manifest_only:
        print(json.dumps(build_manifest(root), ensure_ascii=False, indent=2))
        return 0

    output = Path(args.output).resolve()
    manifest = create_bundle(root, output)
    print(json.dumps({
        "bundle": str(output),
        "file_count": manifest["file_count"],
        "size_bytes": output.stat().st_size,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
