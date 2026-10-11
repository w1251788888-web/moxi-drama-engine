from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lab_ai_topics_route_does_not_block_event_loop_with_sync_model_call():
    route = (ROOT / "app" / "routers" / "market.py").read_text(encoding="utf-8")

    assert "import asyncio" in route
    assert "await asyncio.to_thread(" in route
    assert "generate_json," in route
    assert "user_router = APIRouter(prefix=\"/user/market\"" in route
    assert "verify_project_actor" in route
