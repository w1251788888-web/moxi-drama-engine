"""
墨戏生花 短剧剧本智能创作系统 — 主入口
"""
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.config import config
from app.auth.dependencies import get_current_agent
from app.routers import (
    admin,
    admin_agents,
    admin_cache,
    admin_config,
    admin_dashboard,
    admin_logs,
    admin_reviews,
    admin_scores,
    admin_tasks,
    agents,
    ai_health,
    auto_fix,
    collaboration,
    feed,
    issues,
    lightweight_learning,
    logs,
    market,
    materials,
    project_learning,
    prompts,
    review_records,
    rule_quality,
    rules,
    search,
    scores,
    saas_admin,
    setup,
    skill_workflows,
    short_drama_writing,
    step_version_router,
    episode_segment_router,
    sub_tasks,
    tasks,
    telemetry,
    tools,
    projects_v2,
)
from app.api.routes import config as config_api
from app.middleware.request_logger import RequestLoggerMiddleware


APP_VERSION = "1.0.0"


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _resolve_git_sha() -> str:
    env_sha = os.getenv("MOXI_GIT_SHA", os.getenv("MOXI_DEPLOY_COMMIT", "")).strip()
    if env_sha:
        return env_sha

    core_root = Path(__file__).resolve().parents[1]
    repo_root = core_root.parent
    for candidate in (
        core_root / "DEPLOYED_GIT_COMMIT",
        repo_root / "DEPLOYED_GIT_COMMIT",
        Path("/app/DEPLOYED_GIT_COMMIT"),
        Path("/opt/moxi-shenghua/DEPLOYED_GIT_COMMIT"),
    ):
        value = _read_text_if_exists(candidate)
        if value:
            return value

    head = _read_text_if_exists(repo_root / ".git" / "HEAD")
    if head.startswith("ref: "):
        ref_value = _read_text_if_exists(repo_root / ".git" / head[5:].strip())
        if ref_value:
            return ref_value
    return head


def _config_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _version_feature_flags() -> dict:
    raw = config.raw if isinstance(config.raw, dict) else {}
    rag = raw.get("rag") if isinstance(raw.get("rag"), dict) else {}
    dify = rag.get("dify") if isinstance(rag.get("dify"), dict) else {}
    knowledge_chunks = rag.get("knowledge_chunks") if isinstance(rag.get("knowledge_chunks"), dict) else {}
    graphiti = raw.get("graphiti") if isinstance(raw.get("graphiti"), dict) else {}

    env_dify = os.getenv("MOXI_DIFY_ENABLED", os.getenv("MOXI_RAG_DIFY_ENABLED"))
    dify_enabled = _config_bool(env_dify, default=_config_bool(dify.get("enabled"), default=True))
    knowledge_chunks_enabled = _config_bool(knowledge_chunks.get("enabled"), default=False)
    graphiti_enabled = _config_bool(graphiti.get("enabled"), default=False)

    return {
        "dify_enabled": dify_enabled,
        "knowledge_chunks_enabled": knowledge_chunks_enabled,
        "graphiti_enabled": graphiti_enabled,
    }


def _check_prompt_symlink_health() -> None:
    """检查 prompts 兼容入口是否仍然正确指向规则真源。"""
    core_root = Path(__file__).resolve().parents[1]
    repo_root = core_root.parent
    prompts_root = core_root / "prompts"
    source_root = repo_root / "02-creation-rules"
    expected_links = {
        "agents": source_root / "agent-definitions",
        "knowledge": source_root / "knowledge-base",
        "rules": source_root / "core-rules",
        "steps": source_root / "step-definitions",
        "templates": source_root / "templates",
    }

    for name, target in expected_links.items():
        link_path = prompts_root / name
        if not link_path.exists():
            print(f"[PromptHealth] 缺失入口: {link_path}")
            continue
        if not link_path.is_symlink():
            print(f"[PromptHealth] 入口不是符号链接，存在真源漂移风险: {link_path}")
            continue
        resolved = link_path.resolve()
        if resolved != target.resolve():
            print(f"[PromptHealth] 链接目标异常: {link_path} -> {resolved} (期望 {target})")


