"""前台项目工作区 AI 聊天鉴权。

守住一个关键产品链路：普通用户进入项目工作区后，AI 脑暴不能误打管理员专用接口。
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal


@contextmanager
def _front_user_ai_chat_session(tmp_path, database_name: str, owner_name: str):
    """建立一位已登录前台用户及其隔离数据库，供聊天协议验收复用。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from app.models import saas_admin  # noqa: F401
    from app.services.saas_access_service import create_access_key, login_with_access_key

    original_engine = database.engine
    original_session = database.SessionLocal
    engine = create_engine(
        f"sqlite:///{tmp_path / database_name}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.engine = engine
    database.SessionLocal = session_local
    database.Base.metadata.create_all(bind=engine)

    client = TestClient(app)
    try:
        with session_local() as db:
            issued = create_access_key(
                owner_name=owner_name,
                initial_credit=Decimal("10"),
                advanced_generation_enabled=True,
                db=db,
            )
            session = login_with_access_key(issued.plain_key, db=db)
        yield client, {"X-User-Session": session.session_token or ""}
    finally:
        client.close()
        database.engine = original_engine
        database.SessionLocal = original_session


def test_compiled_chat_packet_uses_shared_eighteen_thousand_character_budget():
    """前后端必须使用同一 Unicode codepoint 上下文预算。"""
    from app.routers.admin_config import CHAT_CONTEXT_MAX_CHARS

    assert CHAT_CONTEXT_MAX_CHARS == 18_000


def test_front_user_ai_chat_accepts_user_session(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from app.services.saas_access_service import create_access_key, login_with_access_key

    original_engine = database.engine
    original_session = database.SessionLocal

    engine = create_engine(
        f"sqlite:///{tmp_path / 'front_user_ai_chat.db'}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from app.models import (  # noqa: F401
        activity_log,
        admin_session,
        agent,
        auto_fix,
        character_visual,
        episode_segment,
        issue_record,
        material_item,
        module,
        patrol_record,
        project_learning,
        project_v2,
        request_log,
        review_record,
        reward_log,
        rule,
        rule_quality,
        saas_admin,
        step_version,
        storyboard,
        sub_task,
        task,
    )

    database.engine = engine
    database.SessionLocal = session_local
    database.Base.metadata.create_all(bind=engine)

    import app.services.text_generation_service as text_generation_service

    monkeypatch.setattr(text_generation_service, "generation_enabled", lambda: True)
    monkeypatch.setattr(
        text_generation_service,
        "generate_text",
        lambda **_: "前台 AI 已接通",
    )

    try:
        with session_local() as db:
            issued = create_access_key(
                owner_name="前台AI验收用户",
                initial_credit=Decimal("10"),
                advanced_generation_enabled=True,
                db=db,
            )
            session = login_with_access_key(issued.plain_key, db=db)

        client = TestClient(app)
        denied = client.post(
            "/api/admin/config/ai/chat",
            json={"messages": [{"role": "user", "content": "测试"}]},
            headers={"X-User-Session": session.session_token or ""},
        )
        assert denied.status_code == 403

        ok = client.post(
            "/api/user/ai/chat",
            json={"messages": [{"role": "user", "content": "测试"}]},
            headers={"X-User-Session": session.session_token or ""},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["content"] == "前台 AI 已接通"
    finally:
        database.engine = original_engine
        database.SessionLocal = original_session


def test_front_user_ai_chat_preserves_compiled_packet_and_current_message(monkeypatch, tmp_path):
    """聊天上下文包与本轮原话必须一起送入模型，不能再按 6 条历史裁剪。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from app.services.saas_access_service import create_access_key, login_with_access_key

    original_engine = database.engine
    original_session = database.SessionLocal

    engine = create_engine(
        f"sqlite:///{tmp_path / 'front_user_ai_chat_context_packet.db'}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from app.models import (  # noqa: F401
        activity_log,
        admin_session,
        agent,
        auto_fix,
        character_visual,
        episode_segment,
        issue_record,
        material_item,
        module,
        patrol_record,
        project_learning,
        project_v2,
        request_log,
        review_record,
        reward_log,
        rule,
        rule_quality,
        saas_admin,
        step_version,
        storyboard,
        sub_task,
        task,
    )

    database.engine = engine
    database.SessionLocal = session_local
    database.Base.metadata.create_all(bind=engine)

    import app.services.text_generation_service as text_generation_service

    captured_prompts: list[str] = []

    def capture_generate_text(**kwargs):
        captured_prompts.append(kwargs["user_prompt"])
        return "前台 AI 已接通"

    monkeypatch.setattr(text_generation_service, "generation_enabled", lambda: True)
    monkeypatch.setattr(text_generation_service, "generate_text", capture_generate_text)

    try:
        with session_local() as db:
            issued = create_access_key(
                owner_name="上下文完整性验收用户",
                initial_credit=Decimal("10"),
                advanced_generation_enabled=True,
                db=db,
            )
            session = login_with_access_key(issued.plain_key, db=db)

        client = TestClient(app)
        compiled_packet = "\n".join(
            f"用户第{index}轮：FACT_{index}" for index in range(1, 7)
        )
        latest_user_message = "第7轮最新要求：FACT_7"
        response = client.post(
            "/api/user/ai/chat",
            json={
                "context": "chat",
                "chat_context_packet": compiled_packet,
                "messages": [{"role": "user", "content": latest_user_message}],
            },
            headers={"X-User-Session": session.session_token or ""},
        )

        assert response.status_code == 200, response.text
        assert captured_prompts, "模型调用必须收到前台聊天请求"
        assert captured_prompts[-1] == (
            f"{compiled_packet}\n\n【本轮用户要求】\n{latest_user_message}"
        )
        for index in range(1, 8):
            assert f"FACT_{index}" in captured_prompts[-1]
    finally:
        database.engine = original_engine
        database.SessionLocal = original_session


def test_front_user_ai_chat_returns_structured_ai_errors(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from app.services.saas_access_service import create_access_key, login_with_access_key
    from app.services.text_generation_service import TextGenerationRateLimitError

    original_engine = database.engine
    original_session = database.SessionLocal

    engine = create_engine(
        f"sqlite:///{tmp_path / 'front_user_ai_error.db'}",
        connect_args={"check_same_thread": False},
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from app.models import saas_admin  # noqa: F401

    database.engine = engine
    database.SessionLocal = session_local
    database.Base.metadata.create_all(bind=engine)

    import app.services.text_generation_service as text_generation_service

    def raise_rate_limited(**_):
        raise TextGenerationRateLimitError("upstream 429")

    monkeypatch.setattr(text_generation_service, "generation_enabled", lambda: True)
    monkeypatch.setattr(text_generation_service, "generate_text", raise_rate_limited)

    try:
        with session_local() as db:
            issued = create_access_key(owner_name="限流验收用户", initial_credit=10, db=db)
            session = login_with_access_key(issued.plain_key, db=db)

        client = TestClient(app)
        resp = client.post(
            "/api/user/ai/chat",
            json={"messages": [{"role": "user", "content": "测试"}]},
            headers={"X-User-Session": session.session_token or ""},
        )
        assert resp.status_code == 429
        assert resp.json()["error_code"] == "rate_limited"
        assert "限流" in resp.json()["detail"]
    finally:
        database.engine = original_engine
        database.SessionLocal = original_session


def test_front_user_ai_chat_rejects_compiled_packet_over_budget_without_calling_model(monkeypatch, tmp_path):
    """超出统一预算时，接口拒绝请求且不把原文回显给客户端。"""
    import app.services.text_generation_service as text_generation_service

    generated_prompts: list[str] = []
    secret_marker = "PACKET_MUST_NOT_LEAK"

    def capture_generate_text(**kwargs):
        generated_prompts.append(kwargs["user_prompt"])
        return "不应生成"

    monkeypatch.setattr(text_generation_service, "generation_enabled", lambda: True)
    monkeypatch.setattr(text_generation_service, "generate_text", capture_generate_text)

    with _front_user_ai_chat_session(
        tmp_path,
        "front_user_ai_chat_packet_over_budget.db",
        "上下文预算验收用户",
    ) as (client, headers):
        response = client.post(
            "/api/user/ai/chat",
            json={
                "context": "chat",
                "chat_context_packet": secret_marker + "甲" * 18_000,
                "messages": [{"role": "user", "content": "本轮要求"}],
            },
            headers=headers,
        )

    assert response.status_code == 422
    assert "上下文" in response.json()["detail"]
    assert secret_marker not in response.text
    assert generated_prompts == []


def test_front_user_ai_chat_packet_requires_a_final_nonblank_user_message(monkeypatch, tmp_path):
    """新版包只接受最后一条为非空用户原话，防止模型接收歧义轮次。"""
    import app.services.text_generation_service as text_generation_service

    generated_prompts: list[str] = []

    def capture_generate_text(**kwargs):
        generated_prompts.append(kwargs["user_prompt"])
        return "不应生成"

    monkeypatch.setattr(text_generation_service, "generation_enabled", lambda: True)
    monkeypatch.setattr(text_generation_service, "generate_text", capture_generate_text)

    with _front_user_ai_chat_session(
        tmp_path,
        "front_user_ai_chat_packet_invalid_current_message.db",
        "当前轮次验收用户",
    ) as (client, headers):
        for invalid_message in (
            {"role": "assistant", "content": "这不是用户原话"},
            {"role": "user", "content": " \n\t "},
        ):
            response = client.post(
                "/api/user/ai/chat",
                json={
                    "context": "chat",
                    "chat_context_packet": "【边界】测试历史记录",
                    "messages": [invalid_message],
                },
                headers=headers,
            )
            assert response.status_code == 422
            assert "最后一条" in response.json()["detail"] or "不能为空" in response.json()["detail"]

    assert generated_prompts == []


def test_front_user_ai_chat_legacy_request_keeps_six_history_messages(monkeypatch, tmp_path):
    """未带新包的管理员/旧前端调用继续使用原有最近六条历史兼容逻辑。"""
    import app.services.text_generation_service as text_generation_service

    generated_prompts: list[str] = []

    def capture_generate_text(**kwargs):
        generated_prompts.append(kwargs["user_prompt"])
        return "前台 AI 已接通"

    monkeypatch.setattr(text_generation_service, "generation_enabled", lambda: True)
    monkeypatch.setattr(text_generation_service, "generate_text", capture_generate_text)

    with _front_user_ai_chat_session(
        tmp_path,
        "front_user_ai_chat_legacy_history.db",
        "旧协议验收用户",
    ) as (client, headers):
        response = client.post(
            "/api/user/ai/chat",
            json={
                "context": "chat",
                "messages": [
                    *[
                        {"role": "user", "content": f"LEGACY_FACT_{index}"}
                        for index in range(1, 8)
                    ],
                    {"role": "user", "content": "LEGACY_CURRENT"},
                ],
            },
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert generated_prompts
    assert "LEGACY_FACT_1" not in generated_prompts[-1]
    for index in range(2, 8):
        assert f"LEGACY_FACT_{index}" in generated_prompts[-1]
    assert "LEGACY_CURRENT" in generated_prompts[-1]
