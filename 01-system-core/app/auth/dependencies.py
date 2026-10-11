"""
鉴权依赖注入 — Agent API Key 鉴权 & 管理员鉴权
两套鉴权完全隔离，互不通用
"""
from dataclasses import dataclass

from fastapi import Header, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent


# ============================================================
# Agent 鉴权（API Key）
# ============================================================

async def get_current_agent(
    authorization: str = Header(..., description="Bearer <api_key>"),
    db: Session = Depends(get_db),
) -> Agent:
    """
    从 Authorization Header 解析 API Key，返回当前 Agent。
    用法：在路由参数里加 agent: Agent = Depends(get_current_agent)
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 格式错误，需要 Bearer <api_key>")

    api_key = authorization[7:]  # 去掉 "Bearer "

    agent = db.query(Agent).filter(Agent.api_key == api_key).first()
    if not agent:
        raise HTTPException(status_code=401, detail="无效的 API Key")

    if agent.status == "disabled":
        raise HTTPException(status_code=403, detail="Agent 已禁用，无法操作")

    return agent


def require_role(*allowed_roles: str):
    """
    角色权限依赖工厂。
    用法：agent: Agent = Depends(require_role("planner"))
          agent: Agent = Depends(require_role("planner", "patrol"))
    """
    async def _check_role(
        agent: Agent = Depends(get_current_agent),
    ) -> Agent:
        if agent.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"该操作仅限 {'/'.join(allowed_roles)} 角色，你的角色是 {agent.role}",
            )
        return agent
    return _check_role


# ============================================================
# 管理员鉴权（Session Token — 持久化到 SQLite）
# ============================================================

async def verify_admin(
    x_admin_token: str = Header(None, alias="X-Admin-Token", description="管理员登录后获取的 session token"),
    db: Session = Depends(get_db),
) -> bool:
    """
    验证管理员 session token（查询 SQLite，重启后依然有效）。
    用法：在路由参数里加 _: bool = Depends(verify_admin)
    """
    from app.routers.admin import is_valid_admin_token
    if not is_valid_admin_token(x_admin_token, db):
        raise HTTPException(status_code=403, detail="无效或已过期的管理员 Token，请重新登录")
    return True


@dataclass(frozen=True)
class ProjectAccessActor:
    """项目区通用访问身份：管理员可看全部，普通用户只看自己的项目。"""

    actor_type: str
    access_key_id: str = ""
    owner_name: str = ""
    advanced_generation_enabled: bool = False
    allow_copy_export: bool = False
    admin_role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.actor_type == "admin"

    @property
    def is_user(self) -> bool:
        return self.actor_type == "user"

    @property
    def is_secondary_admin(self) -> bool:
        return self.actor_type == "secondary_admin"

    @property
    def can_copy_export(self) -> bool:
        return self.is_admin or self.allow_copy_export


async def verify_project_actor(
    x_admin_token: str = Header(None, alias="X-Admin-Token", description="管理员 session token"),
    x_user_session: str = Header(None, alias="X-User-Session", description="前台用户 session token"),
    db: Session = Depends(get_db),
) -> ProjectAccessActor:
    """项目路由鉴权：管理员或前台用户 session 二选一通过。"""
    from app.routers.admin import is_valid_admin_token
    from app.services.saas_access_service import verify_user_session_token

    if x_user_session:
        try:
            session = verify_user_session_token(x_user_session, db)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return ProjectAccessActor(
            actor_type="user",
            access_key_id=session.key_id,
            owner_name=session.owner_name,
            advanced_generation_enabled=session.advanced_generation_enabled,
            allow_copy_export=session.allow_copy_export,
            admin_role=session.admin_role,
        )

    if x_admin_token and is_valid_admin_token(x_admin_token, db):
        return ProjectAccessActor(actor_type="admin")

    raise HTTPException(status_code=403, detail="请先登录管理员后台或前台用户账号")


async def verify_advanced_generation_actor(
    actor: ProjectAccessActor = Depends(verify_project_actor),
) -> ProjectAccessActor:
    """高级生成访问门禁：管理员或已开启高级生成的普通用户。"""
    if actor.is_admin or actor.advanced_generation_enabled:
        return actor
    raise HTTPException(status_code=403, detail="当前账号未开通高级生成权限，请联系管理员开启")


async def verify_secondary_admin_actor(
    x_user_session: str = Header(None, alias="X-User-Session", description="二级管理员用户 session token"),
    db: Session = Depends(get_db),
) -> ProjectAccessActor:
    """二级管理员后台门禁：只允许带 secondary_admin 标记的用户密钥进入。"""
    from app.services.saas_access_service import verify_user_session_token

    if not x_user_session:
        raise HTTPException(status_code=403, detail="请先使用二级管理员密钥登录")
    try:
        session = verify_user_session_token(x_user_session, db)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if session.admin_role != "secondary_admin":
        raise HTTPException(status_code=403, detail="当前密钥不是二级管理员密钥")
    return ProjectAccessActor(
        actor_type="secondary_admin",
        access_key_id=session.key_id,
        owner_name=session.owner_name,
        advanced_generation_enabled=session.advanced_generation_enabled,
        allow_copy_export=session.allow_copy_export,
        admin_role=session.admin_role,
    )
