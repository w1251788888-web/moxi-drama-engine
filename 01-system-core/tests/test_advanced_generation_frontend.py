from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_projects_view_exposes_advanced_generation_project_types():
    view = (ROOT / "webui" / "src" / "views" / "ProjectsView.vue").read_text(encoding="utf-8")

    assert "advancedGenerationApi" in view
    assert "profileOptions" in view
    assert "话剧" in view
    assert "影视剧" in view
    assert "advanced_generation_mode" in view


def test_advanced_generation_view_has_create_entry_not_waitlist_only():
    src = ROOT / "webui" / "src"
    view = (src / "views" / "AdvancedGenerationView.vue").read_text(encoding="utf-8")
    card = (
        src / "features" / "advanced-generation" / "components" / "AdvancedGenerationProfileCard.vue"
    ).read_text(encoding="utf-8")

    assert "创建这种项目" in view + card
    assert "暂未上线" not in view + card


def test_advanced_generation_frontend_framework_is_split():
    src = ROOT / "webui" / "src"
    view = (src / "views" / "AdvancedGenerationView.vue").read_text(encoding="utf-8")

    assert (src / "features" / "advanced-generation" / "composables" / "useAdvancedGenerationProfiles.ts").exists()
    assert (src / "features" / "advanced-generation" / "composables" / "useAdvancedGenerationCapabilities.ts").exists()
    assert (src / "features" / "advanced-generation" / "presentation.ts").exists()
    assert (src / "features" / "advanced-generation" / "components" / "AdvancedGenerationProfileCard.vue").exists()
    assert (src / "features" / "advanced-generation" / "components" / "AdvancedGenerationCapabilityOverview.vue").exists()
    assert "useAdvancedGenerationProfiles" in view
    assert "AdvancedGenerationProfileCard" in view
    assert "AdvancedGenerationCapabilityOverview" in view


def test_advanced_generation_capability_overview_uses_backend_contracts():
    src = ROOT / "webui" / "src" / "features" / "advanced-generation"
    composable = (src / "composables" / "useAdvancedGenerationCapabilities.ts").read_text(encoding="utf-8")
    component = (src / "components" / "AdvancedGenerationCapabilityOverview.vue").read_text(encoding="utf-8")

    assert "advancedGenerationApi.getOrchestrationStatus" in composable
    assert "advancedGenerationApi.getOrchestrationPlan" in composable
    assert "collaborationApi.yjsStatus" in composable
    assert "collaborationApi.yjsPlan" in composable
    assert "searchApi.status" in composable
    assert "searchApi.semanticStatus" in composable
    assert "cacheApi.status" in composable
    assert "'/admin/cache/status'" not in composable
    assert "FTS5" in composable + component
    assert "Redis" in composable + component
    assert "Chroma" in composable + component
    assert "LangGraph" in composable + component
    assert "Yjs" in composable + component
