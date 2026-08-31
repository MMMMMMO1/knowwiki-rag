"""
Pydantic schemas for API request/response models.
"""

from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, Field


# ============== Folder Schemas ==============

class FolderBase(BaseModel):
    """Base folder schema."""
    title: str
    slug: str
    full_path: str
    sort_order: int = 0

class CreateFolderRequest(BaseModel):
    """Schema for creating a new folder."""
    title: str
    parent_id: Optional[int] = None

class FolderResponse(FolderBase):
    """Folder response schema."""
    id: int
    parent_id: Optional[int] = None

    class Config:
        from_attributes = True


# ============== File Schemas ==============

class FileBase(BaseModel):
    """Base file schema."""
    title: str
    slug: str
    full_path: str
    sort_order: int = 0


class FileResponse(FileBase):
    """File response schema."""
    id: int
    folder_id: Optional[int] = None

    class Config:
        from_attributes = True


class FileWithContent(FileResponse):
    """File response with file content."""
    content: Optional[str] = None
    content_type: Optional[str] = None  # "text" or "base64"


# ============== Tree Schemas ==============

class FolderTreeItem(BaseModel):
    """Folder tree item with nested children and files."""
    id: int
    title: str
    slug: str
    full_path: str
    sort_order: int
    children: List["FolderTreeItem"] = []
    files: List[FileResponse] = []

    class Config:
        from_attributes = True


# ============== Upload Schemas ==============

class UploadResponse(BaseModel):
    """Upload operation response."""
    success: bool
    message: str
    file: Optional[FileResponse] = None


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Error response schema."""
    detail: str


# ============== User / Auth Schemas ==============

class UserBase(BaseModel):
    username: str
    role: Literal["admin", "editor", "reader"]
    is_active: bool

class UserResponse(UserBase):
    id: int

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


# ============== Admin / Dashboard Schemas ==============

class CreateUserAdminRequest(BaseModel):
    username: str
    password: str
    role: Literal["admin", "editor", "reader"] = "reader"
    is_active: bool = True

class UpdateUserAdminRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[Literal["admin", "editor", "reader"]] = None
    is_active: Optional[bool] = None

class DashboardStatsResponse(BaseModel):
    total_folders: int
    total_files: int
    total_users: int
    total_conversations: int
    failed_syncs: int

class ChatSessionAudit(BaseModel):
    session_id: str
    username: str
    user_id: int
    message_count: int
    latest_message_time: datetime

class ChatMessageAudit(BaseModel):
    id: int
    role: str
    content: str
    sources: list[dict] = Field(default_factory=list)
    created_at: datetime

class SyncHistoryItem(BaseModel):
    id: int
    doc_id: str
    file_id: Optional[int] = None
    title: str
    full_path: Optional[str] = None
    storage_key: Optional[str] = None
    status: str
    retry_count: int
    chunk_count: int
    error_message: Optional[str] = None
    content_hash: Optional[str] = None
    queued_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
