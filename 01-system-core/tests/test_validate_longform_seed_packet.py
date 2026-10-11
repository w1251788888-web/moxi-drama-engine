import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import validate_longform_seed_packet as seed_gate  # noqa: E402


def _character(name: str, role: str):
    return {
        "name": name,
        "role": role,
        "identity": f"{name} 是长篇主线中的明确功能角色。",
        "info": f"{name} 是核心角色，负责制造主线压力和选择。",
        "relationship_to_core_conflict": f"{name} 直接参与证据公开和权力封锁的核心冲突。",
        "motivation": f"{name} 必须通过本轮事件夺回主动权或维持控制权。",
        "secret_or_bottom_card": f"{name} 手里有一项不能提前公开的关键证据或筹码。",
        "ability_boundary": f"{name} 的行动受公开流程、身份权限和证据链完整性限制。",
        "voiceprint": f"{name} 说话短句化，先给动作再给态度。",
        "inner_need": "需要摆脱旧伤并重新夺回主动权。",
        "resource": "掌握关键证据、关系资源和行动入口。",
        "first_appearance_function": "首次出场必须带来危机、选择和关系压力。",
        "relationship_tension": "与主角存在利益绑定和信任裂缝。",
        "relationships": [
            {"targetName": "对方", "type": "对抗", "description": "证据争夺引发关系变化。"}
        ],
    }


def _episode(ep: int, *, with_states: bool = True):
    row = {
        "ep": ep,
        "title": f"第{ep}集标题",
        "summary": f"第{ep}集主角拿到新证据并付出代价，局面不可逆推进。",
        "conflict": "主角要公开证据，对手要封锁证据并制造公开压力。",
        "turning": "证据是真的，但来源指向主角最不愿怀疑的人。",
        "hook": "门外脚步停住，新证据被第三方上传。",
        "main_scene": f"第{ep}集具体场景与压力现场",
        "relationship_change": "试探关系变成短暂结盟，但互不信任。",
        "info_revealed": "本集确认上一集留下的线索不是偶然。",
        "stage": "推进",
    }
    if with_states:
        row["start_state"] = "承接上一集证据未公开、对手仍占上风。"
        row["end_state"] = "本集结束证据被迫公开一半，关系进入新阶段。"
    return row


def _seed(*, episode_count=30, with_states=True):
    return {
        "project": {
            "name": "真实项目测试",
            "project_type": "短剧",
            "audience_axis": "混合",
            "genre_main": "都市悬疑",
            "total_episodes": 30,
        },
        "outline_data": {
            "logline": "主角保护证人并反查家族系统，必须在继承权和真相之间选择。",
            "worldview": "现代都市家族企业与医疗数据系统交织，所有权力动作都有现实代价。",
            "goldenFinger": "无超自然金手指，差异化来自旧系统只读密钥。",
            "conflict": "主角必须公开真相，对手必须封锁证据并清除证人。",
            "audience_axis": "混合",
            "genre_main": "都市悬疑",
            "episodes": [_episode(index, with_states=with_states) for index in range(1, episode_count + 1)],
        },
        "outline_characters": [
            _character("何铮", "protagonist"),
            _character("沈知行", "antagonist"),
        ],
    }


def test_seed_gate_allows_complete_seed_for_import_and_smoke():
    result = seed_gate.validate_seed_packet(_seed())

    assert result["import_allowed"] is True
    assert result["script_smoke_allowed"] is True
    assert result["critical_issue_count"] == 0
    assert result["explicit_episode_count"] == 30


def test_seed_gate_allows_import_but_blocks_smoke_when_continuity_states_missing():
    result = seed_gate.validate_seed_packet(_seed(with_states=False))

    assert result["import_allowed"] is True
    assert result["script_smoke_allowed"] is False
    assert result["critical_issue_count"] == 0
    assert any(issue["field"] == "start_state" for issue in result["issues"])


def test_seed_gate_blocks_short_seed_and_missing_character_hard_fields():
    seed = _seed(episode_count=3)
    seed["outline_characters"][0].pop("voiceprint")

    result = seed_gate.validate_seed_packet(seed)

    assert result["import_allowed"] is False
    assert result["script_smoke_allowed"] is False
    assert result["critical_issue_count"] >= 2
    assert any(issue["field"] == "count" for issue in result["issues"])
    assert any(issue["field"] == "voiceprint" for issue in result["issues"])
