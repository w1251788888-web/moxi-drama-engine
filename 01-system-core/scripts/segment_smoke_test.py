from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.short_drama_writing import (  # noqa: E402
    TestingScriptRequest,
    _evaluate_testing_scene,
    _generate_testing_scene_passed,
    _build_testing_quality_anchor_block,
)


def build_fixture_request(current_content: str = "", segment_id: str = "hook") -> TestingScriptRequest:
    fixture_path = ROOT.parent / "03-project-library" / "新建项目" / "嘉豪测试" / "project.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    characters = []
    for item in (payload.get("characters") or [])[:8]:
        characters.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "role": item.get("role"),
                "info": item.get("info") or item.get("notes") or "",
                "relationships": item.get("relationships") or [],
            }
        )
    selected = [str(item.get("id")) for item in (payload.get("characters") or [])[:3]]
    return TestingScriptRequest(
        project_type="short_drama",
        audience_axis="混合",
        genre_main="其他",
        genre_sub="逆袭",
        episode_count=60,
        episode_minutes=1.5,
        scene_header_style="bracket",
        episode_no=1,
        scene_no=1,
        word_count_min=200,
        word_count_max=360,
        exclude_punctuation_for_count=True,
        enforce_standard_format=True,
        mode="segment",
        segment_id=segment_id,
        current_content=current_content,
        characters=characters,
        selected_character_ids=selected,
        state_cards=payload.get("state_cards") or {},
    )


def main() -> int:
    confirmed = ""
    segments = ["hook", "validation", "explosion", "resolution"]
    print("== four-segment smoke test ==")
    for segment_id in segments:
        req = build_fixture_request(current_content=confirmed, segment_id=segment_id)
        result = _generate_testing_scene_passed(req)
        content = str(result["content"])
        evaluation = _evaluate_testing_scene(req, content, _build_testing_quality_anchor_block(req))
        print(f"\n[{segment_id}] chars={result['char_count_excluding_punctuation']} warnings={len(result['warnings'])}")
        print(f"blocking={evaluation['blocking_issues']}")
        print(f"failure={evaluation['failure_analysis'].model_dump()}")
        print(f"state_card_suggestions={len(evaluation['state_card_suggestions'])}")
        print(content[:240].replace("\n", "\\n"))
        confirmed = confirmed + ("\n\n" if confirmed else "") + content
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
