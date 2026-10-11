"""Knowledge chunk model for durable RAG-ready text slices."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from app.database import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "chunk_index", name="uq_knowledge_chunk_source_index"),
        Index("idx_knowledge_chunk_source", "source_type", "source_id", "status"),
        Index("idx_knowledge_chunk_hash", "chunk_hash"),
        Index("idx_knowledge_chunk_updated", "updated_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_type = Column(String(30), nullable=False, index=True, comment="Source doc type: rule/material/project/skill")
    source_id = Column(String(500), nullable=False, index=True, comment="Stable source document id")
    source_path = Column(Text, default="", comment="Optional library or workspace path")
    chunk_index = Column(Integer, nullable=False, default=0, comment="0-based chunk position within source")
    chunk_hash = Column(String(64), nullable=False, index=True, comment="SHA256 hash of normalized chunk content")
    title = Column(String(500), default="", comment="Source or chunk title")
    content = Column(Text, nullable=False, comment="Chunk content")
    content_chars = Column(Integer, default=0, comment="Character count for quick diagnostics")
    chunker = Column(String(50), default="builtin", comment="Chunker backend used to produce this row")
    metadata_json = Column(Text, default="{}", comment="Chunk metadata JSON")
    embedding_json = Column(Text, default="", comment="Reserved local embedding/vector metadata JSON")
    status = Column(String(20), nullable=False, default="active", index=True, comment="active/archived")
    created_at = Column(DateTime, default=datetime.now, comment="Created at")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="Updated at")
