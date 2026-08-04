"""
AnythingLLM 同步服务。

本模块只通过 AnythingLLM 真实 HTTP API 工作，不依赖 SDK，也不包装虚构客户端。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.storage import get_file_content
from app.models import AnythingLLMDocumentSync, File

STATUS_PENDING_UPLOAD = "pending_upload"
STATUS_PENDING_DELETE = "pending_delete"
STATUS_SYNCING_UPLOAD = "syncing_upload"
STATUS_SYNCING_DELETE = "syncing_delete"
STATUS_SYNCED = "synced"
STATUS_DELETED = "deleted"
STATUS_FAILED = "failed"

OPERATION_UPLOAD = "upload"
OPERATION_DELETE = "delete"


def calculate_content_hash(content: bytes) -> str:
    """计算文件内容哈希，用于识别同路径文件是否发生过内容变化。"""
    return hashlib.sha256(content).hexdigest()


def _anythingllm_api_base() -> str:
    """统一拼出 AnythingLLM API 根路径，避免调用处重复处理斜杠。"""
    return f"{settings.ANYTHINGLLM_API_URL.rstrip('/')}/api"


def _anythingllm_headers() -> dict[str, str]:
    """构造 AnythingLLM 认证请求头，API Key 只从后端环境变量读取。"""
    if not settings.ANYTHINGLLM_API_KEY:
        raise RuntimeError("缺少后端环境变量 ANYTHINGLLM_API_KEY")
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {settings.ANYTHINGLLM_API_KEY}",
    }


def _workspace_slug() -> str:
    """读取需要嵌入文档的 AnythingLLM 工作区 slug。"""
    if not settings.ANYTHINGLLM_WORKSPACE_SLUG:
        raise RuntimeError("缺少后端环境变量 ANYTHINGLLM_WORKSPACE_SLUG")
    return settings.ANYTHINGLLM_WORKSPACE_SLUG


def _extract_remote_document_name(payload: Any) -> str:
    """
    从上传响应中提取后续 update-embeddings/remove-documents 需要的文档名。

    AnythingLLM 版本之间字段可能略有差异；优先使用 location，因为它通常包含
    custom-documents 前缀，其次回退到 name。
    """
    if not isinstance(payload, dict):
        raise RuntimeError("AnythingLLM 上传响应不是 JSON 对象")

    documents = payload.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, dict):
                continue
            location = document.get("location")
            if isinstance(location, str) and location:
                return location
            name = document.get("name")
            if isinstance(name, str) and name:
                return name

    document = payload.get("document")
    if isinstance(document, dict):
        location = document.get("location")
        if isinstance(location, str) and location:
            return location
        name = document.get("name")
        if isinstance(name, str) and name:
            return name

    raise RuntimeError("AnythingLLM 上传响应中缺少文档 name/location")


def _flatten_remote_documents(payload: Any) -> list[dict[str, Any]]:
    """从 AnythingLLM 文档列表响应中递归提取文件节点，并组装正确的完整路径（如 custom-documents/file.json）。"""
    documents: list[dict[str, Any]] = []

    def walk(value: Any, current_path: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                walk(item, current_path)
            return

        if not isinstance(value, dict):
            return

        name = value.get("name")
        item_type = value.get("type")

        # 确定如果是文件夹，我们需要更新路径前缀
        new_path = current_path
        if item_type == "folder" and isinstance(name, str) and name:
            if name != "documents":
                new_path = f"{current_path}/{name}" if current_path else name

        if isinstance(name, str) and (item_type in (None, "file") or "title" in value):
            # 将文件的 name 组装为包含文件夹的完整 remote_name (例如 custom-documents/file.json)
            # 如果文件名中已经包含了当前路径前缀，则无需重复拼接
            if current_path and name.startswith(f"{current_path}/"):
                full_name = name
            else:
                full_name = f"{current_path}/{name}" if current_path else name
            doc_copy = dict(value)
            doc_copy["name"] = full_name
            documents.append(doc_copy)

        for child_key in ("documents", "items", "files", "children", "localFiles"):
            child_value = value.get(child_key)
            if child_value is not None:
                walk(child_value, new_path)

    walk(payload)
    return documents


def _document_url_filename(document: dict[str, Any]) -> str:
    """从 AnythingLLM 文档 url 字段中提取原始文件名。"""
    url = document.get("url")
    if not isinstance(url, str) or not url:
        return ""
    parsed = urlparse(url)
    return unquote(Path(parsed.path).name)


def _find_existing_remote_document(
    documents: list[dict[str, Any]],
    *,
    remote_name: str | None,
    filename: str,
) -> str | None:
    """
    在上传前查找已存在的 AnythingLLM 文档。

    优先匹配同步表已保存的远端 name；如果之前上传已成功但本地记录尚未落库，
    再用 title/url 文件名兜底匹配，避免重试时重复上传。
    """
    if remote_name:
        for document in documents:
            name = document.get("name")
            if isinstance(name, str) and name == remote_name:
                return name

    candidates: list[str] = []
    for document in documents:
        title = document.get("title")
        name = document.get("name")
        if not isinstance(name, str) or not name:
            continue
        if title == filename or _document_url_filename(document) == filename:
            candidates.append(name)

    return candidates[0] if candidates else None


async def create_upload_sync_record(
    db: AsyncSession,
    file_obj: File,
    content_hash: str,
) -> AnythingLLMDocumentSync:
    """创建或更新上传同步记录，保证 Wiki 入库后不会阻塞等待 AnythingLLM。"""
    result = await db.execute(
        select(AnythingLLMDocumentSync).where(
            or_(
                AnythingLLMDocumentSync.file_id == file_obj.id,
                AnythingLLMDocumentSync.full_path == file_obj.full_path,
            )
        )
    )
    sync_record = result.scalar_one_or_none()

    if not sync_record:
        sync_record = AnythingLLMDocumentSync(
            file_id=file_obj.id,
            full_path=file_obj.full_path,
            storage_key=file_obj.storage_key,
            title=file_obj.title,
        )
        db.add(sync_record)

    sync_record.file_id = file_obj.id
    sync_record.full_path = file_obj.full_path
    sync_record.storage_key = file_obj.storage_key
    sync_record.title = file_obj.title
    sync_record.content_hash = content_hash
    sync_record.operation = OPERATION_UPLOAD
    sync_record.status = STATUS_PENDING_UPLOAD
    sync_record.retry_count = 0
    sync_record.last_error = None

    await db.commit()
    await db.refresh(sync_record)
    return sync_record


async def mark_file_pending_delete(
    db: AsyncSession,
    file_obj: File,
) -> AnythingLLMDocumentSync | None:
    """
    在删除 Wiki 文件前保留远端 AnythingLLM 文档名。

    如果文件从未成功同步到 AnythingLLM，远端无需删除，直接返回 None。
    """
    result = await db.execute(
        select(AnythingLLMDocumentSync).where(
            or_(
                AnythingLLMDocumentSync.file_id == file_obj.id,
                AnythingLLMDocumentSync.full_path == file_obj.full_path,
            )
        )
    )
    sync_record = result.scalar_one_or_none()
    if not sync_record:
        return None

    if not sync_record.anythingllm_name:
        sync_record.file_id = None
        sync_record.operation = OPERATION_DELETE
        sync_record.status = STATUS_DELETED
        sync_record.last_error = None
        await db.commit()
        return None

    sync_record.file_id = None
    sync_record.full_path = file_obj.full_path
    sync_record.storage_key = file_obj.storage_key
    sync_record.title = file_obj.title
    sync_record.operation = OPERATION_DELETE
    sync_record.status = STATUS_PENDING_DELETE
    sync_record.retry_count = 0
    sync_record.last_error = None

    await db.commit()
    await db.refresh(sync_record)
    return sync_record


async def list_files_under_folder(db: AsyncSession, folder_full_path: str) -> list[File]:
    """按 Wiki 逻辑路径找出文件夹下所有文件，供文件夹删除前生成远端删除任务。"""
    result = await db.execute(
        select(File).where(
            or_(
                File.full_path.like(f"{folder_full_path}/%"),
                File.storage_key.like(f"{folder_full_path}/%"),
            )
        )
    )
    return list(result.scalars().all())


async def list_runnable_sync_ids(db: AsyncSession) -> list[int]:
    """找出可以立即执行或重试的同步记录。"""
    result = await db.execute(
        select(AnythingLLMDocumentSync.id).where(
            AnythingLLMDocumentSync.status.in_(
                [STATUS_PENDING_UPLOAD, STATUS_PENDING_DELETE, STATUS_FAILED]
            ),
            AnythingLLMDocumentSync.retry_count < settings.ANYTHINGLLM_SYNC_MAX_RETRIES,
        )
    )
    return list(result.scalars().all())


async def get_sync_status(db: AsyncSession) -> dict[str, Any]:
    """统计同步状态，供管理接口展示后台同步积压和失败原因。"""
    counts_result = await db.execute(
        select(AnythingLLMDocumentSync.status, func.count(AnythingLLMDocumentSync.id))
        .group_by(AnythingLLMDocumentSync.status)
    )
    counts = {status: count for status, count in counts_result.all()}

    latest_error_result = await db.execute(
        select(AnythingLLMDocumentSync.last_error)
        .where(AnythingLLMDocumentSync.status == STATUS_FAILED)
        .order_by(AnythingLLMDocumentSync.updated_at.desc())
        .limit(1)
    )

    return {
        "pending_upload": counts.get(STATUS_PENDING_UPLOAD, 0),
        "pending_delete": counts.get(STATUS_PENDING_DELETE, 0),
        "processing": counts.get(STATUS_SYNCING_UPLOAD, 0) + counts.get(STATUS_SYNCING_DELETE, 0),
        "failed": counts.get(STATUS_FAILED, 0),
        "synced": counts.get(STATUS_SYNCED, 0),
        "deleted": counts.get(STATUS_DELETED, 0),
        "latest_error": latest_error_result.scalar_one_or_none(),
    }


async def process_sync_record(sync_id: int) -> None:
    """后台处理单条同步记录，内部创建独立数据库会话，避免复用请求会话。"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AnythingLLMDocumentSync).where(AnythingLLMDocumentSync.id == sync_id)
        )
        sync_record = result.scalar_one_or_none()
        if not sync_record:
            return

        if sync_record.retry_count >= settings.ANYTHINGLLM_SYNC_MAX_RETRIES:
            return

        try:
            if sync_record.operation == OPERATION_DELETE:
                sync_record.status = STATUS_SYNCING_DELETE
                await db.commit()
                await _delete_remote_document(sync_record)
                sync_record.status = STATUS_DELETED
            else:
                sync_record.status = STATUS_SYNCING_UPLOAD
                await db.commit()
                await _upload_and_embed_document(sync_record)
                sync_record.status = STATUS_SYNCED

            sync_record.retry_count = 0
            sync_record.last_error = None
            sync_record.synced_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            sync_record.status = STATUS_FAILED
            sync_record.retry_count += 1
            sync_record.last_error = str(exc)
            await db.commit()


