from app.schemas.short_drama_writing import TestingScriptRequest


def _minimal_req(**overrides):
    payload = {
        "mode": "segment",
        "segment_id": "hook",
        "episode_no": 1,
        "scene_no": 1,
        "episode_title": "测试",
        "episode_summary": "主角当众被逼签字",
        "episode_conflict": "主角被压迫",
        "episode_hook": "证据出现",
        "current_content": "",
        "generation_provider": "kimi",
        "generation_model": "moonshot-v1-128k",
        "word_count_max": 320,
    }
    payload.update(overrides)
    return TestingScriptRequest(**payload)


def test_single_model_scene_generation_uses_original_route(monkeypatch):
    from app.services import short_drama_scene_generation as sg

    calls = []

    def fake_generate_text(system_prompt, user_prompt, **kwargs):
        calls.append(kwargs)
        return "【场1-1：夜 内 客厅】\n△她攥住纸。\n林晚：我不签。"

    def fake_evaluate(req, content, quality_anchor_block):
        return {
            "content": content,
            "blocking_issues": [],
            "quality_passed": True,
            "warnings": [],
            "char_count_excluding_punctuation": 18,
        }

    monkeypatch.setattr(sg, "generate_text", fake_generate_text)
    monkeypatch.setattr(sg, "evaluate_testing_scene", fake_evaluate)

    result = sg.generate_testing_scene_passed(_minimal_req(advanced_generation_mode=False))

    assert result["quality_passed"] is True
    assert calls[0]["provider"] == "kimi"
    assert calls[0]["model"] == "moonshot-v1-128k"


def test_multimodel_scene_generation_splits_writer_and_reviewer_routes(monkeypatch):
    from app.services import short_drama_scene_generation as sg

    writer_calls = []
    reviewer_models = []

    def fake_generate_text(system_prompt, user_prompt, **kwargs):
        writer_calls.append(kwargs)
        return "【场1-1：夜 内 客厅】\n△她攥住纸。\n林晚：我不签。"

    def fake_evaluate(req, content, quality_anchor_block):
        reviewer_models.append((req.generation_provider, req.generation_model))
        return {
            "content": content,
            "blocking_issues": [],
            "quality_passed": True,
            "warnings": [],
            "char_count_excluding_punctuation": 18,
        }

    monkeypatch.setattr(sg, "generate_text", fake_generate_text)
    monkeypatch.setattr(sg, "evaluate_testing_scene", fake_evaluate)

    req = _minimal_req(
        advanced_generation_mode=True,
        advanced_generation_providers={
            "creative": {"provider": "kimi", "model": "kimi-k2.6", "temperature": 0.85},
            "review": {"provider": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.0},
        },
    )

    result = sg.generate_testing_scene_passed(req)

    assert result["quality_passed"] is True
    assert writer_calls[0]["provider"] == "kimi"
    assert writer_calls[0]["model"] == "kimi-k2.6"
    assert writer_calls[0]["temperature"] == 0.85
    assert reviewer_models == [("anthropic", "claude-sonnet-4-5")]


def test_minor_segment_word_count_drift_does_not_call_autofix(monkeypatch):
    from app.services import short_drama_scene_generation as sg

    def fake_generate_text(system_prompt, user_prompt, **kwargs):
        return "【场1-1：夜 内 客厅】\n△她攥住纸。\n林晚：我不签。"

    def fake_evaluate(req, content, quality_anchor_block):
        return {
            "content": content,
            "blocking_issues": ["净字数超限：当前 360，要求至多 320。"],
            "quality_passed": True,
            "warnings": [],
            "char_count_excluding_punctuation": 360,
        }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("minor length drift should be released, not auto-fixed")

    monkeypatch.setattr(sg, "generate_text", fake_generate_text)
    monkeypatch.setattr(sg, "evaluate_testing_scene", fake_evaluate)
    monkeypatch.setattr(sg, "auto_fix_testing_script_content", fail_if_called)

    result = sg.generate_testing_scene_passed(_minimal_req(word_count_min=280, word_count_max=320))

    assert result["quality_passed"] is True
    assert result["blocking_issues"] == []
    assert any("净字数与目标区间有偏差" in item for item in result["warnings"])
