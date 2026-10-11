from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rule_002f_outline_gate_exposes_actionable_repair_hints():
    source = (ROOT / "webui/src/features/workspace/composables/useOutlineGate.ts").read_text(encoding="utf-8")

    assert "OUTLINE_GATE_REPAIR_GUIDES" in source
    assert "outlineGateFixHints" in source
    assert "firstRepairHint" in source

    for issue_prefix in (
        "大纲前置信息缺少工业化字段",
        "大纲分集缺少可执行字段",
        "大纲分集主场景过泛",
        "人物小传缺少工业化字段",
        "全剧情推演尚未形成分集契约",
    ):
        assert issue_prefix in source

    for user_action in (
        "回到大纲页",
        "补齐一句可拍、可执行的信息",
        "写成具体空间",
        "把上面缺的字段补成具体可拍信息",
        "重新同步全剧情推演",
    ):
        assert user_action in source


def test_rule_002f_workspace_toast_uses_repair_hint_not_only_blocking_label():
    source = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text(encoding="utf-8")

    assert "outlineGateFixHints" in source
    assert "firstRepairHint: firstOutlineGateRepairHint" in source
    assert "处理方式：" in source
    assert "请先完成大纲锁定门" in source
    assert "primaryIssue" in source
    assert "remainingIssueCount" in source
    assert "firstOutlineGateRepairHint(options?.episodeLimit)" in source or "firstOutlineGateRepairHint()" in source
    assert "另有" in source
    assert "outlineGateFixHints.value.slice(0, 2).join" not in source


def test_rule_002f_outline_gate_supports_progressive_episode_limit():
    source = (ROOT / "webui/src/features/workspace/composables/useOutlineGate.ts").read_text(encoding="utf-8")
    workspace = (ROOT / "webui/src/views/ProjectWorkspaceView.vue").read_text(encoding="utf-8")

    assert "outlineGateIssuesForEpisodeLimit" in source
    assert "episodeLimit" in source
    assert "allEpisodes.slice(0, expectedEpisodeCount)" in source
    assert "hasCompleteSeriesSimulationContracts(simulationPacket, expectedEpisodeCount)" in source
    assert "ensureOutlineGatePassed: () => ensureOutlineGatePassed({ episodeLimit: Number(selectedEpisode.value || 1) || 1 })" in workspace
    assert "ensureOutlineGatePassed({ episodeLimit: nextEp })" in workspace
    assert "_refreshSeriesSimulationPacket('script_generation_preflight'" in workspace
