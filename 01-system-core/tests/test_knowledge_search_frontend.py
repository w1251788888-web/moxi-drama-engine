from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "webui" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_knowledge_search_panel_stays_off_user_facing_lab():
    composable = SRC / "features" / "search" / "composables" / "useKnowledgeSearch.ts"
    component = SRC / "features" / "search" / "components" / "KnowledgeSearchPanel.vue"
    lab_view = read(SRC / "views" / "LabView.vue")

    assert composable.exists()
    assert component.exists()
    assert "KnowledgeSearchPanel" not in lab_view
    assert "@/features/search/components/KnowledgeSearchPanel.vue" not in lab_view
    assert "<KnowledgeSearchPanel" not in lab_view
    assert "知识库检索" not in lab_view
    assert "规则素材检索" not in lab_view


def test_user_facing_script_confirm_copy_hides_rag_terms():
    component = read(SRC / "components" / "workshop" / "ScriptConfirmButton.vue")

    assert "RAG" not in component
    assert "rag_doc_count" not in component
    assert "rag_enabled" not in component
    assert "创作状态已更新" in component


def test_outline_user_copy_asks_humans_to_check_auto_split_results():
    raw_panel = read(SRC / "views" / "workspace" / "tabs" / "OutlineRawPanel.vue")
    character_panel = read(SRC / "views" / "workspace" / "tabs" / "OutlineCharacterListPanel.vue")
    episode_panel = read(SRC / "views" / "workspace" / "tabs" / "OutlineEpisodeFrameworkPanel.vue")
    combined = raw_panel + character_panel + episode_panel

    assert "请重点核对角色身份、人物关系、集纲顺序和首尾承接" in raw_panel
    assert "自动识别只能作为初稿" in character_panel
    assert "范围集纲和表格集纲已尽量识别" in episode_panel
    assert "RAG" not in combined
    assert "Dify" not in combined
    assert "知识库检索" not in combined


def test_knowledge_search_uses_existing_search_api_contracts():
    composable = read(SRC / "features" / "search" / "composables" / "useKnowledgeSearch.ts")
    component = read(SRC / "features" / "search" / "components" / "KnowledgeSearchPanel.vue")

    assert "searchApi.status()" in composable
    assert "searchApi.search(params)" in composable
    assert "searchApi.semanticSearch(params)" in composable
    assert "auto_rebuild: true" in composable
    assert "semantic_degraded" in composable + component
    assert "semantic_error" in composable + component
    assert "后端" in component
    assert "降级提示" in component


def test_knowledge_search_has_required_controls_and_doc_type_copy():
    composable = read(SRC / "features" / "search" / "composables" / "useKnowledgeSearch.ts")
    component = read(SRC / "features" / "search" / "components" / "KnowledgeSearchPanel.vue")
    combined = composable + component

    assert "知识库检索 / 规则素材检索" in component
    assert "查询" in component
    assert "语义检索" in component
    assert "全文检索" in component
    assert "类型筛选" in component
    assert "索引状态" in component or "statusSummary" in component
    assert "emptyMessage" in component
    assert "errorMessage" in component
    assert "规则 rule" in combined
    assert "素材 material" in combined
    assert "项目 project" in combined
    assert "技能 skill" in combined
    assert "来源路径" in component
