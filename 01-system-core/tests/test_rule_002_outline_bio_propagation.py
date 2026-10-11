from pathlib import Path

from app.services.short_drama_template_vars import build_base_template_vars


ROOT = Path(__file__).resolve().parents[1]


def test_rule_002d_outline_editor_preserves_character_bio_structural_fields():
    source = (ROOT / "webui/src/views/OutlineEditorView.vue").read_text(encoding="utf-8")
    character_interface = source.split("interface CharacterProfile", 1)[1].split("interface EpisodeAnalysis", 1)[0]
    normalize_body = source.split("function normalizeCharacter", 1)[1].split("function normalizeAnalysisResult", 1)[0]
    save_characters_payload = source.split("outline_characters: (normalizedResult.characters || []).map", 1)[1].split("main_chain_committed", 1)[0]

    for field in (
        "voiceprint",
        "inner_need",
        "resource",
        "first_appearance_function",
        "relationship_tension",
        "secret",
    ):
        assert field in character_interface
        assert field in normalize_body
        assert field in save_characters_payload


def test_rule_002d_committed_outline_characters_keep_structured_bio_in_template_vars():
    metadata = {
        "project": {},
        "inputs": {},
        "workflow_context": {
            "outline_state": {
                "main_chain_committed": True,
                "outline_data": {
                    "logline": "何铮在档案室夜审中保护吴雪。",
                    "worldview": "何家档案室用门禁和审批号控制家族权力。",
                    "goldenFinger": "何铮能读懂旧档案里的编号暗线。",
                    "conflict": "沈知行要把吴雪转出档案室。",
                    "episodes": [],
                },
                "outline_characters": [
                    {
                        "name": "何铮",
                        "role": "protagonist",
                        "info": "何家旁支，档案室夜审执行人。",
                        "voiceprint": "短句克制，先问证据再表态。",
                        "inner_need": "需要证明自己不是家族工具。",
                        "resource": "旧档案编号记忆、B2门禁权限。",
                        "arc": "从旁观执行人变成公开保护者。",
                        "first_appearance_function": "第一场用门禁卡救下吴雪。",
                        "relationship_tension": "与沈知行是名义上下级、实际权力竞争。",
                        "secret": "知道何正声当年转出过一份空白报告。",
                    }
                ],
            }
        },
    }

    result = build_base_template_vars(
        metadata,
        draft_episode=1,
        known_template_keys=("characters",),
    )

    characters = result["characters"]
    for expected in (
        "声纹：短句克制，先问证据再表态。",
        "内在需求：需要证明自己不是家族工具。",
        "资源/筹码：旧档案编号记忆、B2门禁权限。",
        "人物弧线：从旁观执行人变成公开保护者。",
        "首次出场功能：第一场用门禁卡救下吴雪。",
        "关系张力：与沈知行是名义上下级、实际权力竞争。",
        "底牌/秘密：知道何正声当年转出过一份空白报告。",
    ):
        assert expected in characters


def test_rule_002d_outline_bio_is_not_reduced_to_plain_info_only():
    metadata = {
        "project": {},
        "inputs": {},
        "workflow_context": {
            "outline_state": {
                "main_chain_committed": True,
                "outline_data": {},
                "outline_characters": [
                    {
                        "name": "吴雪",
                        "role": "supporting",
                        "info": "档案室临时管理员。",
                        "voiceprint": "怕但不软，先说事实。",
                        "inner_need": "想保住母亲留下的档案线索。",
                    }
                ],
            }
        },
    }

    result = build_base_template_vars(metadata, draft_episode=1, known_template_keys=("characters",))
    line = result["characters"]

    assert "档案室临时管理员。" in line
    assert "怕但不软，先说事实。" in line
    assert "想保住母亲留下的档案线索。" in line
    assert line.count("：") >= 3
