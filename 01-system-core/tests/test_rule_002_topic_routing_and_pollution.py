from app.services.short_drama_rule_resolver import (
    resolve_sample_track_rule_decision_from_variables,
    resolve_sample_track_rule_name_from_variables,
    resolve_subgenre_rule_decision_from_variables,
    resolve_subgenre_rule_name_from_variables,
)


def test_rule_002b_sample_track_explicit_route_is_auditable():
    decision = resolve_sample_track_rule_decision_from_variables(
        {"sample_track": "sample_track_d_realistic_family", "brief": "豪门打脸和档案调查混在一起"}
    )

    assert decision.rule_name == "sample_track_d_realistic_family"
    assert decision.source == "explicit"
    assert decision.confidence == 1.0
    assert decision.requested == "sample_track_d_realistic_family"
    assert "用户显式" in decision.reason
    assert resolve_sample_track_rule_name_from_variables({"sample_track": "sample_track_d_realistic_family"}) == decision.rule_name


def test_rule_002b_sample_track_inferred_route_keeps_evidence_tokens():
    decision = resolve_sample_track_rule_decision_from_variables(
        {"brief": "女儿回乡替母亲去县医院缴费，父亲背着债务送站。"}
    )

    assert decision.rule_name == "sample_track_d_realistic_family"
    assert decision.source == "inferred"
    assert 0 < decision.confidence < 1
    assert {"回乡", "母亲", "县医院", "父亲", "债务", "送站"} & set(decision.matched_tokens)
    assert "命中" in decision.reason


def test_rule_002b_sample_track_does_not_guess_from_unrelated_archive_topic():
    decision = resolve_sample_track_rule_decision_from_variables(
        {
            "audience_axis": "混合",
            "brief": "何铮在档案室追查越界报告，门禁锁死，审批号刷新，倒计时跳出。",
        }
    )

    assert decision.rule_name == ""
    assert decision.source == "none"
    assert decision.confidence == 0
    assert decision.matched_tokens == ()


def test_rule_002b_subgenre_explicit_route_is_auditable():
    decision = resolve_subgenre_rule_decision_from_variables(
        {"subgenre_track": "subgenre_female_face_slap", "audience_axis": "女频"}
    )

    assert decision.rule_name == "subgenre_female_face_slap"
    assert decision.source == "explicit"
    assert decision.confidence == 1.0
    assert "用户显式" in decision.reason
    assert resolve_subgenre_rule_name_from_variables({"subgenre_track": "subgenre_female_face_slap"}) == decision.rule_name


def test_rule_002b_subgenre_inferred_route_exposes_reason_without_business_pollution():
    decision = resolve_subgenre_rule_decision_from_variables(
        {"audience_axis": "混合", "brief": "儿子回乡处理父亲债务，母亲在县医院等检查结果。"}
    )

    assert decision.rule_name == "subgenre_hybrid_realistic_family"
    assert decision.source == "inferred"
    assert decision.confidence > 0
    assert {"回乡", "父亲", "债务", "母亲", "县医院"} & set(decision.matched_tokens)
    assert "命中" in decision.reason
