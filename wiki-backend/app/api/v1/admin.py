"""
Admin API endpoints.

Endpoints:
- POST /api/v1/admin/upload - Upload a file
- DELETE /api/v1/admin/delete/{item_type}/{item_id} - Delete a file or folder

All endpoints require Bearer token authentication.
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File as FastAPIFile, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_admin_token
from app.crud import get_folder_by_id, get_file_by_id, get_file_by_full_path, get_folder_by_full_path, create_file, delete_folder, delete_file_record, create_folder
from app.scanner import normalize_slug, normalize_title, extract_sort_order
from sqlalchemy import select, update, delete, func, desc
from app.models import User, ChatLog, Folder, File, AnythingLLMDocumentSync
from app.core.security import get_password_hash
from app.schemas import (
    AnythingLLMSyncStatusResponse,
    AnythingLLMSyncTriggerResponse,
    UploadResponse,
    FileResponse,
    ErrorResponse,
    CreateFolderRequest,
    FolderResponse,
    CreateUserAdminRequest,
    UpdateUserAdminRequest,
    DashboardStatsResponse,
    ChatSessionAudit,
    ChatMessageAudit,
    SyncHistoryItem,
    UserResponse,
)
from app.anythingllm_sync import (
    calculate_content_hash,
    create_upload_sync_record,
    get_sync_status,
    list_files_under_folder,
    list_runnable_sync_ids,
    mark_file_pending_delete,
    process_sync_record,
    process_sync_records,
)

router = APIRouter(prefix="/admin", tags=["admin"])





@router.post("/folder", response_model=FolderResponse)
async def add_folder(
    request: CreateFolderRequest,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> FolderResponse:
    """Create a new folder in the database."""
    slug = normalize_slug(request.title)
    sort_order = extract_sort_order(request.title)
    title = normalize_title(request.title)

    parent_id = request.parent_id
    if parent_id is not None and parent_id <= 0:
        parent_id = None

    parent_folder = None
    parent_full_path = ""
    if parent_id:
        parent_folder = await get_folder_by_id(db, parent_id)
        if not parent_folder:
            raise HTTPException(status_code=404, detail=f"Parent folder not found: {parent_id}")
        parent_full_path = parent_folder.full_path

    full_path = f"{parent_full_path}/{slug}" if parent_full_path else slug

    # Check if a folder with the same full_path exists
    existing = await get_folder_by_full_path(db, full_path)
    if existing:
        raise HTTPException(status_code=400, detail=f"Folder already exists: {full_path}")

    new_folder = await create_folder(
        db=db,
        parent_id=parent_id,
        title=title,
        slug=slug,
        full_path=full_path,
        sort_order=sort_order,
    )
    
    return FolderResponse.model_validate(new_folder)


@router.post(
    "/upload",
    response_model=UploadResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = FastAPIFile(...),
    folder_id: int | None = Form(None),
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """
    Upload a file to the wiki.
    
    **Requires Bearer token authentication.**
    
    - **file**: File to upload (.md, .html, .docx, .txt, .pdf)
    - **folder_id**: Optional parent folder ID
    
    The file will be saved to S3 and a file record will be created.
    AnythingLLM sync is scheduled asynchronously after the Wiki write succeeds.
    """
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {".md", ".html", ".docx", ".txt", ".pdf"}
    
    # Validate file type
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )
    
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    
    # Normalize: treat folder_id=0 as None (root level)
    if folder_id is not None and folder_id <= 0:
        folder_id = None
    
    # Determine parent path
    parent_folder = None
    parent_full_path = ""
    
    if folder_id:
        parent_folder = await get_folder_by_id(db, folder_id)
        if not parent_folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent folder not found: {folder_id}",
            )
        parent_full_path = parent_folder.full_path
    
    # Build file paths
    filename = file.filename
    slug = normalize_slug(filename)
    full_path = f"{parent_full_path}/{slug}" if parent_full_path else slug
    storage_key = f"{parent_full_path}/{filename}" if parent_full_path else filename
    
    # Check if file already exists in db
    existing = await get_file_by_full_path(db, full_path)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File already exists: {full_path}",
        )
    
    # 先读取上传内容，后续同时用于写入 Wiki 存储和生成同步哈希。
    from app.core.storage import save_file_content
    try:
        content = await file.read()
        success = await save_file_content(storage_key, content)
        if not success:
            raise Exception("S3 upload failed")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file to S3: {str(e)}",
        )
    
    # Create file db record
    file_node = await create_file(
        db=db,
        folder_id=folder_id,
        title=normalize_title(filename),
        slug=slug,
        full_path=full_path,
        storage_key=storage_key,
        sort_order=extract_sort_order(filename),
    )

    sync_record = await create_upload_sync_record(
        db=db,
        file_obj=file_node,
        content_hash=calculate_content_hash(content),
    )
    background_tasks.add_task(process_sync_record, sync_record.id)
    
    return UploadResponse(
        success=True,
        message=f"File uploaded successfully: {full_path}. AnythingLLM sync scheduled.",
        file=FileResponse(
            id=file_node.id,
            folder_id=file_node.folder_id,
            title=file_node.title,
            slug=file_node.slug,
            full_path=file_node.full_path,
            sort_order=file_node.sort_order,
        ),
    )


@router.delete(
    "/delete/{item_type}/{item_id}",
    responses={404: {"model": ErrorResponse}},
)
async def delete_item(
    background_tasks: BackgroundTasks,
    item_type: Literal["folder", "file"],
    item_id: int,
    delete_physical: bool = True,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Delete a file or folder node.
    
    **Requires Bearer token authentication.**
    
    - **item_type**: "folder" or "file"
    - **item_id**: ID of the item to delete
    - **delete_physical**: If true, also delete the physical file/folder (default: true)
    
    Note: Deleting a folder will also delete all its children.
    """
    from app.core.storage import delete_file as s3_delete_file, delete_directory as s3_delete_directory
    sync_ids: list[int] = []
    
    if item_type == "folder":
        folder = await get_folder_by_id(db, item_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        
        deleted_path = folder.full_path

        # 删除文件夹前先为其中已同步到 AnythingLLM 的文件保留远端 name。
        for file_obj in await list_files_under_folder(db, folder.full_path):
            sync_record = await mark_file_pending_delete(db, file_obj)
            if sync_record:
                sync_ids.append(sync_record.id)
        
        if delete_physical:
            try:
                await s3_delete_directory(deleted_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"S3 Delete failed: {e}")
                
        await delete_folder(db, folder)
        
    elif item_type == "file":
        file_obj = await get_file_by_id(db, item_id)
        if not file_obj:
            raise HTTPException(status_code=404, detail="File not found")
            
        deleted_path = file_obj.full_path

        sync_record = await mark_file_pending_delete(db, file_obj)
        if sync_record:
            sync_ids.append(sync_record.id)
        
        if delete_physical and file_obj.storage_key:
            try:
                await s3_delete_file(file_obj.storage_key)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"S3 Delete failed: {e}")
                
        await delete_file_record(db, file_obj)
        
    else:
        raise HTTPException(status_code=400, detail="item_type must be folder or file")

    for sync_id in sync_ids:
        background_tasks.add_task(process_sync_record, sync_id)
            
    return {
        "success": True,
        "message": f"Deleted successfully: {deleted_path}. AnythingLLM delete sync scheduled.",
        "deleted_path": deleted_path,
        "physical_deleted": delete_physical,
    }


