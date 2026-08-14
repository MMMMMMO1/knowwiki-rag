"""
RAG 入库单任务处理器 —— 由 Celery worker 调用，处理单个 rag_document。

流水线: 读取 RagDocument → 状态置 processing → 读 S3 → MarkItDown 解析
        → splitter 切分 → embedding → VectorStore 写入 → 状态置 completed / failed。

不再包含无限 while 轮询循环；调度由 Celery + Redis 负责，
本模块只负责"处理一个任务"。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import RagDocument
from rag.embedding import Embedder
from rag.loader import DocumentLoader
from rag.splitter import TextSplitter
from rag.vector_store import VectorStore


# 与 Celery 的 task_time_limit(900s) 对齐：超过该时长的 processing 视为僵尸任务
STALE_PROCESSING_TIMEOUT_SECONDS = 900


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RetryableIndexingError(Exception):
    """可重试的入库错误（网络抖动、S3 暂不可用、embedding API 限流等）。

    抛出此异常的任务会由 Celery 在延迟后自动重试。
    """


# 匹配常见的密钥形态，用于从错误信息中脱敏（避免 API Key 写入日志 / DB）。
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9._-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
]


def sanitize_error_message(message: str) -> str:
    """脱敏错误信息，移除可能包含的 API Key / Bearer token。"""
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("***", message)
    return message


class RagIndexingProcessor:
    """处理单个 RAG 入库任务。

    用法（由 Celery task 调用）:
        processor = RagIndexingProcessor()
        await processor.process(rag_document_id)
    """

    async def process(self, rag_document_id: int) -> None:
        """执行完整 RAG 流水线，更新 RagDocument 状态。

        成功: status=completed，chunk_count 已写入，completed_at 已记录。
        失败: status=failed，error_message 已写入（脱敏）、retry_count +1、failed_at 已记录，
              并重新抛出异常（RetryableIndexingError 会触发 Celery 重试）。
        """
        async with AsyncSessionLocal() as db:
            doc = await self._load_document(db, rag_document_id)
            if doc is None:
                return

            # 状态置 processing
            doc.status = "processing"
            doc.processing_started_at = _utcnow()
            doc.error_message = None
            await db.commit()

            try:
                await self._run_pipeline(db, doc)
                doc.status = "completed"
                doc.error_message = None
                doc.completed_at = _utcnow()
                doc.failed_at = None
                await db.commit()
            except Exception as exc:
                # 失败：回滚当前事务，写 failed + 脱敏错误
                await db.rollback()
                await self._mark_failed(rag_document_id, sanitize_error_message(str(exc)))
                # 重新抛出，让上层（Celery task）决定是否重试
                raise

    async def _load_document(
        self, db: AsyncSession, rag_document_id: int
    ) -> RagDocument | None:
        """读取 RagDocument；不存在则静默返回 None。"""
        result = await db.execute(
            select(RagDocument).where(RagDocument.id == rag_document_id)
        )
        return result.scalar_one_or_none()

    async def _mark_failed(self, rag_document_id: int, message: str) -> None:
        """把 RagDocument 标记为 failed：写入脱敏错误、retry_count +1、failed_at。"""
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RagDocument)
                .where(RagDocument.id == rag_document_id)
                .values(
                    status="failed",
                    error_message=message,
                    failed_at=_utcnow(),
                    retry_count=RagDocument.retry_count + 1,
                )
            )
            await db.commit()

    async def _run_pipeline(self, db: AsyncSession, doc: RagDocument) -> None:
        """加载 → 解析 → 切分 → 嵌入 → 写入。"""
        # 1. 从 S3/RustFS 读原始字节
        content_bytes = await self._load_raw_bytes(db, doc)

        # 2. MarkItDown 统一解析
        loader = DocumentLoader()
        document = loader.load_bytes(
            file_name=doc.title,
            content=content_bytes,
            metadata={"file_id": doc.file_id},
        )

        # 3. 空文本检测（不可重试）
        if not document.content or not document.content.strip():
            raise ValueError("文档内容为空，无法索引")

        # 4. 计算 content_hash
        doc.content_hash = hashlib.sha256(
            document.content.encode("utf-8")
        ).hexdigest()

        # 5. 清理旧 chunks（支持重复处理 / 重新上传）
        store = VectorStore(db)
        await store.delete_by_document(doc)

        # 6. splitter → embedder → vector_store
        splitter = TextSplitter()
        embedder = Embedder()
        chunks = splitter.split(document)
        vectors = await embedder.embed(chunks)
        await store.insert(doc, chunks, vectors)

    async def _load_raw_bytes(self, db: AsyncSession, doc: RagDocument) -> bytes:
        """从 S3 读取文件原始字节。"""
        from app.models import File
        from app.core.storage import get_file_content

        result = await db.execute(select(File).where(File.id == doc.file_id))
        file = result.scalar_one_or_none()
        if not file:
            raise ValueError(f"Wiki 文件不存在: file_id={doc.file_id}")

        content_bytes = await get_file_content(file.storage_key)
        if content_bytes is None:
            raise RetryableIndexingError(
                f"S3 文件为空或不存在: {file.storage_key}"
            )
        return content_bytes


async def reset_stale_processing_documents() -> int:
    """把超时的 processing 状态文档重置为 pending。

    只重置 processing_started_at 早于阈值（或为 NULL）的任务，
    避免误伤正在被 rag-worker 处理中的任务。
    用于 worker 重启 / 部署后恢复：崩溃遗留的任务会被重置回 pending。
    """
    cutoff = _utcnow() - timedelta(seconds=STALE_PROCESSING_TIMEOUT_SECONDS)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(RagDocument)
            .where(RagDocument.status == "processing")
            .where(
                or_(
                    RagDocument.processing_started_at.is_(None),
                    RagDocument.processing_started_at < cutoff,
                )
            )
            .values(
                status="pending",
                error_message=None,
                processing_started_at=None,
            )
        )
        await db.commit()
        return result.rowcount or 0


async def mark_rag_document_failed(rag_document_id: int, message: str) -> None:
    """把 RagDocument 标记为 failed（供 Celery 投递失败等场景使用）。"""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(RagDocument)
            .where(RagDocument.id == rag_document_id)
            .values(
                status="failed",
                error_message=sanitize_error_message(message),
                failed_at=_utcnow(),
                retry_count=RagDocument.retry_count + 1,
            )
        )
        await db.commit()
