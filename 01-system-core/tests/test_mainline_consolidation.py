from pathlib import Path

from app.main import app
from app.routers.phase2_placeholders import phase2_status


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui" / "src"


def read_src(relative: str) -> str:
    return (WEBUI / relative).read_text(encoding="utf-8")


def test_primary_navigation_uses_project_mainline_not_tasks():
    app_layout = read_src("views/AppLayout.vue")

    assert "path: '/projects'" in app_layout
    assert "path: '/tasks'" not in app_layout


def test_legacy_tasks_route_redirects_to_project_mainline():
    router = read_src("router/index.ts")

    assert "path: 'tasks'" in router
    assert "redirect: '/projects'" in router
    assert "TasksView.vue" not in router


def test_settings_does_not_expose_render_provider_placeholder_tab():
    settings = read_src("views/SettingsView.vue")

    assert "RenderProviderSettings" not in settings
    assert 'TabsTrigger value="render"' not in settings
    assert "渲染服务商" not in settings


def test_storyboard_panel_does_not_advertise_video_generation_placeholder():
    panel = read_src("components/workshop/StoryboardPanel.vue")

    assert "生成视频（二期）" not in panel
    assert "placeholderRenderVideo" not in panel


def test_character_visual_panel_does_not_advertise_lora_training_placeholder():
    panel = read_src("components/workshop/CharacterVisualPanel.vue")

    assert "LoRA" not in panel


async def test_phase2_status_does_not_advertise_red_placeholder_features():
    status = await phase2_status(True)

    advertised = {item["feature"] for item in status["items"]}
    assert "lora_training" not in advertised
    assert "reference_video" not in advertised
    assert "timeline_export" not in advertised
    assert "audio_generation" not in advertised


def test_red_phase2_placeholder_endpoints_are_not_mounted():
    mounted_paths = set(app.openapi().get("paths", {}).keys())

    assert "/api/phase2/status" in mounted_paths
    assert "/api/phase2/lora/train" not in mounted_paths
    assert "/api/phase2/reference-video/analyze" not in mounted_paths
    assert "/api/phase2/timeline/export" not in mounted_paths
    assert "/api/phase2/audio/generate" not in mounted_paths
