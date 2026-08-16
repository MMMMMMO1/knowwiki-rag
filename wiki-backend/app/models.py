from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, backref
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class Folder(Base):
    """
    Folder model representing directories in the wiki structure.
    
    Uses a self-referential relationship to build the directory tree.
    """
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    full_path = Column(String(500), unique=True, index=True)
    sort_order = Column(Integer, default=0)

    # Self-referential relationship for parent-child hierarchy
    children = relationship(
        "Folder",
        backref=backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    
    # Relationship to files inside this folder
    files = relationship(
        "File",
        back_populates="folder",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Folder(id={self.id}, title='{self.title}', full_path='{self.full_path}')>"


class File(Base):
    """
    File model representing objects pointing to S3 storage.
    """
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    full_path = Column(String(500), unique=True, index=True)
    storage_key = Column(String(500), unique=True, nullable=False)
    sort_order = Column(Integer, default=0)

    folder = relationship("Folder", back_populates="files")

    def __repr__(self) -> str:
        return f"<File(id={self.id}, title='{self.title}', storage_key='{self.storage_key}')>"


class User(Base):
    """
    User model for authentication and role-based access.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="reader")  # "admin", "editor", "reader"
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class ChatLog(Base):
    """
    ChatLog model for storing user chat history.
    """
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

    def __repr__(self) -> str:
        return f"<ChatLog(id={self.id}, user_id={self.user_id}, role='{self.role}')>"


# ── RAG 向量存储模型 ──────────────────────────────────────────────


class RagDocument(Base):
    """RAG 文档处理记录 —— 任务状态台账。

    状态机: pending → processing → completed | failed
    - pending: 已入队，等待 worker 消费
    - processing: worker 正在处理
    - completed: 索引完成
    - failed: 失败，可手动重试

    该表只负责业务可观测性（状态、错误、分块数、哈希、时间戳），
    任务调度由 Redis + Celery 负责，两者解耦。
    """

    __tablename__ = "rag_documents"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True, index=True)
    doc_id = Column(String(36), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    content_hash = Column(String(64), nullable=True)
    # Namespace tag written at ingest time; retrieval filters on it for isolation.
    workspace_id = Column(String(100), nullable=False, default="default", index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    # 队列时间戳
    queued_at = Column(DateTime(timezone=True), nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    file = relationship("File")
    chunks = relationship("RagChunk", back_populates="document", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<RagDocument(id={self.id}, title='{self.title}', status='{self.status}')>"


class RagChunk(Base):
    """RAG 文本块 —— 存储切分后的文本片段及其向量。

    注意：embedding 列固定为 1024 维（Vector(1024)）。
    这与配置项 VECTOR_DIM=1024 和默认 embedding 模型 text-embedding-v3 绑定。
    若未来更换 embedding 模型，必须同步修改这里的 Vector 维度、
    VECTOR_DIM 配置，并重建 rag_chunks 表（pgvector 列维度不可直接变更）。
    """

    __tablename__ = "rag_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(36), unique=True, nullable=False, index=True)
    text = Column(Text, nullable=False)
    # 应用层分词后的文本（空格分隔），供 tsvector 全文索引做关键词检索。
    # 原始中文默认分词器切不动，所以由 Python jieba 切好后落库。
    search_text = Column(Text, nullable=True)
    # Denormalized namespace copied from RagDocument; lets pgvector filter without joins.
    workspace_id = Column(String(100), nullable=False, default="default", index=True)
    embedding = Column(Vector(1024), nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("RagDocument", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<RagChunk(id={self.id}, chunk_id='{self.chunk_id[:8]}...')>"


class Memory(Base):
    """Long-term memory distilled from conversations, vectorized for recall.

    Unlike ChatLog (working memory, last N turns only), memories persist across
    sessions. Facts are extracted by an LLM after each turn, embedded with the
    same Embedder, and recalled by vector search scoped to user + workspace.
    """

    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(100), nullable=False, default="default", index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=True)
    importance = Column(Float, nullable=False, default=0.5)
    source_session_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")

    def __repr__(self) -> str:
        return f"<Memory(id={self.id}, user_id={self.user_id}, workspace_id='{self.workspace_id}')>"
