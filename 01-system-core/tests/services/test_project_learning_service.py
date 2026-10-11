from unittest.mock import MagicMock

from app.models.project_learning import MaterialStatus, ProjectMaterial, UserEditRecord
from app.services.project_learning_service import ProjectLearningService


def test_capture_user_edit_materializes_only_candidate_evidence():
    db = MagicMock()
    service = ProjectLearningService(db)

    result_id = service.capture_user_edit(
        project_id="project-1",
        target_type="segment",
        target_id="segment-1",
        before_content="原始内容",
        after_content="用户改稿后补充了更多动作、对白、情绪和连续性证据。" * 20,
        edit_reason="加强可看性",
        session_id="session-1",
    )

    added = [call[0][0] for call in db.add.call_args_list]
    edit_records = [item for item in added if isinstance(item, UserEditRecord)]
    materials = [item for item in added if isinstance(item, ProjectMaterial)]

    assert len(edit_records) == 1
    assert len(materials) == 1
    assert result_id == edit_records[0].id
    assert edit_records[0].materialized is True
    assert edit_records[0].material_id == materials[0].id
    assert materials[0].status == MaterialStatus.CANDIDATE.value
    assert materials[0].quality_score == 0.0
    assert materials[0].user_rating == 0
    assert "needs_human_review" in materials[0].tags
    db.commit.assert_called_once()


def test_capture_user_edit_does_not_auto_approve_minor_edit():
    db = MagicMock()
    service = ProjectLearningService(db)

    result_id = service.capture_user_edit(
        project_id="project-1",
        target_type="segment",
        target_id="segment-1",
        before_content="原始内容",
        after_content="原始内容小改",
    )

    added = [call[0][0] for call in db.add.call_args_list]
    edit_records = [item for item in added if isinstance(item, UserEditRecord)]
    materials = [item for item in added if isinstance(item, ProjectMaterial)]

    assert result_id == edit_records[0].id
    assert edit_records[0].materialized is False
    assert materials == []
    db.commit.assert_called_once()
