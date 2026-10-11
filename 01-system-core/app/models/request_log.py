"""
请求日志表模型 — 记录 Agent 的所有 API 请求
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, DateTime

from app.database import Base


class RequestLog(Base):
    __tablename__ = "request_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.now, index=True, comment="请求时间")
    method = Column(String(10), nullable=False, comment="HTTP 方法: GET/POST/PUT/DELETE")
    path = Column(String(500), nullable=False, index=True, comment="请求路径")
    agent_id = Column(String(36), nullable=True, index=True, comment="操作 Agent ID")
    agent_name = Column(String(100), nullable=True, comment="Agent 名称（冗余）")
    agent_role = Column(String(20), nullable=True, comment="Agent 角色（冗余）")
    request_body = Column(Text, nullable=True, comment="请求体 JSON（POST/PUT）")
    response_status = Column(Integer, nullable=True, comment="HTTP 响应状态码")
