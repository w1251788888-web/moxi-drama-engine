import json
import multiprocessing
import queue
from pathlib import Path

from app.routers.projects._helpers import _merge_workflow_context_patch
from app.services.workspace_service import update_project_json_atomically


def _write_project_field_atomically(workspace: str, barrier, errors, field: str, value) -> None:
    """A second real process updating one non-chat project.json field."""
    try:
        barrier.wait(timeout=10)

        def update_current(project_data: dict) -> dict:
            project_data[field] = value
            project_data["updated_at"] = "2026-07-17T00:00:09.000Z"
            return project_data

        update_project_json_atomically(
            workspace,
            update_current,
            allowed_roots=[Path(workspace).parent],
            create=True,
        )
    except Exception as error:  # pragma: no cover - failure details cross process boundary
        errors.put(repr(error))


def _delete_episode_workspace_state_atomically(workspace: str, barrier, errors, episode_number: int) -> None:
    """Models the delete-episode project.json patch in a competing process."""
    try:
        barrier.wait(timeout=10)

        def update_current(project_data: dict) -> dict:
            workflow_context = project_data.get("workflow_context") if isinstance(project_data.get("workflow_context"), dict) else {}
            progress = workflow_context.get("script_segment_progress")
            if isinstance(progress, dict):
                progress.pop(str(episode_number), None)
                progress.pop(episode_number, None)
            project_data["workflow_context"] = workflow_context
            project_data["episode_memory_cards"] = [
                card for card in project_data.get("episode_memory_cards", [])
                if int(card.get("episode_no") or 0) != episode_number
            ]
            project_data["updated_at"] = "2026-07-17T00:00:09.000Z"
            return project_data

        update_project_json_atomically(
            workspace,
            update_current,
            allowed_roots=[Path(workspace).parent],
            create=True,
        )
    except Exception as error:  # pragma: no cover - failure details cross process boundary
        errors.put(repr(error))


def _workflow_writer(workspace: str, barrier, errors, message_id: str, content: str) -> None:
    try:
        barrier.wait(timeout=10)

        def merge_current(project_data: dict) -> dict:
            existing = project_data.get("workflow_context") if isinstance(project_data.get("workflow_context"), dict) else {}
            project_data["workflow_context"] = _merge_workflow_context_patch(existing, {
                "chat_brainstorm": {
                    "schema_version": 2,
                    "messages": [{
                        "id": message_id,
                        "role": "user",
                        "content": content,
                        "created_at": f"2026-07-17T00:00:0{message_id}.000Z",
                    }],
                },
            })
            return project_data

        update_project_json_atomically(
            workspace,
            merge_current,
            allowed_roots=[Path(workspace).parent],
            create=True,
        )
    except Exception as error:  # pragma: no cover - failure details cross process boundary
        errors.put(repr(error))


def test_project_workflow_context_atomic_update_retains_two_process_writes(tmp_path):
    workspace = tmp_path / "atomic-chat-project"
    workspace.mkdir()
    (workspace / "project.json").write_text(json.dumps({"workflow_context": {"chat_brainstorm": {"messages": []}}}), encoding="utf-8")
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    errors = context.Queue()
    first = context.Process(target=_workflow_writer, args=(str(workspace), barrier, errors, "1", "FACT_A"))
    second = context.Process(target=_workflow_writer, args=(str(workspace), barrier, errors, "2", "FACT_B"))
    first.start()
    second.start()
    first.join(timeout=15)
    second.join(timeout=15)

    assert first.exitcode == 0
    assert second.exitcode == 0
    error_values = []
    while True:
        try:
            error_values.append(errors.get_nowait())
        except queue.Empty:
            break
    assert not error_values, error_values
    project_data = json.loads((workspace / "project.json").read_text(encoding="utf-8"))
    assert {item["content"] for item in project_data["workflow_context"]["chat_brainstorm"]["messages"]} == {"FACT_A", "FACT_B"}


