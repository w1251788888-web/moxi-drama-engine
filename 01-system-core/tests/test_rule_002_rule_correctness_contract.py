from pathlib import Path

from app.services.episode_segment_service import EpisodeSegmentService


ROOT = Path(__file__).resolve().parents[2]


def _criteria_text(segment_type: str) -> str:
    segment = EpisodeSegmentService.SEGMENT_DEFINITIONS[segment_type]
    return str(segment.get("acceptance_criteria") or "")


def test_rule_002_hook_acceptance_does_not_use_punctuation_as_suspense_proxy():
    hook_text = _criteria_text("hook")

    assert '"?"' not in hook_text
    assert '"..."' not in hook_text
    assert '"!"' not in hook_text
    assert "可拍未完成动作" in hook_text


def test_rule_002_validation_accepts_state_or_evidence_progress_not_only_power_up():
    validation_text = _criteria_text("validation")

    assert "能力提升" not in validation_text
    assert "证据" in validation_text
    assert "状态变化" in validation_text


def test_rule_002_resolution_requires_unfinished_promise_not_preview_copy():
    resolution = EpisodeSegmentService.SEGMENT_DEFINITIONS["resolution"]
    resolution_text = str(resolution)

    assert "下集预告" not in resolution_text
    assert "未完成承诺" in resolution_text
    assert "具体" in resolution_text
