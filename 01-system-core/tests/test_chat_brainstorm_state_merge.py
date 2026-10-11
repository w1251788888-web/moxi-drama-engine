from app.routers.projects._helpers import _merge_workflow_context_patch


LEGACY_CHAT_MIGRATION_SCOPE = "legacy-workflow-context"


def _base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = digits[remainder] + result
    return result or "0"


def _frontend_legacy_message_id(index: int, role: str, content: str) -> str:
    hashed = 2_166_136_261
    encoded = f"{LEGACY_CHAT_MIGRATION_SCOPE}|{index}|{role}|{content}".encode("utf-16-le")
    for offset in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[offset:offset + 2], "little")
        hashed = ((hashed ^ code_unit) * 16_777_619) & 0xFFFFFFFF
    return f"legacy-{_base36(hashed)}"


def _message(message_id: str, content: str, created_at: str) -> dict:
    return {
        "id": message_id,
        "role": "user",
        "content": content,
        "created_at": created_at,
    }


def test_chat_brainstorm_merge_unions_messages_in_either_request_order():
    base = {"chat_brainstorm": {"schema_version": 2, "messages": []}}
    request_a = {
        "chat_brainstorm": {
            "schema_version": 2,
            "messages": [_message("a", "FACT_A", "2026-07-17T00:00:01.000Z")],
            "updated_at": "2026-07-17T00:00:01.000Z",
        }
    }
    request_b = {
        "chat_brainstorm": {
            "schema_version": 2,
            "messages": [_message("b", "FACT_B", "2026-07-17T00:00:02.000Z")],
            "updated_at": "2026-07-17T00:00:02.000Z",
        }
    }

    forward = _merge_workflow_context_patch(_merge_workflow_context_patch(base, request_a), request_b)
    reverse = _merge_workflow_context_patch(_merge_workflow_context_patch(base, request_b), request_a)

    assert {item["id"] for item in forward["chat_brainstorm"]["messages"]} == {"a", "b"}
    assert {item["id"] for item in reverse["chat_brainstorm"]["messages"]} == {"a", "b"}


def test_chat_brainstorm_merge_keeps_server_messages_and_newer_content_and_trace():
    existing = {
        "chat_brainstorm": {
            "schema_version": 2,
            "messages": [_message("same", "较新内容", "2026-07-17T00:00:03.000Z")],
            "last_context_trace": {"created_at": "2026-07-17T00:00:03.000Z", "included_message_ids": ["same"]},
            "updated_at": "2026-07-17T00:00:03.000Z",
        }
    }
    incoming = {
        "chat_brainstorm": {
            "schema_version": 2,
            "messages": [_message("same", "旧内容", "2026-07-17T00:00:01.000Z")],
            "updated_at": "2026-07-17T00:00:01.000Z",
        }
    }

    merged = _merge_workflow_context_patch(existing, incoming)
    state = merged["chat_brainstorm"]
    assert state["messages"] == [_message("same", "较新内容", "2026-07-17T00:00:03.000Z")]
    assert state["last_context_trace"] == existing["chat_brainstorm"]["last_context_trace"]

    preserved = _merge_workflow_context_patch(existing, {"chat_brainstorm": {"schema_version": 2, "messages": []}})
    assert preserved["chat_brainstorm"]["messages"] == existing["chat_brainstorm"]["messages"]


def test_chat_brainstorm_merge_migrates_legacy_messages_before_union_in_both_orders():
    legacy = {"role": "user", "content": "LEGACY_MUST_SURVIVE"}
    v2 = _message("v2-message", "V2_MUST_SURVIVE", "2026-07-17T00:00:08.000Z")
    legacy_state = {"chat_brainstorm": {"messages": [legacy]}}
    v2_state = {"chat_brainstorm": {"schema_version": 2, "messages": [v2]}}

    forward = _merge_workflow_context_patch(legacy_state, v2_state)["chat_brainstorm"]
    reverse = _merge_workflow_context_patch(v2_state, legacy_state)["chat_brainstorm"]

    for merged in (forward, reverse):
        assert {item["content"] for item in merged["messages"]} == {"LEGACY_MUST_SURVIVE", "V2_MUST_SURVIVE"}
        legacy_message = next(item for item in merged["messages"] if item["content"] == "LEGACY_MUST_SURVIVE")
        assert legacy_message["id"].startswith("legacy-")
        assert legacy_message["created_at"] == "2000-01-01T00:00:00.000Z"

    replayed = _merge_workflow_context_patch({"chat_brainstorm": forward}, legacy_state)["chat_brainstorm"]
    assert replayed["messages"] == forward["messages"]


def test_chat_brainstorm_updated_at_uses_latest_state_message_or_trace_timestamp():
    existing = {
        "chat_brainstorm": {
            "updated_at": "2026-07-17T00:00:01.000Z",
            "messages": [_message("old", "旧消息", "2026-07-17T00:00:09.000Z")],
            "last_context_trace": {"created_at": "2026-07-17T00:00:10.000Z"},
        }
    }
    incoming = {
        "chat_brainstorm": {
            "updated_at": "2026-07-17T00:00:02.000Z",
            "messages": [_message("new", "新消息", "2026-07-17T00:00:12.000Z")],
            "last_context_trace": {"created_at": "2026-07-17T00:00:13.000Z"},
        }
    }
    merged = _merge_workflow_context_patch(existing, incoming)["chat_brainstorm"]
    assert merged["updated_at"] == "2026-07-17T00:00:13.000Z"


def test_chat_brainstorm_cross_client_legacy_writeback_keeps_one_legacy_message():
    legacy_content = "LEGACY_CROSS_CLIENT_MUST_NOT_DUPLICATE"
    frontend_migrated = _message(
        _frontend_legacy_message_id(0, "user", legacy_content),
        legacy_content,
        "2000-01-01T00:00:00.000Z",
    )
    incoming = {
        "chat_brainstorm": {
            "schema_version": 2,
            "messages": [
                frontend_migrated,
                _message("new-v2", "NEW_V2_MESSAGE", "2026-07-17T00:00:01.000Z"),
            ],
        }
    }
    backend_legacy = {"chat_brainstorm": {"messages": [{"role": "user", "content": legacy_content}]}}

    merged = _merge_workflow_context_patch(backend_legacy, incoming)["chat_brainstorm"]
    assert [item["content"] for item in merged["messages"]] == [legacy_content, "NEW_V2_MESSAGE"]
    assert merged["messages"][0] == frontend_migrated


def test_chat_brainstorm_same_time_conflict_uses_python_unicode_length():
    existing = {"chat_brainstorm": {"messages": [_message("emoji-tie", "😀", "2026-07-17T00:00:01.000Z")]}}
    incoming = {"chat_brainstorm": {"messages": [_message("emoji-tie", "ab", "2026-07-17T00:00:01.000Z")]}}
    merged = _merge_workflow_context_patch(existing, incoming)["chat_brainstorm"]
    assert merged["messages"][0]["content"] == "ab"