def _join_without_process_errors(*processes_and_errors):
    *processes, errors = processes_and_errors
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    error_values = []
    while True:
        try:
            error_values.append(errors.get_nowait())
        except queue.Empty:
            break
    assert not error_values, error_values


def test_atomic_workflow_and_character_updates_retain_both_fields(tmp_path):
    workspace = tmp_path / "atomic-character-project"
    workspace.mkdir()
    (workspace / "project.json").write_text(json.dumps({"workflow_context": {"chat_brainstorm": {"messages": []}}, "unrelated": "keep"}), encoding="utf-8")
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    errors = context.Queue()
    workflow = context.Process(target=_workflow_writer, args=(str(workspace), barrier, errors, "3", "CHAT_FACT"))
    characters = context.Process(target=_write_project_field_atomically, args=(str(workspace), barrier, errors, "characters", [{"name": "角色甲"}]))
    workflow.start()
    characters.start()
    _join_without_process_errors(workflow, characters, errors)

    project_data = json.loads((workspace / "project.json").read_text(encoding="utf-8"))
    assert project_data["workflow_context"]["chat_brainstorm"]["messages"][0]["content"] == "CHAT_FACT"
    assert project_data["characters"] == [{"name": "角色甲"}]
    assert project_data["unrelated"] == "keep"


def test_atomic_workflow_and_delete_episode_updates_retain_chat_and_prune_only_target_episode(tmp_path):
    workspace = tmp_path / "atomic-delete-project"
    workspace.mkdir()
    (workspace / "project.json").write_text(json.dumps({
        "workflow_context": {"chat_brainstorm": {"messages": []}, "script_segment_progress": {"2": {"status": "old"}, "3": {"status": "keep"}}},
        "episode_memory_cards": [{"episode_no": 2, "text": "delete"}, {"episode_no": 3, "text": "keep"}],
        "unrelated": "keep",
    }), encoding="utf-8")
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    errors = context.Queue()
    workflow = context.Process(target=_workflow_writer, args=(str(workspace), barrier, errors, "4", "CHAT_FACT"))
    deletion = context.Process(target=_delete_episode_workspace_state_atomically, args=(str(workspace), barrier, errors, 2))
    workflow.start()
    deletion.start()
    _join_without_process_errors(workflow, deletion, errors)

    project_data = json.loads((workspace / "project.json").read_text(encoding="utf-8"))
    assert project_data["workflow_context"]["chat_brainstorm"]["messages"][0]["content"] == "CHAT_FACT"
    assert "2" not in project_data["workflow_context"]["script_segment_progress"]
    assert "3" in project_data["workflow_context"]["script_segment_progress"]
    assert project_data["episode_memory_cards"] == [{"episode_no": 3, "text": "keep"}]
    assert project_data["unrelated"] == "keep"


def test_project_json_field_routes_use_the_shared_atomic_update_helper():
    root = Path(__file__).resolve().parents[1]
    stores = (root / "app/routers/projects/routes_stores.py").read_text(encoding="utf-8")
    episodes = (root / "app/routers/projects/routes_episodes_scenes.py").read_text(encoding="utf-8")
    character_route = stores[stores.index("async def save_project_characters"):stores.index("@router.get(\"/{project_id}/state-cards\"")]
    state_cards_route = stores[stores.index("async def save_project_state_cards"):stores.index("@router.get(\"/{project_id}/workflow-context\"")]
    delete_episode_route = episodes[episodes.index("async def delete_episode"):episodes.index("# ============================================================\n# 场景管理API")]

    assert "_update_workspace_project_data_atomically(project, update_current_project_data)" in character_route
    assert "_write_workspace_project_data(project, project_data)" not in character_route
    assert "_update_workspace_project_data_atomically(project, update_current_project_data)" in state_cards_route
    assert "_write_workspace_project_data(project, project_data)" not in state_cards_route
    assert "_update_workspace_project_data_atomically(project, update_current_project_data)" in delete_episode_route
    assert "_write_workspace_project_data(project, project_data)" not in delete_episode_route