def _cleanup_old_request_logs():
    """启动时清理过期的请求日志"""
    from datetime import datetime, timedelta
    from app.database import SessionLocal
    from app.models.request_log import RequestLog

    days = config.feed_retention_days
    cutoff = datetime.now() - timedelta(days=days)

    db = SessionLocal()
    try:
        deleted = db.query(RequestLog).filter(RequestLog.timestamp < cutoff).delete()
        db.commit()
        if deleted > 0:
            print(f"[RequestLog] 已清理 {deleted} 条超过 {days} 天的请求日志")
    except Exception as e:
        print(f"[RequestLog] 清理失败: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    init_db()
    _check_prompt_symlink_health()

    # 清理过期请求日志
    _cleanup_old_request_logs()

    # 初始化遥测系统
    try:
        from app.telemetry_integration import init_telemetry
        telemetry_summary = init_telemetry()
        print(f"[{config.project_name}] 遥测系统已初始化 | 活跃会话: {telemetry_summary.get('active_sessions', 0)}")
    except Exception as e:
        print(f"[{config.project_name}] 遥测系统初始化失败: {e}")

    print(f"[{config.project_name}] 服务启动 → http://{config.server_host}:{config.server_port}")
    print(f"[{config.project_name}] 数据库: {config.database_path}")
    print(f"[{config.project_name}] 工作目录: {config.workspace_root}")
    print(f"[{config.project_name}] 注册令牌: {config.redacted_registration_token}")
    yield
    print(f"[{config.project_name}] 服务关闭")


app = FastAPI(
    title=f"{config.project_name} 任务调度中间件",
    description="基于 OpenClaw 的自组织自协作自进化多 Agent 作业平台",
    version=APP_VERSION,
    lifespan=lifespan,
)

# 请求日志中间件（记录 Agent API 调用）
app.add_middleware(RequestLoggerMiddleware)

# CORS 跨域支持（前后端分离部署时需要，必须在最外层）
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_allowed_origins,
    allow_origin_regex=config.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ============================================================
# 全局异常处理
# ============================================================

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """业务逻辑错误 → 400"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


from app.services.text_generation_service import TextGenerationError


@app.exception_handler(TextGenerationError)
async def text_generation_error_handler(request: Request, exc: TextGenerationError):
    """AI 生成错误 → 带可解释提示的结构化响应。

    前端拿到后可按 error_code 做差异化提示（key 错 / 限流 / 超长 / 网络 / 配置缺失）。
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "detail": exc.user_message,
            "error_code": exc.code,
            "suggestion": exc.suggestion,
            "raw": str(exc)[:500],
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """未处理异常 → 500，日志记录堆栈，客户端只看到通用提示"""
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "服务内部错误，请联系管理员"},
    )


@app.get("/api/health", tags=["Health"])
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": config.project_name, "version": APP_VERSION}


@app.get("/api/version", tags=["Health"])
async def version_check():
    """部署版本检查：用于核对本地和线上是否同一份代码。"""
    git_sha = _resolve_git_sha()
    return {
        "service": config.project_name,
        "version": APP_VERSION,
        "git_sha": git_sha,
        "git_sha_short": git_sha[:12] if git_sha else "",
        "build_time": os.getenv("MOXI_BUILD_TIME", ""),
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "features": _version_feature_flags(),
    }


@app.get("/api/config/notification", tags=["Config"])
async def get_notification_config(agent=Depends(get_current_agent)):
    """Agent 获取通知渠道配置（往哪里发通知）"""
    notification = config.notification_config
    return {
        "enabled": notification.get("enabled", False),
        "channels": notification.get("channels", []),
        "events": notification.get("events", []),
    }


