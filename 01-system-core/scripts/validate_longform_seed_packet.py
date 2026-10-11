# -*- coding: utf-8 -*-
"""Validate a real longform project seed before import/generation.

The validator checks explicit user/project evidence only. It does not complete
missing fields, does not generate story material, does not score scripts, and
does not produce industrial pass decisions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import import_outline_state_to_longform_workspace as bridge
from scoring_common import atomic_json_dump, now_iso


FRONTMATTER_FIELDS = {
    "title": "项目名称",
    "genre": "题材/赛道",
    "audience": "受众轴",
    "logline": "一句话梗概",
    "worldview": "世界观",
    "golden_finger": "金手指/差异化",
    "conflict": "核心冲突",
}

FRONTMATTER_MIN_LEN = {
    "title": 2,
    "genre": 2,
    "audience": 2,
    "logline": 8,
    "worldview": 8,
    "golden_finger": 1,
    "conflict": 8,
}

CHARACTER_FIELDS = {
    "name": "角色姓名",
    "role": "角色功能",
    "identity": "身份定位",
    "info": "人物小传主体",
    "relationship_to_core_conflict": "与核心冲突的关系",
    "motivation": "行动动机",
    "secret_or_bottom_card": "底牌/秘密",
    "ability_boundary": "能力边界",
    "voiceprint": "声纹/说话方式",
    "inner_need": "内在需求",
    "resource": "资源/筹码",
    "first_appearance_function": "首次出场功能",
    "relationship_tension": "关系张力",
}

CHARACTER_MIN_LEN = {
    "name": 2,
    "role": 2,
    "identity": 6,
    "info": 8,
    "relationship_to_core_conflict": 8,
    "motivation": 8,
    "secret_or_bottom_card": 4,
    "ability_boundary": 4,
    "voiceprint": 8,
    "inner_need": 8,
    "resource": 4,
    "first_appearance_function": 8,
    "relationship_tension": 8,
}

EPISODE_IMPORT_FIELDS = {
    "title": "本集标题",
    "summary": "本集具体事件",
    "conflict": "本集冲突",
    "turning": "转折/爆点",
    "hook": "下一集钩子",
    "main_scene": "主要可拍场景",
    "relationship_change": "关系变化",
    "info_revealed": "信息增量",
    "stage": "本集功能",
}

EPISODE_SMOKE_FIELDS = {
    "start_state": "本集开始状态",
    "end_state": "本集结束状态",
}

PENDING_VALUES = {"", "content_pending", "待补充", "暂无", "未定"}


def _present(value: Any, min_len: int = 2) -> bool:
    text = bridge._text(value)
    if text in PENDING_VALUES:
        return False
    return len(text) >= min_len


def _missing_fields(row: dict[str, Any], field_labels: dict[str, str], min_len: int = 2) -> list[str]:
    return [label for field, label in field_labels.items() if not _present(row.get(field), min_len=min_len)]


def _issue(layer: str, owner: str, field: str, severity: str, message: str) -> dict[str, str]:
    return {
        "layer": layer,
        "owner": owner,
        "field": field,
        "severity": severity,
        "message": message,
    }


def validate_seed_packet(
    snapshot: dict[str, Any],
    *,
    min_episodes: int = 30,
    min_characters: int = 2,
) -> dict[str, Any]:
    created_at = now_iso()
    args = argparse.Namespace(title="", genre="", episode_count=min_episodes)
    series = bridge.resolve_series_fields(snapshot, args)
    explicit_characters = bridge.explicit_characters(snapshot)
    characters = [
        item
        for item in (bridge.normalize_character(raw, index + 1) for index, raw in enumerate(explicit_characters))
        if item.get("name")
    ]
    episodes = [
        item
        for item in (bridge.normalize_episode(raw, index + 1) for index, raw in enumerate(bridge.explicit_episodes(snapshot)))
        if int(item.get("episode_no") or 0) >= 1
    ]
    issues: list[dict[str, str]] = []

    frontmatter = {
        "title": series.get("title"),
        "genre": series.get("genre"),
        "audience": series.get("audience"),
        "logline": series.get("logline"),
        "worldview": series.get("worldview"),
        "golden_finger": series.get("golden_finger"),
        "conflict": series.get("conflict"),
    }
    for field, label in FRONTMATTER_FIELDS.items():
        minimum = FRONTMATTER_MIN_LEN.get(field, 4)
        if not _present(frontmatter.get(field), min_len=minimum):
            issues.append(_issue("frontmatter", "series", field, "critical", f"缺少{label}，不能进入真实长篇工业化种子。"))

    if len(characters) < min_characters:
        issues.append(_issue(
            "characters",
            "character_bible",
            "count",
            "critical",
            f"显式角色数 {len(characters)} 少于最低要求 {min_characters}；不能从对白或剧情动作里猜角色补数。",
        ))
    for character in characters:
        owner = bridge._text(character.get("name")) or "未命名角色"
        for field, label in CHARACTER_FIELDS.items():
            if not _present(character.get(field), min_len=CHARACTER_MIN_LEN.get(field, 4)):
                issues.append(_issue("characters", owner, field, "critical", f"{owner} 缺少{label}。"))
        relationships = character.get("relationships") if isinstance(character.get("relationships"), list) else []
        if not relationships:
            issues.append(_issue("characters", owner, "relationships", "warning", f"{owner} 没有显式人物关系，后续容易关系漂移。"))

    episode_numbers = [int(ep.get("episode_no") or 0) for ep in episodes]
    unique_numbers = sorted(set(number for number in episode_numbers if number > 0))
    duplicate_numbers = sorted(number for number in set(episode_numbers) if episode_numbers.count(number) > 1)
    if len(unique_numbers) < min_episodes:
        issues.append(_issue(
            "episodes",
            "episode_outline",
            "count",
            "critical",
            f"显式集纲数 {len(unique_numbers)} 少于最低要求 {min_episodes}；不能进入 30 集正文生成。",
        ))
    if duplicate_numbers:
        issues.append(_issue(
            "episodes",
            "episode_outline",
            "duplicate_episode_no",
            "critical",
            f"存在重复集号：{duplicate_numbers[:20]}。",
        ))
    missing_numbers = [number for number in range(1, min_episodes + 1) if number not in unique_numbers]
    if missing_numbers:
        issues.append(_issue(
            "episodes",
            "episode_outline",
            "missing_episode_no",
            "critical",
            f"缺少集号：{missing_numbers[:20]}{'...' if len(missing_numbers) > 20 else ''}。",
        ))
    for episode in episodes:
        ep_no = int(episode.get("episode_no") or 0)
        owner = f"ep{ep_no or '?'}"
        for field, label in EPISODE_IMPORT_FIELDS.items():
            if not _present(episode.get(field), min_len=4 if field != "stage" else 2):
                issues.append(_issue("episodes", owner, field, "critical", f"{owner} 缺少{label}。"))
        for field, label in EPISODE_SMOKE_FIELDS.items():
            if not _present(episode.get(field), min_len=4):
                issues.append(_issue("episodes", owner, field, "blocking_smoke", f"{owner} 缺少{label}；可导入账本，但不能开始正文 smoke。"))

    critical = [item for item in issues if item["severity"] == "critical"]
    smoke_blockers = [item for item in issues if item["severity"] in {"critical", "blocking_smoke"}]
    return {
        "event": "validated_longform_seed_packet",
        "created_at": created_at,
        "import_allowed": not critical,
        "script_smoke_allowed": not smoke_blockers,
        "min_episodes": min_episodes,
        "min_characters": min_characters,
        "series": {
            "title": series.get("title"),
            "genre": series.get("genre"),
            "episode_count_target": series.get("episode_count"),
            "audience": series.get("audience"),
        },
        "explicit_character_count": len(characters),
        "explicit_episode_count": len(unique_numbers),
        "critical_issue_count": len(critical),
        "smoke_blocker_count": len(smoke_blockers),
        "warning_count": sum(1 for item in issues if item["severity"] == "warning"),
        "issues": issues,
        "scientific_boundary": "seed validation only; no generation, no human_score, no industrial_pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a real longform project seed packet before import.")
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--min-episodes", type=int, default=30)
    parser.add_argument("--min-characters", type=int, default=2)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    snapshot = bridge.load_snapshot(args.source_json)
    result = validate_seed_packet(
        snapshot,
        min_episodes=args.min_episodes,
        min_characters=args.min_characters,
    )
    if args.output:
        atomic_json_dump(result, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["import_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
