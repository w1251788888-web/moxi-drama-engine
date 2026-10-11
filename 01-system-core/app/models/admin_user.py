"""数据库管理员账号。

保留 config.yaml 内置 admin 账号作为兜底，同时允许测试/运营阶段在 SQLite
中维护多个后台登录账号。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.database import Base


class AdminUser(Base):
    __tablename__ = "admin_user"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(40), default="admin")
    status = Column(String(30), default="active", index=True)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
