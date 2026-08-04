from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship, backref

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


class AnythingLLMDocumentSync(Base):
    """
    AnythingLLM 同步记录。

    这张表独立于 files 表保存远端文档名，避免 Wiki 文件删除后丢失
    AnythingLLM 删除所需的 name/location。
    """
    __tablename__ = "anythingllm_document_syncs"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True, index=True)
    full_path = Column(String(500), nullable=False, index=True)
    storage_key = Column(String(500), nullable=False)
    title = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=True)
    anythingllm_name = Column(String(1000), nullable=True)
    operation = Column(String(32), nullable=False, default="upload", index=True)
    status = Column(String(32), nullable=False, default="pending_upload", index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    file = relationship("File")


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
    ChatLog model for storing user chat history with AnythingLLM.
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