# 注册路由（统一 /api 前缀）
API_PREFIX = "/api"
app.include_router(agents.router, prefix=API_PREFIX)
app.include_router(ai_health.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(admin_agents.router, prefix=API_PREFIX)
app.include_router(admin_cache.router, prefix=API_PREFIX)
app.include_router(admin_config.router, prefix=API_PREFIX)
app.include_router(admin_dashboard.router, prefix=API_PREFIX)
app.include_router(admin_logs.router, prefix=API_PREFIX)
app.include_router(admin_reviews.router, prefix=API_PREFIX)
app.include_router(admin_scores.router, prefix=API_PREFIX)
app.include_router(admin_tasks.router, prefix=API_PREFIX)
app.include_router(tasks.router, prefix=API_PREFIX)
app.include_router(sub_tasks.router, prefix=API_PREFIX)
app.include_router(rules.router, prefix=API_PREFIX)
app.include_router(search.router, prefix=API_PREFIX)
app.include_router(collaboration.router, prefix=API_PREFIX)
app.include_router(review_records.router, prefix=API_PREFIX)
app.include_router(scores.router, prefix=API_PREFIX)
app.include_router(saas_admin.admin_router, prefix=API_PREFIX)
app.include_router(saas_admin.user_router, prefix=API_PREFIX)
app.include_router(logs.router, prefix=API_PREFIX)
app.include_router(issues.router, prefix=API_PREFIX)
app.include_router(feed.router, prefix=API_PREFIX)
app.include_router(prompts.router, prefix=API_PREFIX)
app.include_router(tools.router, prefix=API_PREFIX)
app.include_router(setup.router, prefix=API_PREFIX)
app.include_router(skill_workflows.router, prefix=API_PREFIX)
app.include_router(market.router, prefix=API_PREFIX)
app.include_router(market.user_router, prefix=API_PREFIX)
app.include_router(materials.router, prefix=API_PREFIX)
app.include_router(short_drama_writing.router, prefix=API_PREFIX)
app.include_router(step_version_router.router, prefix=API_PREFIX)
app.include_router(episode_segment_router.router, prefix=API_PREFIX)
app.include_router(telemetry.router, prefix=API_PREFIX)
app.include_router(auto_fix.router, prefix=API_PREFIX)
app.include_router(project_learning.router, prefix=API_PREFIX)
app.include_router(rule_quality.router, prefix=API_PREFIX)
app.include_router(lightweight_learning.router, prefix=API_PREFIX)

# ── 分镜与提示词系统（一期 + 二期占位）──
from app.routers import (  # noqa: E402
    script_confirm as _script_confirm_router,
    character_visual as _character_visual_router,
    storyboard as _storyboard_router,
    render_config as _render_config_router,
    phase2_placeholders as _phase2_router,
)
app.include_router(_script_confirm_router.router, prefix=API_PREFIX)
app.include_router(_character_visual_router.router, prefix=API_PREFIX)
app.include_router(_storyboard_router.router, prefix=API_PREFIX)
app.include_router(_render_config_router.router, prefix=API_PREFIX)
app.include_router(_phase2_router.router, prefix=API_PREFIX)

# 注册 V2 项目路由（新的Skill化架构API）
app.include_router(projects_v2.router, prefix="")  # 已经在router中定义了前缀 /api/v2/projects

# 注册配置管理API（支持模型提供商配置）
app.include_router(config_api.router, prefix="/api/v2")


# ============================================================
# WebUI 静态文件服务（当 static/ 目录存在时自动启用）
# ============================================================

_webui_dist = os.path.join(os.path.dirname(__file__), "..", "static")

if os.path.isdir(_webui_dist):
    # 挂载静态资源（JS/CSS/图片等）—— 带防缓存头，确保每次部署都刷新
    _assets_dir = os.path.join(_webui_dist, "assets")
    if os.path.isdir(_assets_dir):
        from fastapi.staticfiles import StaticFiles
        from starlette.staticfiles import StaticFiles as StarletteStaticFiles
        from starlette.responses import FileResponse

        class NoCacheStaticFiles(StarletteStaticFiles):
            """自定义 StaticFiles，添加防缓存头"""
            async def get_response(self, path: str, scope):
                response = await super().get_response(path, scope)
                if hasattr(response, 'headers'):
                    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
                    response.headers["Pragma"] = "no-cache"
                    response.headers["Expires"] = "0"
                    # 添加动态版本戳，确保浏览器识别为新请求
                    import time
                    response.headers["X-Build-Time"] = str(int(time.time()))
                return response

        app.mount("/assets", NoCacheStaticFiles(directory=_assets_dir), name="webui-assets")

    # index.html 专用响应头：禁止浏览器缓存，保证每次都拿到最新构建
    _NO_CACHE_HEADERS = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    # 所有未匹配路径 → 先尝试返回静态文件，再回退到 index.html（SPA 前端路由）
    @app.get("/", include_in_schema=False)
    async def serve_root():
        """根路径直接返回 index.html"""
        index = os.path.join(_webui_dist, "index.html")
        if os.path.isfile(index):
            return FileResponse(index, headers=_NO_CACHE_HEADERS)
        return JSONResponse(status_code=404, content={"detail": "WebUI not found"})

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """其他路径：静态文件优先，否则返回 index.html（SPA 路由）"""
        # /api/* 未匹配的路径 → 返回 404 JSON，不要把 API 请求吃进 SPA
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": f"API endpoint not found: /{full_path}"})
        # 先检查是否有对应的静态文件（如 logo-200.png, favicon.ico 等）
        static_file = os.path.join(_webui_dist, full_path)
        if full_path and os.path.isfile(static_file):
            return FileResponse(static_file)
        # 否则返回 index.html（SPA 路由），附带禁缓存头
        index = os.path.join(_webui_dist, "index.html")
        if os.path.isfile(index):
            return FileResponse(index, headers=_NO_CACHE_HEADERS)
        return JSONResponse(status_code=404, content={"detail": "WebUI not found"})

    print(f"[WebUI] 已挂载前端: {os.path.abspath(_webui_dist)}")
