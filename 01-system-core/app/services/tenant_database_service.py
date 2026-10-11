"""Per-access-key tenant database helpers.

This module is deliberately conservative: it creates and tracks a separate
SQLite file for each user access key without moving active project records yet.
That gives deployment a safe isolation landing zone while the existing project
routes continue to work from the master database during migration.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.saas_admin import UserAccessKey


_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _safe_key_id(value: str) -> str:
    cleaned = _SAFE_PART_RE.sub("_", str(value or "").strip())[:80]
    return cleaned or "unknown"


def _master_sqlite_path(db: Session) -> Path | None:
    try:
        url = db.get_bind().url
        database = str(url.database or "")
    except Exception:
        return None
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser().resolve()


def tenant_database_root(db: Session) -> Path | None:
    """Return the root directory for per-key tenant SQLite files."""
    explicit_root = os.getenv("MOXI_TENANT_DB_ROOT", "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()
    master = _master_sqlite_path(db)
    if master is None:
        return None
    return master.parent / "tenant-dbs"


def tenant_database_path(db: Session, access_key_id: str) -> Path | None:
    root = tenant_database_root(db)
    if root is None:
        return None
    return root / _safe_key_id(access_key_id) / "tenant.db"


def _load_tenant_metadata() -> None:
    """Import user-data models so Base.metadata can create the tenant schema."""
    from app.models import (  # noqa: F401
        activity_log,
        admin_session,
        admin_user,
        agent,
        auto_fix,
        episode_segment,
        collaboration,
        compliance,
        evidence,
        character_visual,
        issue_record,
        knowledge_chunk,
        legal_assets,
        material_item,
        module,
        outline_job,
        patrol_record,
        project_learning,
        project_v2,
        request_log,
        review_record,
        reward_log,
        rule,
        rule_quality,
        saas_admin,
        skill_registry,
        short_drama_generation_job,
        step_version,
        storyboard,
        sub_task,
        task,
    )


def _create_tenant_schema(db_path: Path) -> None:
    from app.database import Base, configure_sqlite_connection

    _load_tenant_metadata()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    try:
        with engine.connect() as conn:
            configure_sqlite_connection(conn.connection, enable_wal=True)
        Base.metadata.create_all(bind=engine)
    finally:
        engine.dispose()


def ensure_access_key_tenant_database(db: Session, row: UserAccessKey) -> None:
    """Ensure the key has a tracked, ready tenant DB file.

    In-memory test databases intentionally skip file creation but still keep the
    application flow alive. For real SQLite deployments, failures are recorded
    on the key row instead of breaking login, because losing access to existing
    projects would be worse than temporarily falling back to the master DB.
    """
    if row is None or not getattr(row, "id", ""):
        return
    path = tenant_database_path(db, row.id)
    if path is None:
        return

    try:
        _create_tenant_schema(path)
        row.tenant_db_path = str(path)
        row.tenant_storage_status = "ready"
        row.tenant_storage_updated_at = datetime.now()
    except Exception:
        row.tenant_storage_status = "error"
        row.tenant_storage_updated_at = datetime.now()


def delete_access_key_tenant_database(db: Session, row: UserAccessKey) -> bool:
    """Delete the tracked tenant DB for a removed access key.

    The stored path is never trusted directly. We recompute the expected
    per-key location and only delete inside the configured tenant root.
    """
    if row is None or not getattr(row, "id", ""):
        return False
    root = tenant_database_root(db)
    expected_path = tenant_database_path(db, row.id)
    if root is None or expected_path is None:
        return False

    root = root.expanduser().resolve()
    expected_path = expected_path.expanduser().resolve()
    if expected_path == root or root not in expected_path.parents:
        return False

    deleted = False
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{expected_path}{suffix}")
        if candidate.exists():
            candidate.unlink()
            deleted = True
    try:
        parent = expected_path.parent
        if parent.exists() and parent != root and root in parent.parents:
            shutil.rmtree(parent)
            deleted = True
    except OSError:
        pass

    row.tenant_storage_status = "deleted"
    row.tenant_storage_updated_at = datetime.now()
    return deleted
