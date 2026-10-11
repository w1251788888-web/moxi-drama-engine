from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def admin_session_db(tmp_path):
    from app.models.admin_session import AdminSession  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin-session.db'}",
        connect_args={"check_same_thread": False},
    )
    AdminSession.__table__.create(bind=engine, checkfirst=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        AdminSession.__table__.drop(bind=engine, checkfirst=True)


def test_admin_token_expires_and_is_removed(admin_session_db, monkeypatch):
    from app.models.admin_session import AdminSession
    from app.routers.admin import create_admin_token, is_valid_admin_token

    monkeypatch.setenv("MOXI_ADMIN_SESSION_TTL_MINUTES", "1")
    token = create_admin_token(admin_session_db)
    row = admin_session_db.query(AdminSession).filter(AdminSession.token == token).one()
    row.last_used_at = datetime.now() - timedelta(minutes=2)
    admin_session_db.commit()

    assert is_valid_admin_token(token, admin_session_db) is False
    assert admin_session_db.query(AdminSession).filter(AdminSession.token == token).first() is None


def test_admin_token_refreshes_last_used_before_expiry(admin_session_db, monkeypatch):
    from app.models.admin_session import AdminSession
    from app.routers.admin import create_admin_token, is_valid_admin_token

    monkeypatch.setenv("MOXI_ADMIN_SESSION_TTL_MINUTES", "30")
    token = create_admin_token(admin_session_db)
    row = admin_session_db.query(AdminSession).filter(AdminSession.token == token).one()
    old_last_used = datetime.now() - timedelta(minutes=10)
    row.last_used_at = old_last_used
    admin_session_db.commit()

    assert is_valid_admin_token(token, admin_session_db) is True
    admin_session_db.refresh(row)
    assert row.last_used_at > old_last_used


def test_cleanup_expired_admin_sessions_keeps_fresh_tokens(admin_session_db, monkeypatch):
    from app.models.admin_session import AdminSession
    from app.routers.admin import cleanup_expired_admin_sessions, create_admin_token

    monkeypatch.setenv("MOXI_ADMIN_SESSION_TTL_MINUTES", "5")
    fresh_token = create_admin_token(admin_session_db)
    stale = AdminSession(
        token="stale-token",
        created_at=datetime.now() - timedelta(minutes=30),
        last_used_at=datetime.now() - timedelta(minutes=30),
    )
    admin_session_db.add(stale)
    admin_session_db.commit()

    deleted = cleanup_expired_admin_sessions(admin_session_db)

    assert deleted == 1
    assert admin_session_db.query(AdminSession).filter(AdminSession.token == "stale-token").first() is None
    assert admin_session_db.query(AdminSession).filter(AdminSession.token == fresh_token).first() is not None


def test_admin_logout_reads_token_from_header(admin_session_db, monkeypatch):
    from app.database import get_db
    from app.main import app
    from app.routers.admin import create_admin_token
    from fastapi.testclient import TestClient

    token = create_admin_token(admin_session_db)

    def override_db():
        yield admin_session_db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.post("/api/admin/logout", headers={"X-Admin-Token": token})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["message"] == "已登出"
