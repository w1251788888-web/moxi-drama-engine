import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_saas_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'saas-admin.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        yield app, TestClient(app), Session
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed_saas_generation_source_materials(Session, project_id: str, *, confirmed_total_episodes: int) -> None:
    from app.models.project_v2 import ProjectV2

    with Session() as db:
        project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
        assert project is not None
        config = project.get_config()
        config["confirmed_total_episodes"] = confirmed_total_episodes
        config["total_episodes"] = confirmed_total_episodes
        project.set_config(config)
        workspace = Path(project.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
        project_json = workspace / "project.json"
        payload = json.loads(project_json.read_text(encoding="utf-8") or "{}") if project_json.exists() else {}
        payload["characters"] = [{"name": "backend-character"}]
        payload["workflow_context"] = {
            "outline_state": {"source": "backend-outline-state"},
            "materials": [{"id": "material-1"}],
        }
        payload["state_cards"] = {"episode_1": {"status": "ready"}}
        project_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        db.add(project)
        db.commit()


def test_admin_login_accepts_username_and_password(monkeypatch, isolated_saas_client):
    from app.config import config

    _, client, _ = isolated_saas_client
    monkeypatch.setattr(config, "verify_admin_password", lambda password: password == "900236")

    resp = client.post("/api/admin/login", json={"username": "admin", "password": "900236"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["token"]


def test_credit_charge_uses_five_times_actual_ai_cost():
    from app.services.saas_billing_service import calculate_billable_credit, estimate_generation_actual_cost_cny

    result = calculate_billable_credit(Decimal("0.36"))

    assert result.actual_cost_cny == Decimal("0.36")
    assert result.multiplier == Decimal("5")
    assert result.credit_amount == Decimal("1.80")
    assert estimate_generation_actual_cost_cny(prompt_tokens=0, completion_tokens=0) == Decimal("0.01")
    assert estimate_generation_actual_cost_cny(
        prompt_tokens=100,
        completion_tokens=50,
        input_cost_per_1k=Decimal("1.00"),
        output_cost_per_1k=Decimal("2.00"),
    ) == Decimal("0.20")


def test_user_access_key_login_returns_credit_and_advanced_flag():
    from app.services.saas_access_service import create_access_key, login_with_access_key

    issued = create_access_key(
        owner_name="内测用户A",
        initial_credit=Decimal("99"),
        advanced_generation_enabled=True,
        allow_copy_export=True,
    )
    session = login_with_access_key(issued.plain_key)

    assert issued.plain_key.startswith("MOXI-")
    assert session.owner_name == "内测用户A"
    assert session.credit_balance == Decimal("99.00")
    assert session.advanced_generation_enabled is True
    assert session.allow_copy_export is True


def test_admin_feature_gate_controls_advanced_generation_for_key():
    from app.services.saas_access_service import (
        create_access_key,
        set_advanced_generation_enabled,
        set_copy_export_enabled,
    )

    issued = create_access_key(owner_name="普通用户", initial_credit=Decimal("10"))
    disabled = set_advanced_generation_enabled(issued.key_id, False)
    enabled = set_advanced_generation_enabled(issued.key_id, True)
    copy_disabled = set_copy_export_enabled(issued.key_id, False)
    copy_enabled = set_copy_export_enabled(issued.key_id, True)

    assert disabled.advanced_generation_enabled is False
    assert enabled.advanced_generation_enabled is True
    assert copy_disabled.allow_copy_export is False
    assert copy_enabled.allow_copy_export is True


def test_saas_admin_access_key_endpoints_are_admin_only(isolated_saas_client):
    from app.auth.dependencies import verify_admin

    app, client, _ = isolated_saas_client
    blocked = client.post("/api/moxi-admin/access-keys", json={"owner_name": "用户A"})
    assert blocked.status_code == 403

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/access-keys",
            json={"owner_name": "用户A", "initial_credit": 99, "advanced_generation_enabled": False},
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["plain_key"].startswith("MOXI-")
        assert payload["credit_balance"] == 99
        assert payload["advanced_generation_enabled"] is False
        assert payload["allow_copy_export"] is False

        toggled = client.put(
            f"/api/moxi-admin/access-keys/{payload['key_id']}/advanced-generation",
            json={"enabled": True},
        )
        assert toggled.status_code == 200, toggled.text
        assert toggled.json()["advanced_generation_enabled"] is True

        copy_toggled = client.put(
            f"/api/moxi-admin/access-keys/{payload['key_id']}/copy-export",
            json={"enabled": True},
        )
        assert copy_toggled.status_code == 200, copy_toggled.text
        assert copy_toggled.json()["allow_copy_export"] is True
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_front_user_access_key_login_endpoint_returns_safe_session(isolated_saas_client):
    from app.auth.dependencies import verify_admin

    app, client, _ = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/access-keys",
            json={
                "owner_name": "用户B",
                "initial_credit": 20,
                "advanced_generation_enabled": True,
                "allow_copy_export": True,
            },
        )
        assert created.status_code == 200, created.text
        resp = client.post("/api/user/access-key/login", json={"access_key": created.json()["plain_key"]})
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["owner_name"] == "用户B"
    assert payload["credit_balance"] == 20
    assert payload["advanced_generation_enabled"] is True
    assert payload["allow_copy_export"] is True
    assert payload["session_token"].startswith("MXS-")
    assert payload["session_expires_at"]
    assert "plain_key" not in payload


def test_front_user_session_can_check_ai_health_for_storyboard_panel(monkeypatch, isolated_saas_client):
    from app.auth.dependencies import verify_admin
    import app.routers.ai_health as ai_health_router

    app, client, _ = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/access-keys",
            json={
                "owner_name": "分镜页普通用户",
                "initial_credit": 20,
                "advanced_generation_enabled": True,
                "allow_copy_export": True,
            },
        )
        assert created.status_code == 200, created.text
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    login = client.post("/api/user/access-key/login", json={"access_key": created.json()["plain_key"]})
    assert login.status_code == 200, login.text
    monkeypatch.setattr(
        ai_health_router,
        "check_llm_reachable",
        lambda timeout_seconds=5.0: {"ok": True, "detail": "ok", "latency_ms": 1},
    )

    resp = client.get(
        "/api/admin/ai/health",
        headers={"X-User-Session": login.json()["session_token"]},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_front_user_session_can_use_storyboard_routes_for_owned_project(monkeypatch, isolated_saas_client):
    from uuid import uuid4

    from app.auth.dependencies import verify_admin
    from app.models.storyboard import Shot
    import app.routers.storyboard as storyboard_router
    from app.services.saas_access_service import create_access_key

    app, client, Session = isolated_saas_client
    with Session() as db:
        user = create_access_key(owner_name="分镜普通项目用户", initial_credit=20, db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"分镜普通用户项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    with Session() as db:
        shot = Shot(
            project_id=project_id,
            episode=1,
            shot_order=1,
            spec_json='{"shot_id":"shot-1","order":1,"duration_sec":3,"camera":{"shot_size":"MS","angle":"eye","movement":"static"}}',
        )
        db.add(shot)
        db.commit()
        db.refresh(shot)
        shot_id = shot.id

    list_resp = client.get(
        "/api/storyboard/list",
        params={"project_id": project_id, "episode": 1},
        headers=headers,
    )

    assert list_resp.status_code == 200, list_resp.text
    assert len(list_resp.json()["items"]) == 1

    async def fake_plan_shots(*_args, **_kwargs):
        return {"ok": True, "shots": [], "rag_used": False, "elapsed_ms": 1, "msg": "ok"}

    monkeypatch.setattr(storyboard_router.sb_svc, "plan_shots", fake_plan_shots)
    plan_resp = client.post(
        "/api/storyboard/plan",
        json={"project_id": project_id, "session_id": project_id, "episode": 1},
        headers=headers,
    )

    assert plan_resp.status_code == 200, plan_resp.text
    assert plan_resp.json()["ok"] is True
    compile_resp = client.post(
        "/api/storyboard/compile",
        json={"shot_id": shot_id, "platforms": ["generic"]},
        headers=headers,
    )
    assert compile_resp.status_code == 200, compile_resp.text
    assert compile_resp.json()["packs"][0]["platform"] == "generic"
    prompts_resp = client.get(
        "/api/storyboard/prompts",
        params={"shot_id": shot_id},
        headers=headers,
    )
    assert prompts_resp.status_code == 200, prompts_resp.text
    assert len(prompts_resp.json()["items"]) == 1
    assert verify_admin not in app.dependency_overrides


def test_legal_assets_count_short_drama_generation_jobs_as_ai_work(isolated_saas_client):
    from uuid import uuid4

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_saas_client
    with Session() as db:
        user = create_access_key(owner_name="法律资产短剧任务用户", initial_credit=20, db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"法律资产短剧项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id=f"legal-short-drama-job-{uuid4().hex[:8]}",
            project_id=project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="candidate_review_required",
            episode_no=1,
            scene_no=1,
            public_message="已生成候选稿，但需要你确认修改后保存。",
            public_progress=100,
        ))
        db.commit()

    matrix_resp = client.get(f"/api/v2/projects/{project_id}/legal-assets/matrix", headers=headers)
    assert matrix_resp.status_code == 200, matrix_resp.text
    ai_item = next(item for item in matrix_resp.json()["system_generated"] if item["material_type"] == "ai_creation_statement")
    assert ai_item["status"] == "ready"
    assert ai_item["detail"] == "AI 任务 1 次"

    statement_resp = client.get(f"/api/v2/projects/{project_id}/legal-assets/ai-statement", headers=headers)
    assert statement_resp.status_code == 200, statement_resp.text
    statement = statement_resp.json()["content"]
    assert "短剧科研链路 / candidate_review_required" in statement
    assert "当前未记录到 AI 生成任务。" not in statement


def test_front_user_register_consumes_invite_and_returns_session(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import FrontUser, InviteCode, UserAccessKey

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 1, "batch_name": "注册测试", "max_uses": 1, "note": "注册链路验收"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert created.status_code == 200, created.text
    plain_code = created.json()["items"][0]["plain_code"]

    registered = client.post(
        "/api/user/register",
        json={
            "username": "invite_user",
            "password": "passw0rd",
            "invite_code": plain_code,
            "email": "invite-user@example.com",
        },
    )
    assert registered.status_code == 200, registered.text
    payload = registered.json()
    assert payload["front_user_id"]
    assert payload["plain_key"].startswith("MOXI-")
    assert payload["session_token"].startswith("MXS-")
    assert payload["credit_balance"] == 10

    reused = client.post(
        "/api/user/register",
        json={"username": "invite_user_2", "password": "passw0rd", "invite_code": plain_code},
    )
    assert reused.status_code == 400

    with Session() as db:
        user = db.query(FrontUser).filter(FrontUser.username == "invite_user").first()
        key = db.query(UserAccessKey).filter(UserAccessKey.id == payload["key_id"]).first()
        invite = db.query(InviteCode).filter(InviteCode.code_prefix == plain_code[:18]).first()
        assert user and user.access_key_id == payload["key_id"]
        assert invite is not None
        assert user.invite_code_id == invite.id
        assert user.password_hash.startswith("sha256$")
        assert key and key.front_user_id == user.id
        assert invite and invite.status == "used"
        assert invite.used_count == 1


def test_front_user_account_login_uses_registered_user_password(isolated_saas_client):
    from app.auth.dependencies import verify_admin

    app, client, _ = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 1, "batch_name": "账号登录", "max_uses": 1},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert created.status_code == 200, created.text
    plain_code = created.json()["items"][0]["plain_code"]
    registered = client.post(
        "/api/user/register",
        json={
            "username": "account_user",
            "password": "passw0rd",
            "invite_code": plain_code,
            "email": "account-user@example.com",
        },
    )
    assert registered.status_code == 200, registered.text

    logged_in = client.post(
        "/api/user/account/login",
        json={"username": "account_user", "password": "passw0rd"},
    )
    email_login = client.post(
        "/api/user/account/login",
        json={"username": "account-user@example.com", "password": "passw0rd"},
    )
    wrong = client.post(
        "/api/user/account/login",
        json={"username": "account_user", "password": "wrong-pass"},
    )

    assert logged_in.status_code == 200, logged_in.text
    assert email_login.status_code == 200, email_login.text
    payload = logged_in.json()
    assert payload["key_id"] == registered.json()["key_id"]
    assert payload["session_token"].startswith("MXS-")
    assert "plain_key" not in payload
    assert wrong.status_code == 403


def test_invite_registration_session_reaches_project_api_and_safe_admin_listing(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import FrontUser, FrontUserSession, OperatorAuditLog, UserAccessKey

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        invite_resp = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 1, "batch_name": "握手链路", "max_uses": 1, "note": "前后端DB联动"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert invite_resp.status_code == 200, invite_resp.text
    registered = client.post(
        "/api/user/register",
        json={
            "username": "handshake_user",
            "password": "passw0rd",
            "invite_code": invite_resp.json()["items"][0]["plain_code"],
            "email": "handshake@example.com",
            "phone": "13900000001",
        },
    )
    assert registered.status_code == 200, registered.text
    session_payload = registered.json()
    headers = {"X-User-Session": session_payload["session_token"]}

    projects = client.get("/api/v2/projects/", headers=headers)
    assert projects.status_code == 200, projects.text
    assert projects.json() == []

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        listed = client.get("/api/moxi-admin/front-users", params={"keyword": "handshake"})
        disabled = client.put(
            f"/api/moxi-admin/front-users/{session_payload['front_user_id']}",
            json={"status": "disabled"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert listed.status_code == 200, listed.text
    listed_items = listed.json()["items"]
    assert len(listed_items) == 1
    listed_user = listed_items[0]
    assert listed_user["username"] == "handshake_user"
    assert listed_user["key_status"] == "active"
    assert listed_user["credit_balance"] == 10
    assert "plain_key" not in listed_user
    assert "plain_password" not in listed_user
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["key_status"] == "disabled"

    blocked_projects = client.get("/api/v2/projects/", headers=headers)
    assert blocked_projects.status_code == 403

    with Session() as db:
        user = db.query(FrontUser).filter(FrontUser.username == "handshake_user").first()
        key = db.query(UserAccessKey).filter(UserAccessKey.id == session_payload["key_id"]).first()
        sessions = db.query(FrontUserSession).filter(FrontUserSession.access_key_id == session_payload["key_id"]).all()
        actions = {item.action for item in db.query(OperatorAuditLog).all()}
        assert user and user.email == "handshake@example.com" and user.phone == "13900000001"
        assert key and key.front_user_id == user.id and key.status == "disabled"
        assert sessions and all(item.status == "disabled" for item in sessions)
        assert {"invite_code.create_batch", "user.register", "front_user.update"} <= actions


def test_invite_registered_user_can_complete_project_workspace_mainline(
    tmp_path,
    monkeypatch,
    isolated_saas_client,
):
    import json
    from pathlib import Path
    from uuid import uuid4

    from app.auth.dependencies import verify_admin
    from app.models.project_v2 import ContentVersion, ProjectV2
    from app.routers.projects import _helpers as project_helpers

    app, client, Session = isolated_saas_client
    workspace_root = tmp_path / "front-user-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        invite_resp = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 2, "batch_name": "前台主链路", "max_uses": 1, "note": "真实用户工作区验收"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert invite_resp.status_code == 200, invite_resp.text
    invite_codes = [item["plain_code"] for item in invite_resp.json()["items"]]
    user_suffix = uuid4().hex[:8]
    registered = client.post(
        "/api/user/register",
        json={
            "username": f"workspace_user_{user_suffix}",
            "password": "passw0rd",
            "invite_code": invite_codes[0],
            "email": f"workspace-{user_suffix}@example.com",
        },
    )
    other_registered = client.post(
        "/api/user/register",
        json={
            "username": f"workspace_other_{user_suffix}",
            "password": "passw0rd",
            "invite_code": invite_codes[1],
        },
    )
    assert registered.status_code == 200, registered.text
    assert other_registered.status_code == 200, other_registered.text
    session_payload = registered.json()
    headers = {"X-User-Session": session_payload["session_token"]}
    other_headers = {"X-User-Session": other_registered.json()["session_token"]}

    empty_projects = client.get("/api/v2/projects/", headers=headers)
    assert empty_projects.status_code == 200, empty_projects.text
    assert empty_projects.json() == []

    project_name = f"前台真实链路-{user_suffix}"
    created = client.post(
        "/api/v2/projects/",
        json={
            "name": project_name,
            "description": "注册用户从前台创建的短剧项目",
            "project_type": "真人短剧-女频",
            "audience_axis": "女频",
            "genre_main": "都市",
            "genre_sub": "逆袭",
            "config": {
                "total_episodes": 3,
                "episode_seconds": 90,
                "word_count_per_episode": "1080-1320",
                "advanced_generation_mode": True,
                "advanced_generation_profile_id": "short_drama",
            },
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project = created.json()
    project_id = project["id"]
    assert project["workspace_path"].startswith(str(workspace_root))
    project_workspace = Path(project["workspace_path"])
    assert project_workspace.parent.name == session_payload["key_id"]
    assert project_workspace.parent.parent.name == "users"

    listed = client.get("/api/v2/projects/", headers=headers)
    blocked_list = client.get("/api/v2/projects/", headers=other_headers)
    blocked_detail = client.get(f"/api/v2/projects/{project_id}", headers=other_headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == project_id for item in listed.json())
    assert blocked_list.status_code == 200, blocked_list.text
    assert all(item["id"] != project_id for item in blocked_list.json())
    assert blocked_detail.status_code == 403

    workflow_payload = {
        "workflow_context": {"world_rules": "女频内测身份反转", "conflict_plan": "合同真相逐步揭开"},
        "canon_packet": {"locked_facts": ["女主真实身份暂不公开"]},
        "episode_memory_cards": [{"episode_no": 1, "summary": "女主被误解后拿到关键证据"}],
        "merge": False,
    }
    workflow_resp = client.put(
        f"/api/v2/projects/{project_id}/workflow-context",
        json=workflow_payload,
        headers=headers,
    )
    assert workflow_resp.status_code == 200, workflow_resp.text
    assert workflow_resp.json()["workflow_context"]["world_rules"] == "女频内测身份反转"

    characters_payload = {
        "characters": [
            {"id": "heroine", "name": "林晚", "role": "protagonist", "motivation": "夺回家业"},
            {"id": "rival", "name": "周曼", "role": "antagonist", "motivation": "掩盖真相"},
        ]
    }
    chars_resp = client.put(f"/api/v2/projects/{project_id}/characters", json=characters_payload, headers=headers)
    assert chars_resp.status_code == 200, chars_resp.text
    assert chars_resp.json()["characters"][0]["name"] == "林晚"

    state_payload = {
        "relationship_cards": [{"from": "林晚", "to": "周曼", "state": "公开敌对"}],
        "info_cards": [{"fact": "林晚掌握旧合同", "visibility": "audience_only"}],
        "power_cards": [{"holder": "林晚", "asset": "证据链"}],
        "promise_cards": [{"promise": "第3集揭开身份"}],
        "locked_fact_cards": [{"fact": "旧合同真实有效"}],
    }
    state_resp = client.put(f"/api/v2/projects/{project_id}/state-cards", json=state_payload, headers=headers)
    assert state_resp.status_code == 200, state_resp.text
    assert state_resp.json()["relationship_cards"][0]["state"] == "公开敌对"

    episode_resp = client.post(
        f"/api/v2/projects/{project_id}/episodes",
        json={"title": "第一集", "summary": "女主入局", "status": "draft"},
        headers=headers,
    )
    assert episode_resp.status_code == 200, episode_resp.text

    scene_resp = client.post(
        f"/api/v2/projects/{project_id}/episodes/1/scenes",
        json={"time": "夜", "location_type": "内", "location_name": "会议室", "content": "林晚推门而入。"},
        headers=headers,
    )
    assert scene_resp.status_code == 200, scene_resp.text

    save_resp = client.post(
        f"/api/v2/projects/{project_id}/episodes/1/scenes/1/save",
        json={
            "content": "【夜·内·会议室】\n林晚把旧合同拍在桌上，周曼脸色骤变。",
            "editor_type": "human",
            "editor_id": session_payload["front_user_id"],
            "editor_name": "注册用户",
            "change_note": "前台用户主链路验收保存",
            "create_checkpoint": True,
        },
        headers=headers,
    )
    versions_resp = client.get(f"/api/v2/projects/{project_id}/episodes/1/scenes/1/versions", headers=headers)
    assert save_resp.status_code == 200, save_resp.text
    assert versions_resp.status_code == 200, versions_resp.text
    assert versions_resp.json()[0]["change_note"] == "前台用户主链路验收保存"

    with Session() as db:
        stored = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
        version = db.query(ContentVersion).filter(ContentVersion.project_id == project_id).first()
        assert stored and stored.created_by == session_payload["key_id"]
        assert version and Path(version.content_path).exists()
        project_json = json.loads((Path(stored.workspace_path) / "project.json").read_text(encoding="utf-8"))
        assert project_json["characters"][0]["name"] == "林晚"
        assert project_json["workflow_context"]["world_rules"] == "女频内测身份反转"
        assert project_json["state_cards"]["locked_fact_cards"][0]["fact"] == "旧合同真实有效"

    deleted = client.delete(
        f"/api/v2/projects/{project_id}",
        params={"delete_workspace": True},
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert not Path(project["workspace_path"]).exists()


def test_front_user_short_drama_testing_routes_bill_and_enforce_project_scope(
    tmp_path,
    monkeypatch,
    isolated_saas_client,
):
    from decimal import Decimal
    from uuid import uuid4

    from app.models.saas_admin import CreditLedger, UserAccessKey
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import audit_routes, scene_edit_routes
    from app.schemas.short_drama_writing import (
        BenchmarkAssessment,
        ContinuityAssessment,
        TestingFailureAnalysis,
        TestingScriptAutoFixResponse,
    )
    from app.services import text_generation_service
    from app.services.saas_access_service import create_access_key

    app, client, Session = isolated_saas_client
    workspace_root = tmp_path / "short-drama-testing-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user_a = create_access_key(owner_name="测试页用户A", initial_credit=Decimal("2.00"), db=db)
        user_b = create_access_key(owner_name="测试页用户B", initial_credit=Decimal("2.00"), db=db)

    login_a = client.post("/api/user/access-key/login", json={"access_key": user_a.plain_key})
    login_b = client.post("/api/user/access-key/login", json={"access_key": user_b.plain_key})
    assert login_a.status_code == 200, login_a.text
    assert login_b.status_code == 200, login_b.text
    headers_a = {"X-User-Session": login_a.json()["session_token"]}
    headers_b = {"X-User-Session": login_b.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"短剧测试页扣费-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers_a,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    def record_usage(input_tokens: int = 100, output_tokens: int = 50) -> None:
        text_generation_service._record_usage_metrics({
            "provider": "mock",
            "model": "mock-model",
            "input_tokens": input_tokens,
            "cached_input_tokens": 0,
            "uncached_input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "elapsed_seconds": 0.01,
            "estimated": False,
            "raw_usage": {},
        })

    def fake_generate_text(*_args, **_kwargs):
        record_usage()
        return "强化人物目标\n压缩无效对白"

    def fake_evaluate(*_args, **_kwargs):
        record_usage()
        return {
            "char_count_excluding_punctuation": 18,
            "warnings": [],
            "blocking_issues": [],
            "present_character_ids": ["hero"],
            "health_items": [],
            "relationship_suggestions": [],
            "state_card_suggestions": [],
            "benchmark_assessment": BenchmarkAssessment(score=80, passed=True),
            "continuity_assessment": ContinuityAssessment(score=82, passed=True),
            "failure_analysis": TestingFailureAnalysis(),
            "episode_memory_card": {},
            "canon_packet": {},
        }

    async def fake_rag(*_args, **_kwargs):
        return []

    def fake_run_deep_audit(*_args, **_kwargs):
        return BenchmarkAssessment(score=88, passed=True), ContinuityAssessment(score=86, passed=True)

    def fake_auto_fix(*_args, **_kwargs):
        record_usage()
        return TestingScriptAutoFixResponse(
            success=True,
            content="修复后的短剧片段",
            char_count_excluding_punctuation=8,
        )

    monkeypatch.setattr(scene_edit_routes, "generate_text", fake_generate_text)
    monkeypatch.setattr(audit_routes, "evaluate_testing_scene", fake_evaluate)
    monkeypatch.setattr(audit_routes, "apply_scene_level_gate", lambda _req, evaluation, _contract: evaluation)
    monkeypatch.setattr(audit_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(audit_routes, "run_testing_deep_audit", fake_run_deep_audit)
    monkeypatch.setattr(audit_routes, "auto_fix_testing_script_content", fake_auto_fix)

    suggest = client.post(
        "/api/admin/short-drama/testing/script-scene/suggest",
        json={"project_id": project_id, "scene_content": "林晚推门而入。", "audience_axis": "女频"},
        headers=headers_a,
    )
    patch = client.post(
        "/api/admin/short-drama/testing/script-scene/patch",
        json={
            "project_id": project_id,
            "full_text": "林晚推门而入。",
            "selected_text": "推门而入",
            "instruction": "增强压迫感",
        },
        headers=headers_a,
    )
    validate = client.post(
        "/api/admin/short-drama/testing/script-scene/validate",
        json={"project_id": project_id, "scene_content": "林晚把合同拍在桌上。"},
        headers=headers_a,
    )
    deep_audit = client.post(
        "/api/admin/short-drama/testing/script-scene/deep-audit",
        json={"project_id": project_id, "scene_content": "林晚把合同拍在桌上。"},
        headers=headers_a,
    )
    auto_fix = client.post(
        "/api/admin/short-drama/testing/script-scene/auto-fix",
        json={"project_id": project_id, "scene_content": "林晚把合同拍在桌上。"},
        headers=headers_a,
    )
    blocked = client.post(
        "/api/admin/short-drama/testing/script-scene/suggest",
        json={"project_id": project_id, "scene_content": "越权访问"},
        headers=headers_b,
    )
    missing_project = client.post(
        "/api/admin/short-drama/testing/script-scene/suggest",
        json={"project_id": "", "scene_content": "缺项目"},
        headers=headers_a,
    )

    assert suggest.status_code == 200, suggest.text
    assert patch.status_code == 200, patch.text
    assert validate.status_code == 200, validate.text
    assert deep_audit.status_code == 200, deep_audit.text
    assert auto_fix.status_code == 200, auto_fix.text
    assert blocked.status_code == 403
    assert missing_project.status_code == 403

    with Session() as db:
        success_rows = (
            db.query(CreditLedger)
            .filter(
                CreditLedger.access_key_id == user_a.key_id,
                CreditLedger.event_type == "charge",
                CreditLedger.status == "success",
            )
            .all()
        )
        billed_types = {row.generation_type for row in success_rows}
        stored_user = db.query(UserAccessKey).filter(UserAccessKey.id == user_a.key_id).first()
        assert {
            "testing_scene_suggest",
            "testing_scene_patch",
            "testing_script_validate",
            "testing_script_deep_audit",
            "testing_script_auto_fix",
        } <= billed_types
        assert all(row.amount == Decimal("-0.05") for row in success_rows)
        assert stored_user and stored_user.credit_balance == Decimal("1.75")


def test_front_user_testing_route_charge_failure_does_not_return_ai_patch(
    tmp_path,
    monkeypatch,
    isolated_saas_client,
):
    from decimal import Decimal
    from uuid import uuid4

    from app.models.saas_admin import CreditLedger, UserAccessKey
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_edit_routes
    from app.services import text_generation_service
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_saas_client
    workspace_root = tmp_path / "short-drama-charge-failure-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="余额边界用户", initial_credit=Decimal("0.06"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"扣费失败不暴露结果-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    def expensive_generate_text(*_args, **_kwargs):
        text_generation_service._record_usage_metrics({
            "provider": "mock",
            "model": "expensive-model",
            "input_tokens": 1000,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 1000,
            "output_tokens": 10000,
            "total_tokens": 11000,
            "elapsed_seconds": 0.01,
            "estimated": False,
            "raw_usage": {},
        })
        return "余额不足时不能返回这段替换结果"

    monkeypatch.setattr(scene_edit_routes, "generate_text", expensive_generate_text)

    response = client.post(
        "/api/admin/short-drama/testing/script-scene/patch",
        json={
            "project_id": project_id,
            "full_text": "林晚推门而入。",
            "selected_text": "推门而入",
            "instruction": "写得更贵一点",
        },
        headers=headers,
    )

    assert response.status_code == 402, response.text
    assert "余额不足时不能返回这段替换结果" not in response.text
    with Session() as db:
        stored_user = db.query(UserAccessKey).filter(UserAccessKey.id == user.key_id).first()
        rows = (
            db.query(CreditLedger)
            .filter(CreditLedger.access_key_id == user.key_id, CreditLedger.event_type == "charge")
            .all()
        )
        assert stored_user and stored_user.credit_balance == Decimal("0.06")
        assert any(row.status == "failed" and row.amount == Decimal("0.00") for row in rows)
        assert all(row.status != "success" for row in rows)


def test_testing_script_scene_empty_output_records_failure_without_charge(
    tmp_path,
    monkeypatch,
    isolated_saas_client,
):
    from decimal import Decimal
    from uuid import uuid4

    from app.models.saas_admin import CreditLedger, UserAccessKey
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services import workspace_service
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_saas_client
    workspace_root = tmp_path / "short-drama-empty-output-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(workspace_service, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(workspace_service, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="空正文用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"空正文拦截-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_saas_generation_source_materials(Session, project_id, confirmed_total_episodes=3)

    async def fake_rag(*_args, **_kwargs):
        return []

    def fake_generate_research_chain(*_args, **_kwargs):
        return {
            "content": "",
            "char_count_excluding_punctuation": 0,
            "warnings": [],
            "blocking_issues": [],
            "benchmark_assessment": None,
            "continuity_assessment": None,
            "episode_memory_card": {},
            "canon_packet": {},
        }

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", lambda _req, approved, _contract: approved)

    response = client.post(
        "/api/admin/short-drama/testing/script-scene",
        json={
            "project_id": project_id,
            "brief": "何铮保护吴雪追查实验室真相",
            "episode_summary": "吴雪被追踪，何铮介入。",
        },
        headers=headers,
    )

    assert response.status_code == 502, response.text
    assert "empty_generation" in response.text
    with Session() as db:
        stored_user = db.query(UserAccessKey).filter(UserAccessKey.id == user.key_id).first()
        rows = (
            db.query(CreditLedger)
            .filter(CreditLedger.access_key_id == user.key_id, CreditLedger.event_type == "charge")
            .all()
        )
        assert stored_user and stored_user.credit_balance == Decimal("1.00")
        assert any(row.status == "failed" and row.amount == Decimal("0.00") for row in rows)
        assert all(row.status != "success" for row in rows)
        assert any("未扣费" in row.human_reason for row in rows)


def test_admin_front_user_crud_and_default_seed_preserve_login_boundaries(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import FrontUser, FrontUserSession, UserAccessKey

    app, client, Session = isolated_saas_client

    blocked = client.get("/api/moxi-admin/front-users")
    assert blocked.status_code == 403

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/front-users",
            json={
                "username": "managed_user",
                "password": "passw0rd",
                "email": "managed@example.com",
                "phone": "13800000000",
                "note": "后台创建验收",
                "initial_credit": 42,
                "advanced_generation_enabled": True,
            },
        )
        seeded = client.post("/api/moxi-admin/front-users/seed-defaults")
        seeded_again = client.post("/api/moxi-admin/front-users/seed-defaults")
        listed = client.get("/api/moxi-admin/front-users", params={"keyword": "managed"})
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["username"] == "managed_user"
    assert payload["plain_key"].startswith("MOXI-")
    assert payload["plain_password"] == "passw0rd"
    assert payload["credit_balance"] == 42
    assert payload["advanced_generation_enabled"] is True
    assert listed.status_code == 200, listed.text
    assert any(item["user_id"] == payload["user_id"] for item in listed.json()["items"])
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["total"] == 3
    assert all(item["plain_password"] for item in seeded.json()["items"])
    assert seeded_again.status_code == 200, seeded_again.text
    assert seeded_again.json()["total"] == 3
    assert all(item["plain_password"] is None for item in seeded_again.json()["items"])

    account_login = client.post(
        "/api/user/account/login",
        json={"username": "managed_user", "password": "passw0rd"},
    )
    key_login = client.post("/api/user/access-key/login", json={"access_key": payload["plain_key"]})
    assert account_login.status_code == 200, account_login.text
    assert key_login.status_code == 200, key_login.text

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        disabled = client.put(
            f"/api/moxi-admin/front-users/{payload['user_id']}",
            json={"status": "disabled", "note": "暂停使用"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["key_status"] == "disabled"

    assert client.post(
        "/api/user/account/login",
        json={"username": "managed_user", "password": "passw0rd"},
    ).status_code == 403
    assert client.post("/api/user/access-key/login", json={"access_key": payload["plain_key"]}).status_code == 403

    with Session() as db:
        user = db.query(FrontUser).filter(FrontUser.id == payload["user_id"]).first()
        key = db.query(UserAccessKey).filter(UserAccessKey.id == payload["access_key_id"]).first()
        sessions = db.query(FrontUserSession).filter(FrontUserSession.access_key_id == payload["access_key_id"]).all()
        assert user and user.status == "disabled"
        assert key and key.status == "disabled"
        assert sessions and all(session.status == "disabled" for session in sessions)

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        enabled = client.put(
            f"/api/moxi-admin/front-users/{payload['user_id']}",
            json={"status": "active", "password": "newpassw0rd"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["status"] == "active"
    assert enabled.json()["key_status"] == "active"
    assert client.post(
        "/api/user/account/login",
        json={"username": "managed_user", "password": "newpassw0rd"},
    ).status_code == 200

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        deleted = client.delete(f"/api/moxi-admin/front-users/{payload['user_id']}")
        deleted_list = client.get("/api/moxi-admin/front-users", params={"status": "deleted"})
    finally:
        app.dependency_overrides.pop(verify_admin, None)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"
    assert deleted_list.status_code == 200, deleted_list.text
    assert any(item["user_id"] == payload["user_id"] for item in deleted_list.json()["items"])
    assert client.post(
        "/api/user/account/login",
        json={"username": "managed_user", "password": "newpassw0rd"},
    ).status_code == 403


def test_user_session_refresh_and_default_plan_seed_recover_low_credit(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import SubscriptionPlan

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        seeded = client.post("/api/moxi-admin/subscription-plans/seed-defaults")
        created_key = client.post(
            "/api/moxi-admin/access-keys",
            json={"owner_name": "low_credit_user", "initial_credit": 0.25, "advanced_generation_enabled": False},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["total"] == 3
    assert {item["code"] for item in seeded.json()["items"]} >= {"starter", "creator", "studio"}
    assert created_key.status_code == 200, created_key.text

    login = client.post("/api/user/access-key/login", json={"access_key": created_key.json()["plain_key"]})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    assert client.get("/api/user/session").status_code == 403

    current = client.get("/api/user/session", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["credit_balance"] == 0.25
    assert current.json()["session_token"] == login.json()["session_token"]

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        recharged = client.post(
            f"/api/moxi-admin/access-keys/{created_key.json()['key_id']}/recharge",
            json={"amount": 8, "reason": "低余额恢复验收"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)
    assert recharged.status_code == 200, recharged.text

    refreshed = client.get("/api/user/session", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["credit_balance"] == 8.25

    with Session() as db:
        assert db.query(SubscriptionPlan).count() == 3


def test_subscription_plans_checkout_recharges_user_and_creates_order(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import CreditLedger, PaymentOrder, UserAccessKey

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        saved_plan = client.post(
            "/api/moxi-admin/subscription-plans",
            json={
                "code": "test-pro",
                "name": "测试创作套餐",
                "description": "自动化验收套餐",
                "price_cny": 88,
                "credit_amount": 120,
                "advanced_generation_enabled": True,
                "validity_days": 30,
                "status": "active",
                "sort_order": 5,
            },
        )
        invite_resp = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 1, "batch_name": "订阅测试", "max_uses": 1},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert saved_plan.status_code == 200, saved_plan.text
    assert saved_plan.json()["plan_id"]
    assert invite_resp.status_code == 200, invite_resp.text

    registered = client.post(
        "/api/user/register",
        json={
            "username": "subscribe_user",
            "password": "passw0rd",
            "invite_code": invite_resp.json()["items"][0]["plain_code"],
        },
    )
    assert registered.status_code == 200, registered.text
    headers = {"X-User-Session": registered.json()["session_token"]}

    plans = client.get("/api/user/subscription-plans")
    assert plans.status_code == 200, plans.text
    plan = next(item for item in plans.json()["items"] if item["code"] == "test-pro")

    order = client.post("/api/user/subscription-orders", json={"plan_id": plan["plan_id"]}, headers=headers)
    assert order.status_code == 200, order.text
    payload = order.json()
    assert payload["order_no"].startswith("MOXI-PAY-")
    assert payload["status"] == "paid"
    assert payload["credit_amount"] == 120
    assert payload["credit_balance"] == 130
    assert payload["advanced_generation_enabled"] is True

    user_orders = client.get("/api/user/subscription-orders", headers=headers)
    assert user_orders.status_code == 200, user_orders.text
    assert any(item["order_id"] == payload["order_id"] for item in user_orders.json()["items"])

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        admin_orders = client.get("/api/moxi-admin/payment-orders")
        admin_plans = client.get("/api/moxi-admin/subscription-plans")
    finally:
        app.dependency_overrides.pop(verify_admin, None)
    assert admin_orders.status_code == 200, admin_orders.text
    assert any(item["order_id"] == payload["order_id"] for item in admin_orders.json()["items"])
    assert admin_plans.status_code == 200, admin_plans.text
    assert any(item["code"] == "starter" for item in admin_plans.json()["items"])

    with Session() as db:
        key = db.query(UserAccessKey).filter(UserAccessKey.id == registered.json()["key_id"]).first()
        ledger = (
            db.query(CreditLedger)
            .filter(CreditLedger.access_key_id == registered.json()["key_id"], CreditLedger.generation_type == "subscription")
            .first()
        )
        stored_order = db.query(PaymentOrder).filter(PaymentOrder.id == payload["order_id"]).first()
        assert key and key.credit_balance == Decimal("130.00")
        assert key.advanced_generation_enabled is True
        assert key.expires_at is not None
        assert ledger and ledger.amount == Decimal("120.00")
        assert stored_order and stored_order.front_user_id == key.front_user_id


def test_subscription_pending_order_uses_signed_webhook_before_recharge(isolated_saas_client, monkeypatch):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import CreditLedger, PaymentOrder, UserAccessKey
    from app.services.saas_subscription_service import build_payment_webhook_signature

    app, client, Session = isolated_saas_client
    monkeypatch.setenv("MOXI_PAYMENT_WEBHOOK_SECRET", "test-webhook-secret")

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        saved_plan = client.post(
            "/api/moxi-admin/subscription-plans",
            json={
                "code": "pending-pro",
                "name": "待支付套餐",
                "description": "支付回调验签测试",
                "price_cny": 66,
                "credit_amount": 55,
                "advanced_generation_enabled": False,
                "validity_days": 15,
                "status": "active",
                "sort_order": 6,
            },
        )
        invite_resp = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 1, "batch_name": "待支付订阅", "max_uses": 1},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert saved_plan.status_code == 200, saved_plan.text
    assert invite_resp.status_code == 200, invite_resp.text

    registered = client.post(
        "/api/user/register",
        json={
            "username": "pending_subscribe_user",
            "password": "passw0rd",
            "invite_code": invite_resp.json()["items"][0]["plain_code"],
        },
    )
    assert registered.status_code == 200, registered.text
    headers = {"X-User-Session": registered.json()["session_token"]}

    pending = client.post(
        "/api/user/subscription-orders",
        json={
            "plan_id": saved_plan.json()["plan_id"],
            "checkout_mode": "pending",
            "provider": "mock_gateway",
        },
        headers=headers,
    )
    assert pending.status_code == 200, pending.text
    pending_payload = pending.json()
    assert pending_payload["status"] == "pending"
    assert pending_payload["paid_at"] is None
    assert pending_payload["credit_balance"] is None

    bad_webhook = client.post(
        "/api/user/subscription-orders/webhook/mock",
        json={
            "order_no": pending_payload["order_no"],
            "amount_cny": pending_payload["amount_cny"],
            "provider_trade_no": "MOXI-GW-001",
            "signature": "bad-signature",
        },
    )
    assert bad_webhook.status_code == 400

    with Session() as db:
        key = db.query(UserAccessKey).filter(UserAccessKey.id == registered.json()["key_id"]).first()
        ledger_count = (
            db.query(CreditLedger)
            .filter(
                CreditLedger.access_key_id == registered.json()["key_id"],
                CreditLedger.generation_type == "subscription",
            )
            .count()
        )
        stored_order = db.query(PaymentOrder).filter(PaymentOrder.id == pending_payload["order_id"]).first()
        assert key and key.credit_balance == Decimal("10.00")
        assert ledger_count == 0
        assert stored_order and stored_order.status == "pending"

    signature = build_payment_webhook_signature(
        "test-webhook-secret",
        order_no=pending_payload["order_no"],
        amount_cny=pending_payload["amount_cny"],
        provider_trade_no="MOXI-GW-001",
    )
    paid = client.post(
        "/api/user/subscription-orders/webhook/mock",
        json={
            "order_no": pending_payload["order_no"],
            "amount_cny": pending_payload["amount_cny"],
            "provider_trade_no": "MOXI-GW-001",
            "signature": signature,
        },
    )
    assert paid.status_code == 200, paid.text
    paid_payload = paid.json()
    assert paid_payload["status"] == "paid"
    assert paid_payload["credit_balance"] == 65
    assert paid_payload["paid_at"]

    duplicate = client.post(
        "/api/user/subscription-orders/webhook/mock",
        json={
            "order_no": pending_payload["order_no"],
            "amount_cny": pending_payload["amount_cny"],
            "provider_trade_no": "MOXI-GW-001",
            "signature": signature,
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["credit_balance"] == 65

    with Session() as db:
        key = db.query(UserAccessKey).filter(UserAccessKey.id == registered.json()["key_id"]).first()
        ledger_count = (
            db.query(CreditLedger)
            .filter(
                CreditLedger.access_key_id == registered.json()["key_id"],
                CreditLedger.generation_type == "subscription",
            )
            .count()
        )
        stored_order = db.query(PaymentOrder).filter(PaymentOrder.id == pending_payload["order_id"]).first()
        assert key and key.credit_balance == Decimal("65.00")
        assert key.expires_at is not None
        assert ledger_count == 1
        assert stored_order and stored_order.status == "paid"


def test_operator_audit_tracks_admin_and_user_business_actions(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import OperatorAuditLog

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created_key = client.post(
            "/api/moxi-admin/access-keys",
            json={"owner_name": "审计用户", "initial_credit": 5, "advanced_generation_enabled": False},
        )
        created_invite = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 1, "batch_name": "审计批次", "max_uses": 1},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert created_key.status_code == 200, created_key.text
    assert created_invite.status_code == 200, created_invite.text

    registered = client.post(
        "/api/user/register",
        json={
            "username": "audit_user",
            "password": "passw0rd",
            "invite_code": created_invite.json()["items"][0]["plain_code"],
        },
    )
    assert registered.status_code == 200, registered.text
    account_login = client.post(
        "/api/user/account/login",
        json={"username": "audit_user", "password": "passw0rd"},
    )
    assert account_login.status_code == 200, account_login.text

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        listed = client.get("/api/moxi-admin/operator-audit-logs", params={"limit": 50})
        user_logs = client.get("/api/moxi-admin/operator-audit-logs", params={"actor_type": "user", "limit": 50})
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert listed.status_code == 200, listed.text
    assert user_logs.status_code == 200, user_logs.text
    actions = {item["action"] for item in listed.json()["items"]}
    assert {
        "access_key.create",
        "invite_code.create_batch",
        "user.register",
        "user.login.account",
    } <= actions
    assert all(item["actor_type"] == "user" for item in user_logs.json()["items"])
    assert "plain_key" not in listed.text

    with Session() as db:
        rows = db.query(OperatorAuditLog).all()
        assert len(rows) >= 4
        assert any(row.target_id == created_key.json()["key_id"] for row in rows)


def test_user_session_token_is_persisted_and_verifiable():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.saas_admin import CreditLedger, FrontUserSession, UserAccessKey
    from app.services.saas_access_service import (
        create_access_key,
        login_with_access_key,
        verify_user_session_token,
    )

    engine = create_engine("sqlite:///:memory:")
    for table in (UserAccessKey.__table__, FrontUserSession.__table__, CreditLedger.__table__):
        table.create(engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        issued = create_access_key(owner_name="会话用户", initial_credit=0, db=db)
        session = login_with_access_key(issued.plain_key, db=db)
        assert session.session_token and session.session_token.startswith("MXS-")

        verified = verify_user_session_token(session.session_token, db)
        assert verified.key_id == issued.key_id
        assert verified.owner_name == "会话用户"
        assert db.query(FrontUserSession).count() == 1
    finally:
        db.close()


def test_access_key_gets_dedicated_tenant_database(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.saas_admin import CreditLedger, FrontUserSession, UserAccessKey
    from app.services.saas_access_service import (
        create_access_key,
        login_with_access_key,
        verify_user_session_token,
    )

    master_db = tmp_path / "master.db"
    engine = create_engine(f"sqlite:///{master_db}")
    for table in (UserAccessKey.__table__, FrontUserSession.__table__, CreditLedger.__table__):
        table.create(engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        issued = create_access_key(owner_name="独立库用户", initial_credit=0, db=db)
        row = db.query(UserAccessKey).filter(UserAccessKey.id == issued.key_id).first()
        assert row is not None
        assert row.tenant_storage_status == "ready"
        assert row.tenant_db_path.endswith(f"tenant-dbs/{issued.key_id}/tenant.db")
        assert Path(row.tenant_db_path).exists()

        Path(row.tenant_db_path).unlink()
        session = login_with_access_key(issued.plain_key, db=db)
        verified = verify_user_session_token(session.session_token, db)
        db.refresh(row)

        assert verified.key_id == issued.key_id
        assert row.tenant_storage_status == "ready"
        assert Path(row.tenant_db_path).exists()
    finally:
        db.close()


def test_generation_billing_charges_success_and_records_failed_without_charge():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.saas_admin import CreditLedger, FrontUserSession, UserAccessKey
    from app.services.saas_access_service import (
        charge_access_key_for_generation,
        create_access_key,
        ensure_access_key_can_spend,
        record_generation_failure_without_charge,
    )

    engine = create_engine("sqlite:///:memory:")
    for table in (UserAccessKey.__table__, FrontUserSession.__table__, CreditLedger.__table__):
        table.create(engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        issued = create_access_key(owner_name="扣费用户", initial_credit=Decimal("1.00"), db=db)
        ensure_access_key_can_spend(db, issued.key_id)

        session = charge_access_key_for_generation(
            db,
            issued.key_id,
            prompt_tokens=100,
            completion_tokens=50,
            provider="kimi",
            model="kimi-k2.6",
            generation_type="scene_draft",
            input_cost_per_1k=Decimal("1.00"),
            output_cost_per_1k=Decimal("2.00"),
            billing_multiplier=Decimal("3"),
        )
        assert session.credit_balance == Decimal("0.40")

        record_generation_failure_without_charge(
            db,
            issued.key_id,
            provider="kimi",
            model="kimi-k2.6",
            generation_type="scene_draft",
            reason="上游超时",
        )
        rows = db.query(CreditLedger).order_by(CreditLedger.created_at.asc()).all()
        assert [row.event_type for row in rows] == ["recharge", "charge", "charge"]
        assert rows[1].amount == Decimal("-0.60")
        assert rows[1].status == "success"
        assert rows[2].amount == Decimal("0.00")
        assert rows[2].status == "failed"
        assert rows[2].balance_after == Decimal("0.40")

        row = db.query(UserAccessKey).filter(UserAccessKey.id == issued.key_id).first()
        assert row is not None
        row.expires_at = datetime.now() - timedelta(days=1)
        db.commit()
        with pytest.raises(ValueError, match="密钥"):
            ensure_access_key_can_spend(db, issued.key_id)
    finally:
        db.close()


def test_front_user_project_routes_are_session_scoped(tmp_path, monkeypatch):
    from pathlib import Path
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from app.models import project_v2, saas_admin  # noqa: F401
    from app.models.project_v2 import GenerationJob, ModelProvider, ProjectV2
    from app.models.saas_admin import CreditLedger
    from app.routers.admin import create_admin_token
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key
    from app.services import text_generation_service

    original_engine = database.engine
    original_session = database.SessionLocal
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'user-projects.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace)

    try:
        with database.SessionLocal() as db:
            user_a = create_access_key(owner_name="用户A", initial_credit=1, db=db)
            user_b = create_access_key(owner_name="用户B", initial_credit=0, db=db)
            provider = ModelProvider(
                name=f"mock-provider-{uuid4().hex[:8]}",
                provider_type="mock",
                base_url="https://mock.local/v1",
                api_key="sk-mock",
                default_model="mock-model",
                is_default=True,
                input_cost_cny_per_1k=Decimal("1.00"),
                output_cost_cny_per_1k=Decimal("2.00"),
                billing_multiplier=Decimal("3"),
            )
            provider.set_models(["mock-model"])
            db.add(provider)
            db.commit()

        client = TestClient(app)
        login_a = client.post("/api/user/access-key/login", json={"access_key": user_a.plain_key})
        login_b = client.post("/api/user/access-key/login", json={"access_key": user_b.plain_key})
        assert login_a.status_code == 200, login_a.text
        assert login_b.status_code == 200, login_b.text
        headers_a = {"X-User-Session": login_a.json()["session_token"]}
        headers_b = {"X-User-Session": login_b.json()["session_token"]}

        project_name = f"用户隔离-{uuid4().hex[:8]}"
        created = client.post(
            "/api/v2/projects/",
            json={
                "name": project_name,
                "description": "普通用户项目隔离验收",
                "project_type": "真人短剧-女频",
                "audience_axis": "女频",
                "genre_main": "都市",
                "genre_sub": "逆袭",
                "config": {"total_episodes": 3},
            },
            headers=headers_a,
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]

        with database.SessionLocal() as db:
            stored = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
            assert stored and stored.created_by == user_a.key_id
            workspace_path = Path(stored.workspace_path)
            assert workspace_path.parent.name == user_a.key_id
            assert workspace_path.parent.parent.name == "users"

        duplicate_same_owner = client.post(
            "/api/v2/projects/",
            json={
                "name": project_name,
                "description": "同用户同名项目应被拦截",
                "project_type": "真人短剧-女频",
                "audience_axis": "女频",
                "genre_main": "都市",
                "genre_sub": "逆袭",
                "config": {"total_episodes": 3},
            },
            headers=headers_a,
        )
        assert duplicate_same_owner.status_code == 400

        same_name_other_user = client.post(
            "/api/v2/projects/",
            json={
                "name": project_name,
                "description": "不同用户允许同名项目",
                "project_type": "真人短剧-女频",
                "audience_axis": "女频",
                "genre_main": "都市",
                "genre_sub": "逆袭",
                "config": {"total_episodes": 3},
            },
            headers=headers_b,
        )
        assert same_name_other_user.status_code == 200, same_name_other_user.text
        with database.SessionLocal() as db:
            stored_b = db.query(ProjectV2).filter(ProjectV2.id == same_name_other_user.json()["id"]).first()
            assert stored_b and stored_b.created_by == user_b.key_id
            workspace_path_b = Path(stored_b.workspace_path)
            assert workspace_path_b.parent.name == user_b.key_id
            assert workspace_path_b.parent.parent.name == "users"

        list_a = client.get("/api/v2/projects/", headers=headers_a)
        list_b = client.get("/api/v2/projects/", headers=headers_b)
        assert list_a.status_code == 200, list_a.text
        assert list_b.status_code == 200, list_b.text
        assert any(item["id"] == project_id for item in list_a.json())
        assert all(item["id"] != project_id for item in list_b.json())

        with database.SessionLocal() as db:
            admin_token = create_admin_token(db)
        mixed_headers_b = {
            "X-Admin-Token": admin_token,
            "X-User-Session": login_b.json()["session_token"],
        }
        mixed_list_b = client.get("/api/v2/projects/", headers=mixed_headers_b)
        assert mixed_list_b.status_code == 200, mixed_list_b.text
        assert all(item["id"] != project_id for item in mixed_list_b.json())

        blocked = client.get(f"/api/v2/projects/{project_id}", headers=headers_b)
        anonymous = client.get(f"/api/v2/projects/{project_id}")
        assert blocked.status_code == 403
        assert anonymous.status_code == 403

        episode = client.post(
            f"/api/v2/projects/{project_id}/episodes",
            json={"title": "第一集", "summary": "用户链路", "status": "draft"},
            headers=headers_a,
        )
        assert episode.status_code == 200, episode.text

        def fake_generate_text(*_args, **kwargs):
            text_generation_service._record_usage_metrics({
                "provider": kwargs.get("provider") or "mock",
                "model": kwargs.get("model") or "mock-model",
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "uncached_input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "elapsed_seconds": 0.01,
                "estimated": False,
                "raw_usage": {},
            })
            return "这是普通用户生成任务的结果。"

        monkeypatch.setattr(text_generation_service, "generate_text", fake_generate_text)
        generation = client.post(
            f"/api/v2/projects/{project_id}/generate",
            json={"job_type": "scene_draft", "episode_number": 1, "temperature": 0.4},
            headers=headers_a,
        )
        assert generation.status_code == 200, generation.text
        job_id = generation.json()["job_id"]

        with database.SessionLocal() as db:
            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            ledger = (
                db.query(CreditLedger)
                .filter(CreditLedger.access_key_id == user_a.key_id, CreditLedger.event_type == "charge")
                .order_by(CreditLedger.created_at.desc())
                .first()
            )
            stored_user = db.query(saas_admin.UserAccessKey).filter(saas_admin.UserAccessKey.id == user_a.key_id).first()
            assert job and job.status == "completed"
            assert job.created_by == user_a.key_id
            assert job.prompt_tokens == 100
            assert job.completion_tokens == 50
            assert ledger and ledger.status == "success"
            assert ledger.amount == Decimal("-0.60")
            assert ledger.actual_cost_cny == Decimal("0.2000")
            assert ledger.billing_multiplier == Decimal("3.00")
            assert stored_user and stored_user.credit_balance == Decimal("0.40")
    finally:
        database.engine = original_engine
        database.SessionLocal = original_session


def test_admin_can_list_disable_and_recharge_access_keys(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import FrontUserSession

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/access-keys",
            json={"owner_name": "禁用测试用户", "initial_credit": 10, "advanced_generation_enabled": False},
        )
        assert created.status_code == 200, created.text
        key_id = created.json()["key_id"]

        listed = client.get("/api/moxi-admin/access-keys", params={"keyword": "禁用测试"})
        assert listed.status_code == 200, listed.text
        assert any(item["key_id"] == key_id for item in listed.json()["items"])

        recharged = client.post(
            f"/api/moxi-admin/access-keys/{key_id}/recharge",
            json={"amount": 15, "reason": "人工补额度"},
        )
        assert recharged.status_code == 200, recharged.text
        assert recharged.json()["credit_balance"] == 25

        login = client.post("/api/user/access-key/login", json={"access_key": created.json()["plain_key"]})
        assert login.status_code == 200, login.text
        session_token = login.json()["session_token"]

        disabled = client.put(f"/api/moxi-admin/access-keys/{key_id}/status", json={"status": "disabled"})
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
        assert client.get("/api/user/session", headers={"X-User-Session": session_token}).status_code == 403
        with Session() as db:
            sessions = db.query(FrontUserSession).filter(FrontUserSession.access_key_id == key_id).all()
            assert sessions and all(item.status == "disabled" for item in sessions)

        reenabled = client.put(f"/api/moxi-admin/access-keys/{key_id}/status", json={"status": "active"})
        assert reenabled.status_code == 200, reenabled.text
        assert reenabled.json()["status"] == "active"
        assert client.get("/api/user/session", headers={"X-User-Session": session_token}).status_code == 403

        deleted = client.delete(f"/api/moxi-admin/access-keys/{key_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"
        reactivate_deleted = client.put(f"/api/moxi-admin/access-keys/{key_id}/status", json={"status": "active"})
        assert reactivate_deleted.status_code == 400, reactivate_deleted.text
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_can_create_list_and_disable_invite_codes(isolated_saas_client):
    from app.auth.dependencies import verify_admin

    app, client, _ = isolated_saas_client
    blocked = client.post("/api/moxi-admin/invite-codes", json={"count": 1, "batch_name": "blocked"})
    assert blocked.status_code == 403

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/invite-codes",
            json={"count": 2, "batch_name": "内测批次", "max_uses": 1, "note": "自动化测试"},
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["total"] == 2
        assert payload["items"][0]["plain_code"].startswith("MOXI-INV-")
        invite_id = payload["items"][0]["invite_id"]

        listed = client.get("/api/moxi-admin/invite-codes", params={"batch_name": "内测批次"})
        assert listed.status_code == 200, listed.text
        assert any(item["invite_id"] == invite_id for item in listed.json()["items"])
        assert "plain_code" not in str(listed.json()["items"])

        disabled = client.put(f"/api/moxi-admin/invite-codes/{invite_id}/status", json={"status": "disabled"})
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_llm_provider_masks_encrypted_api_key(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.project_v2 import ModelProvider

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        saved = client.put(
            "/api/moxi-admin/llm-providers/openai",
            json={
                "display_name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test-secret",
                "default_model": "gpt-4o",
                "models": ["gpt-4o", "gpt-4o-mini"],
                "is_active": True,
                "is_default": True,
                "input_cost_cny_per_1k": 0.03,
                "output_cost_cny_per_1k": 0.12,
                "billing_multiplier": 4,
                "minimum_actual_cost_cny": 0.02,
            },
        )
        assert saved.status_code == 200, saved.text
        payload = saved.json()
        assert payload["has_api_key"] is True
        assert payload["input_cost_cny_per_1k"] == 0.03
        assert payload["output_cost_cny_per_1k"] == 0.12
        assert payload["billing_multiplier"] == 4
        assert "sk-test-secret" not in str(payload)

        listed = client.get("/api/moxi-admin/llm-providers")
        assert listed.status_code == 200, listed.text
        assert "sk-test-secret" not in listed.text
        assert any(item["provider"] == "openai" and item["has_api_key"] for item in listed.json()["items"])
        with Session() as db:
            provider = db.query(ModelProvider).filter(ModelProvider.provider_type == "openai").first()
            assert provider and provider.is_default is True
            assert provider.api_key == "sk-test-secret"
            assert provider.input_cost_cny_per_1k == Decimal("0.030000")
            assert provider.output_cost_cny_per_1k == Decimal("0.120000")
            assert provider.billing_multiplier == Decimal("4.00")
            assert provider.minimum_actual_cost_cny == Decimal("0.0200")
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_llm_provider_active_state_is_exclusive(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.project_v2 import ModelProvider
    from app.models.saas_admin import LLMProviderSetting

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        openai = client.put(
            "/api/moxi-admin/llm-providers/openai",
            json={
                "display_name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-openai",
                "default_model": "gpt-4o",
                "models": ["gpt-4o"],
                "is_active": True,
                "is_default": True,
            },
        )
        assert openai.status_code == 200, openai.text

        deepseek = client.put(
            "/api/moxi-admin/llm-providers/deepseek",
            json={
                "display_name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-deepseek",
                "default_model": "deepseek-chat",
                "models": ["deepseek-chat"],
                "is_active": True,
                "is_default": False,
            },
        )
        assert deepseek.status_code == 200, deepseek.text

        listed = client.get("/api/moxi-admin/llm-providers")
        assert listed.status_code == 200, listed.text
        states = {item["provider"]: item["is_active"] for item in listed.json()["items"]}
        assert states["deepseek"] is True
        assert states["openai"] is False
        assert sum(1 for active in states.values() if active) == 1

        with Session() as db:
            setting_states = {
                item.provider: item.is_active
                for item in db.query(LLMProviderSetting).all()
            }
            provider_states = {
                item.provider_type: item.is_active
                for item in db.query(ModelProvider).all()
            }
            assert setting_states["deepseek"] is True
            assert setting_states["openai"] is False
            assert provider_states["deepseek"] is True
            assert provider_states["openai"] is False
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_default_deepseek_metadata_upgrades_legacy_empty_key(isolated_saas_client):
    import json

    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import LLMProviderSetting

    app, client, Session = isolated_saas_client
    with Session() as db:
        db.add(LLMProviderSetting(
            provider="deepseek",
            display_name="DeepSeek",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
            models_json=json.dumps(["deepseek-chat", "deepseek-reasoner"], ensure_ascii=False),
            api_key_encrypted="",
        ))
        db.commit()

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        listed = client.get("/api/moxi-admin/llm-providers")
        assert listed.status_code == 200, listed.text
        deepseek = next(item for item in listed.json()["items"] if item["provider"] == "deepseek")
        assert deepseek["base_url"] == "https://api.deepseek.com"
        assert deepseek["default_model"] == "deepseek-v4-flash"
        assert "deepseek-v4-pro" in deepseek["models"]
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_refreshes_kimi_models_from_upstream(isolated_saas_client, monkeypatch):
    from app.auth.dependencies import verify_admin
    from app.services import saas_admin_query_service

    app, client, _Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True

    class FakeResponse:
        status_code = 200
        text = '{"data":[]}'

        def json(self):
            return {
                "data": [
                    {"id": "kimi-k2.6"},
                    {"id": "moonshot-v1-128k"},
                    {"id": "moonshot-v1-32k"},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert url == "https://api.moonshot.cn/v1/models"
            assert headers["Authorization"] == "Bearer sk-kimi-secret"
            return FakeResponse()

    monkeypatch.setattr(saas_admin_query_service.httpx, "AsyncClient", FakeAsyncClient)

    try:
        saved = client.put(
            "/api/moxi-admin/llm-providers/kimi",
            json={
                "display_name": "Kimi",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key": "sk-kimi-secret",
                "default_model": "moonshot-v1-128k",
                "models": ["moonshot-v1-128k"],
                "is_active": True,
                "is_default": True,
            },
        )
        assert saved.status_code == 200, saved.text

        refreshed = client.post("/api/moxi-admin/llm-providers/kimi/models/refresh")
        assert refreshed.status_code == 200, refreshed.text
        payload = refreshed.json()
        assert payload["provider"] == "kimi"
        assert payload["models"] == ["kimi-k2.6", "moonshot-v1-128k", "moonshot-v1-32k"]
        assert payload["default_model"] == "moonshot-v1-128k"
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_refreshes_deepseek_models_from_upstream(isolated_saas_client, monkeypatch):
    from app.auth.dependencies import verify_admin
    from app.services import saas_admin_query_service

    app, client, _Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True

    class FakeResponse:
        status_code = 200
        text = '{"data":[]}'

        def json(self):
            return {
                "data": [
                    {"id": "deepseek-v4-flash"},
                    {"id": "deepseek-v4-pro"},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert url == "https://api.deepseek.com/models"
            assert headers["Authorization"] == "Bearer sk-deepseek-secret"
            return FakeResponse()

    monkeypatch.setattr(saas_admin_query_service.httpx, "AsyncClient", FakeAsyncClient)

    try:
        saved = client.put(
            "/api/moxi-admin/llm-providers/deepseek",
            json={
                "display_name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-deepseek-secret",
                "default_model": "deepseek-chat",
                "models": ["deepseek-chat"],
                "is_active": True,
                "is_default": True,
            },
        )
        assert saved.status_code == 200, saved.text

        refreshed = client.post("/api/moxi-admin/llm-providers/deepseek/models/refresh")
        assert refreshed.status_code == 200, refreshed.text
        payload = refreshed.json()
        assert payload["provider"] == "deepseek"
        assert payload["models"] == ["deepseek-v4-flash", "deepseek-v4-pro"]
        assert payload["default_model"] == "deepseek-v4-flash"
        assert "sk-deepseek-secret" not in str(payload)
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_can_delete_access_key_from_list(isolated_saas_client):
    from app.auth.dependencies import verify_admin

    app, client, _Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/access-keys",
            json={"owner_name": "可删除密钥", "initial_credit": 1, "advanced_generation_enabled": False},
        )
        assert created.status_code == 200, created.text
        key_id = created.json()["key_id"]
        login = client.post("/api/user/access-key/login", json={"access_key": created.json()["plain_key"]})
        assert login.status_code == 200, login.text
        session_token = login.json()["session_token"]

        deleted = client.delete(f"/api/moxi-admin/access-keys/{key_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"
        assert client.get("/api/user/session", headers={"X-User-Session": session_token}).status_code == 403

        listed = client.get("/api/moxi-admin/access-keys")
        assert listed.status_code == 200, listed.text
        assert key_id not in {item["key_id"] for item in listed.json()["items"]}
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_delete_access_key_cleans_owned_projects_tenant_db_and_sessions(tmp_path, monkeypatch, isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.project_v2 import ProjectV2
    from app.models.saas_admin import FrontUserSession, UserAccessKey
    from app.routers.projects import _helpers as project_helpers

    app, client, Session = isolated_saas_client
    workspace_root = tmp_path / "key-owned-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        created = client.post(
            "/api/moxi-admin/access-keys",
            json={"owner_name": "连库删除用户", "initial_credit": 1, "advanced_generation_enabled": False},
        )
        assert created.status_code == 200, created.text
        key_id = created.json()["key_id"]
        plain_key = created.json()["plain_key"]

        login = client.post("/api/user/access-key/login", json={"access_key": plain_key})
        assert login.status_code == 200, login.text
        session_token = login.json()["session_token"]

        project = client.post(
            "/api/v2/projects/",
            json={"name": "密钥删除联动项目", "config": {"total_episodes": 3}},
            headers={"X-User-Session": session_token},
        )
        assert project.status_code == 200, project.text
        project_id = project.json()["id"]
        workspace_path = Path(project.json()["workspace_path"])

        with Session() as db:
            row = db.query(UserAccessKey).filter(UserAccessKey.id == key_id).first()
            assert row is not None
            tenant_db = Path(row.tenant_db_path)
            assert tenant_db.exists()
            assert db.query(ProjectV2).filter(ProjectV2.id == project_id).count() == 1
            assert db.query(FrontUserSession).filter(FrontUserSession.access_key_id == key_id, FrontUserSession.status == "active").count() >= 1
        assert workspace_path.exists()

        deleted = client.delete(f"/api/moxi-admin/access-keys/{key_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"
        assert client.get("/api/user/session", headers={"X-User-Session": session_token}).status_code == 403

        with Session() as db:
            row = db.query(UserAccessKey).filter(UserAccessKey.id == key_id).first()
            assert row is not None
            assert row.status == "deleted"
            assert row.tenant_storage_status == "deleted"
            assert db.query(ProjectV2).filter(ProjectV2.id == project_id).count() == 0
            assert db.query(FrontUserSession).filter(FrontUserSession.access_key_id == key_id, FrontUserSession.status == "active").count() == 0
        assert not tenant_db.exists()
        assert not workspace_path.exists()
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_secondary_admin_key_can_only_create_plain_user_keys(isolated_saas_client):
    from app.auth.dependencies import verify_admin

    app, client, _Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        secondary = client.post(
            "/api/moxi-admin/access-keys",
            json={
                "owner_name": "二级管理员A",
                "initial_credit": 0,
                "advanced_generation_enabled": False,
                "admin_role": "secondary_admin",
            },
        )
        assert secondary.status_code == 200, secondary.text
        assert secondary.json()["admin_role"] == "secondary_admin"
        plain_key = secondary.json()["plain_key"]
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    login = client.post("/api/user/access-key/login", json={"access_key": plain_key})
    assert login.status_code == 200, login.text
    session_token = login.json()["session_token"]
    assert login.json()["admin_role"] == "secondary_admin"

    created = client.post(
        "/api/moxi-admin/secondary/access-keys",
        headers={"X-User-Session": session_token},
        json={
            "owner_name": "二级管理员生成的普通用户",
            "initial_credit": 3,
            "advanced_generation_enabled": True,
            "admin_role": "secondary_admin",
        },
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["admin_role"] == "user"
    assert payload["advanced_generation_enabled"] is False

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        listed = client.get("/api/moxi-admin/access-keys")
        assert listed.status_code == 200, listed.text
        rows = {item["key_id"]: item for item in listed.json()["items"]}
        assert payload["key_id"] in rows
        assert rows[payload["key_id"]]["plain_key"] == payload["plain_key"]
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    blocked = client.get("/api/moxi-admin/access-keys", headers={"X-User-Session": session_token})
    assert blocked.status_code == 403


def test_admin_advanced_generation_config_persists_role_models(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import AdminFeatureFlag
    from app.services.saas_admin_query_service import ADVANCED_GENERATION_CONFIG_KEY

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        kimi = client.put(
            "/api/moxi-admin/llm-providers/kimi",
            json={
                "display_name": "Kimi",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key": "sk-kimi-secret",
                "default_model": "kimi-k2.6",
                "models": ["kimi-k2.6", "moonshot-v1-128k"],
                "is_active": True,
                "is_default": True,
            },
        )
        assert kimi.status_code == 200, kimi.text

        saved = client.put(
            "/api/moxi-admin/advanced-generation/config",
            json={
                "enabled": True,
                "profile_id": "short_drama",
                "roles": [
                    {
                        "role": "logic",
                        "provider": "deepseek",
                        "model": "deepseek-reasoner",
                        "temperature": 0.25,
                        "duty": "负责结构推理",
                    },
                    {
                        "role": "creative",
                        "provider": "kimi",
                        "model": "kimi-k2.6",
                        "temperature": 0.85,
                        "duty": "负责中文执笔",
                    },
                    {
                        "role": "review",
                        "provider": "claude",
                        "model": "claude-sonnet-4-5",
                        "temperature": 0,
                        "duty": "负责质量评审",
                    },
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        payload = saved.json()
        assert payload["enabled"] is True
        assert payload["roles"][1]["role"] == "creative"
        assert payload["roles"][1]["provider"] == "kimi"
        assert payload["roles"][1]["model"] == "kimi-k2.6"
        assert payload["roles"][1]["has_api_key"] is True
        assert "sk-kimi-secret" not in str(payload)

        listed = client.get("/api/moxi-admin/advanced-generation/config")
        assert listed.status_code == 200, listed.text
        assert listed.json()["roles"][0]["label"] == "逻辑规划模型"

        with Session() as db:
            flag = db.query(AdminFeatureFlag).filter(AdminFeatureFlag.key == ADVANCED_GENERATION_CONFIG_KEY).first()
            assert flag is not None
            assert flag.enabled is True
            assert "负责中文执笔" in flag.note
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_logs_ledgers_and_exceptions_are_real_query_endpoints(isolated_saas_client):
    from app.auth.dependencies import verify_admin
    from app.models.saas_admin import CreditLedger

    app, client, Session = isolated_saas_client
    app.dependency_overrides[verify_admin] = lambda: True
    try:
        with Session() as db:
            db.add(CreditLedger(
                access_key_id="test-exception-key",
                event_type="charge",
                amount=-2,
                balance_after=8,
                actual_cost_cny=0.4,
                billing_multiplier=5,
                provider="kimi",
                model="kimi-k2.6",
                prompt_tokens=100,
                completion_tokens=200,
                generation_type="script",
                status="failed",
                human_reason="AI接口超时，用户本次未扣额度",
            ))
            db.commit()

        ledgers = client.get("/api/moxi-admin/credit-ledger")
        logs = client.get("/api/moxi-admin/generation-logs")
        exceptions = client.get("/api/moxi-admin/exceptions")
        overview = client.get("/api/moxi-admin/overview")

        assert ledgers.status_code == 200, ledgers.text
        assert logs.status_code == 200, logs.text
        assert exceptions.status_code == 200, exceptions.text
        assert overview.status_code == 200, overview.text
        assert any(item["status"] == "failed" for item in exceptions.json()["items"])
        assert "今日生成" in str(overview.json()["cards"])
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_admin_task_and_log_hot_paths_have_page_scoped_stats_and_indexes():
    from pathlib import Path

    from app.models.activity_log import ActivityLog
    from app.models.module import Module
    from app.models.sub_task import SubTask
    from app.models.saas_admin import OperatorAuditLog
    from app.models.task import Task

    service_source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "admin_task_query_service.py"
    ).read_text(encoding="utf-8")

    assert "_build_task_stats_subquery(db, task_ids=page_ids)" in service_source
    assert "_build_task_module_count_subquery(db, task_ids=page_ids)" in service_source
    assert "order_position = case(" in service_source
    assert "_build_module_stats_subquery(db, module_ids=page_ids)" in service_source
    assert "_build_module_stats_subquery(db, module_ids=[module_id])" in service_source

    task_indexes = {idx.name for idx in Task.__table__.indexes}
    module_indexes = {idx.name for idx in Module.__table__.indexes}
    sub_task_indexes = {idx.name for idx in SubTask.__table__.indexes}
    log_indexes = {idx.name for idx in ActivityLog.__table__.indexes}
    audit_indexes = {idx.name for idx in OperatorAuditLog.__table__.indexes}

    assert {"ix_task_status_created", "ix_task_status_updated", "ix_task_type_created"} <= task_indexes
    assert {"ix_module_task_created", "ix_module_task_name"} <= module_indexes
    assert {
        "ix_sub_task_task_created",
        "ix_sub_task_task_status_created",
        "ix_sub_task_module_created",
        "ix_sub_task_module_status_created",
        "ix_sub_task_agent_status_created",
    } <= sub_task_indexes
    assert {
        "ix_activity_log_created",
        "ix_activity_log_action_created",
        "ix_activity_log_agent_created",
        "ix_activity_log_sub_task_created",
    } <= log_indexes
    assert {
        "ix_operator_audit_actor_created",
        "ix_operator_audit_action_created",
        "ix_operator_audit_target_created",
        "ix_operator_audit_status_created",
    } <= audit_indexes


def test_admin_task_list_stats_are_scoped_to_current_page():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.agent import Agent
    from app.models.module import Module
    from app.models.sub_task import SubTask
    from app.models.task import Task
    from app.services import admin_task_query_service

    engine = create_engine("sqlite:///:memory:")
    for table in (Agent.__table__, Task.__table__, Module.__table__, SubTask.__table__):
        table.create(engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add_all([
            Task(id="task-1", name="Alpha", description="", status="active"),
            Task(id="task-2", name="Beta", description="", status="completed"),
        ])
        db.flush()
        db.add(Module(id="module-1", task_id="task-1", name="M1"))
        db.add_all([
            SubTask(id="sub-1", task_id="task-1", module_id="module-1", name="S1", status="done"),
            SubTask(id="sub-2", task_id="task-1", module_id="module-1", name="S2", status="blocked"),
        ])
        db.commit()

        page = admin_task_query_service.list_tasks(
            db,
            page=1,
            page_size=1,
            sort_by="name",
            sort_order="asc",
        )

        assert page["total"] == 2
        assert page["has_more"] is True
        assert [item["id"] for item in page["items"]] == ["task-1"]
        assert page["items"][0]["module_count"] == 1
        assert page["items"][0]["sub_task_count"] == 2
        assert page["items"][0]["done_count"] == 1
        assert page["items"][0]["blocked_count"] == 1
    finally:
        db.close()


def test_admin_module_list_stats_are_scoped_to_current_page():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.agent import Agent
    from app.models.module import Module
    from app.models.sub_task import SubTask
    from app.models.task import Task
    from app.services import admin_task_query_service

    engine = create_engine("sqlite:///:memory:")
    for table in (Agent.__table__, Task.__table__, Module.__table__, SubTask.__table__):
        table.create(engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add(Task(id="task-1", name="Alpha", description="", status="active"))
        db.flush()
        db.add_all([
            Module(id="module-1", task_id="task-1", name="Alpha module"),
            Module(id="module-2", task_id="task-1", name="Beta module"),
        ])
        db.add_all([
            SubTask(id="sub-1", task_id="task-1", module_id="module-1", name="S1", status="done"),
            SubTask(id="sub-2", task_id="task-1", module_id="module-1", name="S2", status="blocked"),
            SubTask(id="sub-3", task_id="task-1", module_id="module-2", name="S3", status="pending"),
        ])
        db.commit()

        page = admin_task_query_service.list_task_modules(
            db,
            task_id="task-1",
            page=1,
            page_size=1,
            sort_by="name",
            sort_order="asc",
        )

        assert page["total"] == 2
        assert page["has_more"] is True
        assert [item["id"] for item in page["items"]] == ["module-1"]
        assert page["items"][0]["sub_task_count"] == 2
        assert page["items"][0]["done_count"] == 1
        assert page["items"][0]["blocked_count"] == 1
        assert page["items"][0]["pending_count"] == 0
    finally:
        db.close()
