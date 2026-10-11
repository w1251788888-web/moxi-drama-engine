"""项目 API v2 主路由聚合器。

具体路由实现已按域拆分到 app/routers/projects/ 下：
- routes_projects.py        项目 CRUD + 模型提供商
- routes_stores.py          角色库 / 状态卡 / 工作流上下文 stores
- routes_episodes_scenes.py 集 / 场 / 版本 / 回滚
- routes_contributions.py   项目贡献度
- routes_generation.py      AI 生成任务 + 大纲分析

本文件保留 router 实例和 WORKSPACE_ROOT 别名供老路径兼容。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routers.projects import (
    routes_contributions,
    routes_collaboration,
    routes_compliance,
    routes_episodes_scenes,
    routes_evidence_approvals,
    routes_generation,
    routes_legal_assets,
    routes_projects,
    routes_stores,
)
# 兼容老 import：以前 main.py 里用 projects_v2.WORKSPACE_ROOT、projects_v2.SessionLocal
from app.routers.projects._helpers import REPO_ROOT, WORKSPACE_ROOT  # noqa: F401
from app.database import SessionLocal  # noqa: F401

router = APIRouter(prefix="/api/v2/projects", tags=["Projects V2"])

# 5 个子路由聚合到一个主 router 上，对外路径不变
router.include_router(routes_projects.router)
router.include_router(routes_stores.router)
router.include_router(routes_episodes_scenes.router)
router.include_router(routes_contributions.router)
router.include_router(routes_generation.router)
router.include_router(routes_evidence_approvals.router)
router.include_router(routes_collaboration.router)
router.include_router(routes_compliance.router)
router.include_router(routes_legal_assets.router)
