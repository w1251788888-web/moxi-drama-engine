"""
管理员会话 Token 模型 — 持久化存储，按安全 TTL 过期
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime

from app.database import Base


class AdminSession(Base):
    __tablename__ = "admin_session"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token = Column(String(64), unique=True, nullable=False, index=True, comment="Session token")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    last_used_at = Column(DateTime, default=datetime.now, comment="最近使用时间")
