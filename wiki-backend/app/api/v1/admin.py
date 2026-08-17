"""
Admin API endpoints.

Endpoints:
- POST /api/v1/admin/upload - Upload a file
- DELETE /api/v1/admin/delete/{item_type}/{item_id} - Delete a file or folder

All endpoints require Bearer token authentication.
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_admin_token
from app.crud import get_folder_by_id, get_file_by_id, get_file_by_full_path, get_folder_by_full_path, create_file, delete_folder, delete_file_record, create_folder
from app.scanner import normalize_slug, normalize_title, extract_sort_order
from sqlalchemy import select, func, desc
from app.models import User, ChatLog, Folder, File
from app.core.security import get_password_hash
from app.schemas import (
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

router = APIRouter(prefix="/admin", tags=["admin"])


async def _list_files_under_folder(db: AsyncSession, folder_full_path: str) -> list:
    """按 Wiki 路径找出文件夹下所有文件。"""
    from sqlalchemy import or_
    result = await db.execute(
        select(File).where(
            or_(
                File.full_path.like(f"{folder_full_path}/%"),
                File.storage_key.like(f"{folder_full_path}/%"),
            )
        )
    )
    return list(result.scalars().all())





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
    file: UploadFile = FastAPIFile(...),
    folder_id: int | None = Form(None),
    overwrite: bool = Form(False),
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """
    Upload a file to the wiki.

    **Requires Bearer token authentication.**

    - **file**: File to upload (.md, .html, .docx, .txt, .pdf)
    - **folder_id**: Optional parent folder ID
    - **overwrite**: If true, overwrite the existing file with the same path
      and re-enqueue RAG indexing (default false).

    The file will be saved to S3 and a file record will be created.
    Knowledge sync is scheduled asynchronously after the Wiki write succeeds.
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
    if existing and not overwrite:
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
    
    if existing:
        # 覆盖：保留原 File 记录，更新必要字段；RAG 记录由 IngestService 幂等重置，
        # 旧 chunks 由 worker 入库流水线在写入前清理（delete_by_document）。
        file_node = existing
        file_node.title = normalize_title(filename)
        file_node.slug = slug
        file_node.storage_key = storage_key
        file_node.sort_order = extract_sort_order(filename)
        file_node.folder_id = folder_id
    else:
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

    # 创建或重置 RAG 索引记录（幂等，不执行实际解析/向量化）
    from rag.ingest_service import IngestService
    rag_service = IngestService(db)
    rag_doc = await rag_service.ingest(file_id=file_node.id)

    await db.commit()

    # 投递 Celery 入库任务到 Redis，由 rag-worker 异步消费
    from rag.tasks import enqueue_rag_document_task
    queued = enqueue_rag_document_task(rag_doc.id)
    if queued:
        upload_message = (
            "File overwritten and RAG indexing task queued."
            if overwrite
            else f"File uploaded successfully: {full_path}. RAG indexing task queued."
        )
    else:
        from rag.task_worker import mark_rag_document_failed
        await mark_rag_document_failed(rag_doc.id, "Celery 任务投递失败（Redis 不可用）")
        upload_message = (
            f"文件覆盖成功，但知识库入队失败: {full_path}"
            if overwrite
            else f"文件上传成功，但知识库入队失败: {full_path}"
        )

    return UploadResponse(
        success=True,
        message=upload_message,
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
    from rag.vector_store import VectorStore

    if item_type == "folder":
        folder = await get_folder_by_id(db, item_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        deleted_path = folder.full_path

        # 1. 删除前先收集子文件 file_ids，并清理 RAG 索引。
        #    必须在删文件之前清理：rag_documents.file_id 外键是 ON DELETE SET NULL，
        #    若先删文件，file_id 会被置为 NULL，就再也找不到对应的 RAG 记录了。
        child_files = await _list_files_under_folder(db, deleted_path)
        child_file_ids = [f.id for f in child_files]
        rag_store = VectorStore(db)
        await rag_store.delete_by_file_ids(child_file_ids)

        # 2. 删除 S3 目录
        if delete_physical:
            try:
                await s3_delete_directory(deleted_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"S3 Delete failed: {e}")

        # 3. 删除 folder（ORM cascade 同时删除子文件）
        await delete_folder(db, folder)

    elif item_type == "file":
        file_obj = await get_file_by_id(db, item_id)
        if not file_obj:
            raise HTTPException(status_code=404, detail="File not found")

        deleted_path = file_obj.full_path

        # 1. 先清理 RAG 索引（同样必须在删文件前）
        rag_store = VectorStore(db)
        await rag_store.delete_by_file_id(item_id)

        # 2. 删除 S3 文件
        if delete_physical and file_obj.storage_key:
            try:
                await s3_delete_file(file_obj.storage_key)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"S3 Delete failed: {e}")

        # 3. 删除文件记录
        await delete_file_record(db, file_obj)

    else:
        raise HTTPException(status_code=400, detail="item_type must be folder or file")

    return {
        "success": True,
        "message": f"Deleted successfully: {deleted_path}. RAG index cleaned.",
        "deleted_path": deleted_path,
        "physical_deleted": delete_physical,
    }


# ============== RAG 知识库状态 ==============

@router.get("/knowledge/status")
async def rag_knowledge_status(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """返回自研 RAG 索引状态统计。"""
    from sqlalchemy import func
    from app.models import RagDocument

    result = await db.execute(
        select(
            RagDocument.status,
            func.count(RagDocument.id).label("count"),
        ).group_by(RagDocument.status)
    )
    status_map = {row.status: row.count for row in result.all()}

    # 取最近一条失败信息
    latest_error_result = await db.execute(
        select(RagDocument.error_message)
        .where(RagDocument.status == "failed")
        .order_by(RagDocument.updated_at.desc())
        .limit(1)
    )
    latest_error = latest_error_result.scalar_one_or_none()

    return {
        "success": True,
        "pending": status_map.get("pending", 0),
        "processing": status_map.get("processing", 0),
        "completed": status_map.get("completed", 0),
        "failed": status_map.get("failed", 0),
        "skipped": status_map.get("skipped", 0),
        "latest_error": latest_error,
    }


@router.post("/knowledge/sync")
async def rag_knowledge_sync(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """把 failed 和 pending 的 RAG 文档重置为 pending 并重新投递 Celery 任务。

    pending 可能因 Redis 重启等原因丢失队列消息，这里一并重新投递；
    processing 正在被 worker 处理，跳过以保护并发，避免重复处理；
    skipped 表示文件已被删除，重试无意义，不处理。
    """
    from datetime import datetime, timezone
    from app.models import RagDocument

    result = await db.execute(
        select(RagDocument).where(RagDocument.status.in_(["failed", "pending"]))
    )
    docs = result.scalars().all()

    now = datetime.now(timezone.utc)
    doc_ids: list[int] = []
    for doc in docs:
        doc.status = "pending"
        doc.error_message = None
        doc.queued_at = now
        doc.processing_started_at = None
        doc.completed_at = None
        doc.failed_at = None
        doc.retry_count = 0  # 手动重试时清零
        doc_ids.append(doc.id)

    await db.commit()

    # 批量重新投递 Celery 任务
    from rag.tasks import enqueue_rag_document_task
    enqueued = 0
    failed_ids: list[int] = []
    for doc_id in doc_ids:
        if enqueue_rag_document_task(doc_id):
            enqueued += 1
        else:
            failed_ids.append(doc_id)

    if failed_ids:
        from rag.task_worker import mark_rag_document_failed
        for doc_id in failed_ids:
            await mark_rag_document_failed(doc_id, "Celery 任务投递失败（Redis 不可用）")

    return {
        "success": True,
        "message": f"Reset {len(docs)} failed/pending documents to pending.",
        "scheduled": len(docs),
        "enqueued": enqueued,
        "failed_enqueue": len(failed_ids),
    }


@router.post("/knowledge/rebuild")
async def rag_knowledge_rebuild(
    force: bool = False,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """扫描 files 表中所有 Wiki 文件，补齐/重建 RAG 入库任务。

    force=False（默认）：
    - 无 RagDocument 的文件：创建记录并投递（created）
    - RagDocument 为 failed/pending：重置为 pending 并重新投递（requeued）
    - RagDocument 为 completed/skipped：跳过（skipped）

    force=True（强制全量重建，用于 metadata/schema 规则升级）：
    - completed/skipped/failed/pending 全部重置为 pending 并重新投递（requeued）

    两种模式下 processing 都跳过（skipped_processing），避免打断正在处理的 worker。
    投递失败：标记 failed 并计入 failed_enqueue。
    """
    from datetime import datetime, timezone
    from app.models import File, RagDocument
    from rag.ingest_service import IngestService
    from rag.tasks import enqueue_rag_document_task
    from rag.task_worker import mark_rag_document_failed

    files_result = await db.execute(select(File).order_by(File.id.asc()))
    files = files_result.scalars().all()

    # 一次性取出所有入库记录，按 file_id 建索引，避免逐文件查询
    docs_result = await db.execute(select(RagDocument))
    docs_by_file_id: dict[int, RagDocument] = {}
    for doc in docs_result.scalars().all():
        if doc.file_id is not None and doc.file_id not in docs_by_file_id:
            docs_by_file_id[doc.file_id] = doc

    created = 0
    requeued = 0
    skipped = 0
    skipped_processing = 0
    to_enqueue: list[int] = []

    now = datetime.now(timezone.utc)
    ingest = IngestService(db)

    def _reset_pending(doc: RagDocument) -> None:
        doc.status = "pending"
        doc.error_message = None
        doc.queued_at = now
        doc.processing_started_at = None
        doc.completed_at = None
        doc.failed_at = None
        doc.retry_count = 0

    for file in files:
        doc = docs_by_file_id.get(file.id)
        if doc is None:
            # 无入库记录：创建 pending 记录
            new_doc = await ingest.ingest(file.id)
            to_enqueue.append(new_doc.id)
            created += 1
        elif doc.status == "processing":
            # processing 正在被 worker 处理：两种模式都跳过，保护并发
            skipped_processing += 1
        elif force:
            # 强制重建：completed/skipped/failed/pending 全部重置重新入队
            _reset_pending(doc)
            to_enqueue.append(doc.id)
            requeued += 1
        elif doc.status in ("failed", "pending"):
            # 默认：重置 failed/pending 重新入队
            _reset_pending(doc)
            to_enqueue.append(doc.id)
            requeued += 1
        else:
            # 默认：completed / skipped 不重复处理
            skipped += 1

    await db.commit()

    # 记录已落库后再投递，避免 worker 先于事务提交读到旧状态
    enqueued = 0
    failed_ids: list[int] = []
    for doc_id in to_enqueue:
        if enqueue_rag_document_task(doc_id):
            enqueued += 1
        else:
            failed_ids.append(doc_id)

    if failed_ids:
        for doc_id in failed_ids:
            await mark_rag_document_failed(doc_id, "Celery 任务投递失败（Redis 不可用）")

    return {
        "success": True,
        "message": (
            f"Rebuild finished: forced={force}, created {created}, "
            f"requeued {requeued}, skipped {skipped}, "
            f"skipped_processing {skipped_processing}."
        ),
        "forced": force,
        "created": created,
        "requeued": requeued,
        "skipped": skipped,
        "skipped_processing": skipped_processing,
        "enqueued": enqueued,
        "failed_enqueue": len(failed_ids),
    }


@router.get("/knowledge/files")
async def rag_knowledge_files(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """返回扁平文件列表，附带每个文件的 RAG 索引状态。"""
    from app.models import File, RagDocument

    files_result = await db.execute(select(File).order_by(File.id.asc()))
    files = files_result.scalars().all()

    # 每个 file_id 取最新一条 RagDocument（ingest 幂等保证同一 file_id 不重复）
    docs_result = await db.execute(
        select(RagDocument).order_by(RagDocument.id.desc())
    )
    docs_by_file_id: dict[int, RagDocument] = {}
    for doc in docs_result.scalars().all():
        if doc.file_id is not None and doc.file_id not in docs_by_file_id:
            docs_by_file_id[doc.file_id] = doc

    items = []
    for file in files:
        doc = docs_by_file_id.get(file.id)
        items.append({
            "id": file.id,
            "title": file.title,
            "full_path": file.full_path,
            "storage_key": file.storage_key,
            "rag_status": doc.status if doc else "not_indexed",
            "rag_chunk_count": doc.chunk_count if doc else 0,
            "rag_queued_at": doc.queued_at.isoformat() if doc and doc.queued_at else None,
            "rag_completed_at": doc.completed_at.isoformat() if doc and doc.completed_at else None,
            "rag_failed_at": doc.failed_at.isoformat() if doc and doc.failed_at else None,
            "rag_error_message": doc.error_message if doc else None,
        })

    return {"success": True, "files": items}


@router.post("/knowledge/rebuild-file/{file_id}")
async def rag_rebuild_file(
    file_id: int,
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """重建单个文件的 RAG 索引：复用 IngestService 重置记录并重新入队。"""
    from rag.ingest_service import IngestService
    from rag.tasks import enqueue_rag_document_task
    from rag.task_worker import mark_rag_document_failed

    try:
        service = IngestService(db)
        doc = await service.ingest(file_id=file_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    queued = enqueue_rag_document_task(doc.id)
    if not queued:
        await mark_rag_document_failed(doc.id, "Celery 任务投递失败（Redis 不可用）")
        raise HTTPException(
            status_code=500,
            detail="Celery 任务投递失败（Redis 不可用）",
        )

    return {
        "success": True,
        "message": f"Rebuild queued for file {file_id}.",
        "file_id": file_id,
        "rag_document_id": doc.id,
        "status": doc.status,
    }


# ============== Dashboard Statistics ==============

@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    _: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> DashboardStatsResponse:
    """获取管理员后台的统计数据。"""
    from app.models import RagDocument
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

    # 统计同步失败的任务数量（RagDocument）
    result = await db.execute(
        select(func.count(RagDocument.id))
        .filter(RagDocument.status == "failed")
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
    获取最近的知识库文档同步任务历史记录。

    RagDocument.file_id 可能为空（文件已被删除时 SET NULL），
    此时仍返回该任务自身的 title，full_path/storage_key 为 None。
    """
    from app.models import RagDocument, File

    result = await db.execute(
        select(RagDocument, File)
        .join(File, File.id == RagDocument.file_id, isouter=True)
        .order_by(RagDocument.updated_at.desc())
        .limit(limit)
    )
    rows = result.all()

    items: list[SyncHistoryItem] = []
    for doc, file in rows:
        items.append(
            SyncHistoryItem(
                id=doc.id,
                doc_id=doc.doc_id,
                file_id=doc.file_id,
                title=doc.title,
                full_path=file.full_path if file else None,
                storage_key=file.storage_key if file else None,
                status=doc.status,
                retry_count=doc.retry_count,
                chunk_count=doc.chunk_count,
                error_message=doc.error_message,
                content_hash=doc.content_hash,
                queued_at=doc.queued_at,
                processing_started_at=doc.processing_started_at,
                completed_at=doc.completed_at,
                failed_at=doc.failed_at,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
        )
    return items