@router.get("/anythingllm/status", response_model=AnythingLLMSyncStatusResponse)
async def anythingllm_status(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> AnythingLLMSyncStatusResponse:
    """返回 AnythingLLM 后台同步状态统计。"""
    status_data = await get_sync_status(db)
    return AnythingLLMSyncStatusResponse(success=True, **status_data)


@router.post("/anythingllm/sync", response_model=AnythingLLMSyncTriggerResponse)
async def trigger_anythingllm_sync(
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> AnythingLLMSyncTriggerResponse:
    """手动触发 pending/failed 同步记录重试。"""
    sync_ids = await list_runnable_sync_ids(db)
    background_tasks.add_task(process_sync_records, sync_ids)
    return AnythingLLMSyncTriggerResponse(
        success=True,
        message=f"Scheduled {len(sync_ids)} AnythingLLM sync records.",
        scheduled=len(sync_ids),
    )


# ============== Dashboard Statistics ==============

@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> DashboardStatsResponse:
    """获取管理员后台的统计数据。"""
    # 统计文件夹数量
    result = await db.execute(select(func.count(Folder.id)))
    total_folders = result.scalar() or 0

    # 统计文件数量
    result = await db.execute(select(func.count(File.id)))
    total_files = result.scalar() or 0

    # 统计用户数量
    result = await db.execute(select(func.count(User.id)))
    total_users = result.scalar() or 0

    # 统计会话数量 (根据 session_id 分组统计)
    result = await db.execute(select(func.count(func.distinct(ChatLog.session_id))))
    total_conversations = result.scalar() or 0

    # 统计同步失败的任务数量
    result = await db.execute(
        select(func.count(AnythingLLMDocumentSync.id))
        .filter(AnythingLLMDocumentSync.status == "failed")
    )
    failed_syncs = result.scalar() or 0

    return DashboardStatsResponse(
        total_folders=total_folders,
        total_files=total_files,
        total_users=total_users,
        total_conversations=total_conversations,
        failed_syncs=failed_syncs,
    )


# ============== User Management ==============

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    """列出系统中的所有用户账户。"""
    result = await db.execute(select(User).order_by(User.id.asc()))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.post("/users", response_model=UserResponse)
async def create_user(
    request: CreateUserAdminRequest,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """管理员创建一个新用户账户。"""
    # 检查用户名是否重复
    existing = await db.execute(select(User).filter(User.username == request.username))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建用户记录
    hashed_pw = get_password_hash(request.password)
    new_user = User(
        username=request.username,
        hashed_password=hashed_pw,
        role=request.role,
        is_active=request.is_active,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return UserResponse.model_validate(new_user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    request: UpdateUserAdminRequest,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """管理员更新某个用户账户（更新密码、角色、或禁用启用状态）。"""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if request.role is not None:
        user.role = request.role
    if request.is_active is not None:
        user.is_active = request.is_active
    if request.password is not None and request.password.strip() != "":
        user.hashed_password = get_password_hash(request.password)

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """管理员删除某个用户账户。"""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.delete(user)
    await db.commit()
    return {"success": True, "message": "用户删除成功"}


# ============== Chat logs Audit ==============

@router.get("/chat-sessions", response_model=list[ChatSessionAudit])
async def list_chat_sessions(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionAudit]:
    """
    列出所有用户的对话会话，按最新活动时间倒序排序。
    """
    stmt = (
        select(
            ChatLog.session_id,
            User.username,
            ChatLog.user_id,
            func.count(ChatLog.id).label("message_count"),
            func.max(ChatLog.created_at).label("latest_message_time"),
        )
        .join(User, ChatLog.user_id == User.id)
        .group_by(ChatLog.session_id, User.username, ChatLog.user_id)
        .order_by(desc("latest_message_time"))
    )

    result = await db.execute(stmt)
    rows = result.all()

    sessions = []
    for r in rows:
        sessions.append(
            ChatSessionAudit(
                session_id=r.session_id,
                username=r.username,
                user_id=r.user_id,
                message_count=r.message_count,
                latest_message_time=r.latest_message_time,
            )
        )
    return sessions


@router.get("/chat-sessions/{session_id}/messages", response_model=list[ChatMessageAudit])
async def get_session_messages(
    session_id: str,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageAudit]:
    """
    获取指定会话的完整对话日志，供管理员审计。
    """
    result = await db.execute(
        select(ChatLog)
        .filter(ChatLog.session_id == session_id)
        .order_by(ChatLog.created_at.asc())
    )
    logs = result.scalars().all()

    return [
        ChatMessageAudit(
            id=log.id,
            role=log.role,
            content=log.content,
            created_at=log.created_at,
        )
        for log in logs
    ]


# ============== Sync History ==============

@router.get("/sync-history", response_model=list[SyncHistoryItem])
async def get_sync_history(
    limit: int = 50,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> list[SyncHistoryItem]:
    """
    获取最近的 AnythingLLM 文档同步任务历史记录。
    """
    result = await db.execute(
        select(AnythingLLMDocumentSync)
        .order_by(AnythingLLMDocumentSync.updated_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return [SyncHistoryItem.model_validate(r) for r in records]
