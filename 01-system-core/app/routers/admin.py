"""
管理端路由 — 登录
"""
import os
import secrets
import bcrypt
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.config import config
from app.database import get_db
from app.models.admin_session import AdminSession
from app.models.admin_user import AdminUser


router = APIRouter(prefix="/admin", tags=["Admin"])

DEFAULT_ADMIN_SESSION_TTL_MINUTES = 24 * 60
ADMIN_SESSION_TTL_ENV = "MOXI_ADMIN_SESSION_TTL_MINUTES"


# ============================================================
# Token 工具函数（持久化到 SQLite，按 TTL 自动过期）
# ============================================================

def get_admin_session_ttl_minutes() -> int:
    """读取管理员 session 空闲过期分钟数，默认 24 小时。"""
    raw = os.getenv(ADMIN_SESSION_TTL_ENV, "").strip()
    if not raw:
        raw = str(config._data.get("admin", {}).get("session_ttl_minutes", "") or "")
    if not raw:
        return DEFAULT_ADMIN_SESSION_TTL_MINUTES
    try:
        ttl = int(raw)
    except ValueError:
        return DEFAULT_ADMIN_SESSION_TTL_MINUTES
    return max(1, ttl)


def is_admin_session_expired(row: AdminSession, now: datetime | None = None) -> bool:
    """判断管理员 session 是否已经超过空闲过期时间。"""
    now = now or datetime.now()
    last_activity = row.last_used_at or row.created_at
    if last_activity is None:
        return True
    return last_activity + timedelta(minutes=get_admin_session_ttl_minutes()) <= now


def cleanup_expired_admin_sessions(db: Session, now: datetime | None = None) -> int:
    """清理过期管理员 session，返回删除数量。"""
    now = now or datetime.now()
    expired_rows = [
        row
        for row in db.query(AdminSession).all()
        if is_admin_session_expired(row, now)
    ]
    for row in expired_rows:
        db.delete(row)
    if expired_rows:
        db.commit()
    return len(expired_rows)


def create_admin_token(db: Session) -> str:
    """生成随机 admin session token 并持久化到数据库。"""
    cleanup_expired_admin_sessions(db)
    now = datetime.now()
    token = secrets.token_hex(32)
    session = AdminSession(token=token, created_at=now, last_used_at=now)
    db.add(session)
    db.commit()
    return token


def is_valid_admin_token(token: str, db: Session) -> bool:
    """验证 admin session token 是否有效，过期则清理并拒绝。"""
    if not token:
        return False
    cleanup_expired_admin_sessions(db)
    row = db.query(AdminSession).filter(AdminSession.token == token).first()
    if not row:
        return False
    if is_admin_session_expired(row):
        db.delete(row)
        db.commit()
        return False

    row.last_used_at = datetime.now()
    db.commit()
    return True


def revoke_admin_token(token: str, db: Session) -> None:
    """注销指定 token"""
    db.query(AdminSession).filter(AdminSession.token == token).delete()
    db.commit()


def hash_admin_user_password(password: str) -> str:
    """Hash a database admin password using the same bcrypt format as config.yaml."""
    return "bcrypt:" + bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_admin_user_password(password: str, stored_hash: str) -> bool:
    stored = str(stored_hash or "")
    if not stored.startswith("bcrypt:"):
        return False
    return bcrypt.checkpw(password.encode(), stored[7:].encode())


def upsert_admin_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str = "admin",
    note: str = "",
) -> AdminUser:
    """Create or reset a database-backed admin account for local testing/ops."""
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise ValueError("管理员账号不能为空")
    if len(str(password or "")) < 8:
        raise ValueError("管理员密码至少 8 位")
    row = db.query(AdminUser).filter(AdminUser.username == normalized_username).first()
    if row is None:
        row = AdminUser(username=normalized_username)
        db.add(row)
    row.password_hash = hash_admin_user_password(password)
    row.role = str(role or "admin")
    row.status = "active"
    row.note = str(note or "")
    db.commit()
    db.refresh(row)
    return row


# ============================================================
# 请求/响应模型
# ============================================================

class AdminLoginRequest(BaseModel):
    username: str = Field("admin", description="管理员账号")
    password: str = Field(..., description="管理员密码")


class AdminLoginResponse(BaseModel):
    token: str
    message: str = "登录成功"


# ============================================================
# 路由
# ============================================================

@router.post("/login", response_model=AdminLoginResponse, summary="管理员登录")
async def admin_login(req: AdminLoginRequest, db: Session = Depends(get_db)):
    """
    管理员使用密码登录，返回随机 session token。
    后续管理操作通过 Header X-Admin-Token 传递此 token。
    token 持久化到数据库，但会按 TTL 自动过期。
    """
    username = str(req.username or "").strip()
    if username == "admin":
        if not config.verify_admin_password(req.password):
            raise HTTPException(status_code=403, detail="密码错误")
    else:
        admin_user = db.query(AdminUser).filter(AdminUser.username == username).first()
        if (
            admin_user is None
            or admin_user.status != "active"
            or not verify_admin_user_password(req.password, admin_user.password_hash)
        ):
            raise HTTPException(status_code=403, detail="账号或密码错误")

    token = create_admin_token(db)
    return AdminLoginResponse(token=token)


@router.post("/logout", summary="管理员登出")
async def admin_logout(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    """注销当前 session token"""
    if x_admin_token:
        revoke_admin_token(x_admin_token, db)
    return {"message": "已登出"}
