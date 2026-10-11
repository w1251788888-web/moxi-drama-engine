"""
素材库表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Float

from app.database import Base


class MaterialItem(Base):
    __tablename__ = "material_item"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_platform = Column(String(50), nullable=False, index=True, comment="来源平台")
    source_url = Column(Text, nullable=False, comment="来源链接")
    content_type = Column(String(30), nullable=False, index=True, comment="内容类型")
    title = Column(String(300), nullable=False, comment="标题")
    summary = Column(Text, nullable=False, comment="摘要")
    heat_score = Column(Float, default=0.0, comment="热度分")
    heat_reason = Column(Text, default="", comment="热度原因")
    data_points_json = Column(Text, default="[]", comment="数据点 JSON")
    structure_tags_json = Column(Text, default="[]", comment="[已废弃] 结构标签 JSON - 请使用 project_tags_json")
    style_tags_json = Column(Text, default="[]", comment="[已废弃] 风格标签 JSON - 请使用 project_tags_json")
    project_fit_tags_json = Column(Text, default="[]", comment="[已废弃] 项目适配标签 JSON - 请使用 project_tags_json")
    project_tags_json = Column(Text, default="[]", comment="项目统一标签 JSON（合并 structure/style/project_fit）")
    selection_score = Column(Float, default=0.0, index=True, comment="入库筛选分")
    status = Column(String(20), default="candidate", index=True, comment="状态: candidate/approved/rejected")
    citations_json = Column(Text, default="[]", comment="引用链接 JSON")
    raw_payload_json = Column(Text, default="{}", comment="原始精炼结果 JSON")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