async def process_sync_records(sync_ids: Iterable[int]) -> None:
    """顺序处理一批同步记录，便于手动同步接口重试积压任务。"""
    for sync_id in sync_ids:
        await process_sync_record(sync_id)


async def _upload_and_embed_document(sync_record: AnythingLLMDocumentSync) -> None:
    """上传 Wiki 文件到 AnythingLLM 根目录，并嵌入后端配置的工作区。"""
    content = await get_file_content(sync_record.storage_key)
    if content is None:
        raise RuntimeError(f"Wiki 存储中找不到文件: {sync_record.storage_key}")

    filename = Path(sync_record.storage_key).name
    headers = _anythingllm_headers()

    async with httpx.AsyncClient(timeout=60) as http:
        documents_response = await http.get(
            f"{_anythingllm_api_base()}/v1/documents",
            headers=headers,
        )
        documents_response.raise_for_status()
        remote_name = _find_existing_remote_document(
            _flatten_remote_documents(documents_response.json()),
            remote_name=sync_record.anythingllm_name,
            filename=filename,
        )

        if not remote_name:
            upload_response = await http.post(
                f"{_anythingllm_api_base()}/v1/document/upload",
                headers=headers,
                files={"file": (filename, content)},
            )
            upload_response.raise_for_status()
            remote_name = _extract_remote_document_name(upload_response.json())

        embed_response = await http.post(
            f"{_anythingllm_api_base()}/v1/workspace/{_workspace_slug()}/update-embeddings",
            headers={**headers, "Content-Type": "application/json"},
            json={"adds": [remote_name], "deletes": []},
        )
        embed_response.raise_for_status()

    sync_record.anythingllm_name = remote_name


