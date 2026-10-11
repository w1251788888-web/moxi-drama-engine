from scripts.production_smoke_test import workflow_context_roundtrip_matches


def test_workflow_context_smoke_uses_normalized_chat_message_instead_of_stripped_custom_key():
    marker = "smoke-123"
    workflow_context = {
        "outline_state": {"deployment_smoke_marker": marker},
        "chat_brainstorm": {
            "schema_version": 1,
            "messages": [
                {"role": "user", "content": f"部署烟测 {marker}"},
                {"role": "ai", "content": "已收到"},
            ],
        },
    }

    assert workflow_context_roundtrip_matches(workflow_context, marker) is True
    workflow_context["chat_brainstorm"]["messages"][0]["content"] = "部署烟测"
    assert workflow_context_roundtrip_matches(workflow_context, marker) is False


def test_workflow_context_smoke_requires_both_outline_and_chat_evidence():
    marker = "smoke-456"

    assert workflow_context_roundtrip_matches({}, marker) is False
    assert workflow_context_roundtrip_matches({
        "outline_state": {"deployment_smoke_marker": marker},
        "chat_brainstorm": {"messages": []},
    }, marker) is False
