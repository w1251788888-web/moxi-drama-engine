"""数据库管理员账号登录。"""
from __future__ import annotations


def test_database_admin_user_can_login(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from app.routers.admin import upsert_admin_user

    original_engine = database.engine
    original_session = database.SessionLocal

    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin_user_login.db'}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from app.models import admin_user  # noqa: F401

    database.engine = engine
    database.SessionLocal = session_local
    database.Base.metadata.create_all(bind=engine)

    try:
        with session_local() as db:
            upsert_admin_user(
                db,
                username="admin_ops_test",
                password="MoxiAdmin-Test-2026!",
                note="pytest admin",
            )

        client = TestClient(app)
        bad = client.post("/api/admin/login", json={"username": "admin_ops_test", "password": "wrong"})
        assert bad.status_code == 403

        ok = client.post(
            "/api/admin/login",
            json={"username": "admin_ops_test", "password": "MoxiAdmin-Test-2026!"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["token"]
    finally:
        database.engine = original_engine
        database.SessionLocal = original_session