async def _delete_remote_document(sync_record: AnythingLLMDocumentSync) -> None:
    """先取消工作区嵌入，再删除 AnythingLLM 文件。"""
    remote_name = sync_record.anythingllm_name
    if not remote_name:
        return

    headers = _anythingllm_headers()
    async with httpx.AsyncClient(timeout=60) as http:
        documents_response = await http.get(
            f"{_anythingllm_api_base()}/v1/documents",
            headers=headers,
        )
        documents_response.raise_for_status()
        existing_name = _find_existing_remote_document(
            _flatten_remote_documents(documents_response.json()),
            remote_name=remote_name,
            filename=Path(sync_record.storage_key).name,
        )
        if not existing_name:
            return

        unembed_response = await http.post(
            f"{_anythingllm_api_base()}/v1/workspace/{_workspace_slug()}/update-embeddings",
            headers={**headers, "Content-Type": "application/json"},
            json={"adds": [], "deletes": [existing_name]},
        )
        if unembed_response.status_code != 404:
            unembed_response.raise_for_status()

        delete_response = await http.request(
            "DELETE",
            f"{_anythingllm_api_base()}/v1/system/remove-documents",
            headers={**headers, "Content-Type": "application/json"},
            json={"names": [existing_name]},
        )
        if delete_response.status_code != 404:
            delete_response.raise_for_status()
