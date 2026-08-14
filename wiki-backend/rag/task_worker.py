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
from rag.exceptions import RetryableIndexingError
from rag.loader import DocumentLoader
from rag.splitter import TextSplitter
from rag.vector_store import VectorStore


# 与 Celery 的 task_time_limit(900s) 对齐：超过该时长的 processing 视为僵尸任务
STALE_PROCESSING_TIMEOUT_SECONDS = 900


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

    async def process(self, rag_document_id: int) -> str:
        """执行完整 RAG 流水线。

        返回 "completed" / "failed" / "skipped"。
        - completed: 索引完成
        - failed: 最终失败（不可重试），状态已写 failed
        - skipped: 任务不存在或已被处理（重复消息），不重复处理
        可重试错误会抛 RetryableIndexingError（状态已写 failed 并注明将自动重试）。
        """
        # 1. 原子抢占：只允许 pending/failed → processing（防止重复消息并发处理）
        if not await self._claim_processing(rag_document_id):
            return "skipped"

        # 2. 执行流水线
        async with AsyncSessionLocal() as db:
            doc = await self._load_document(db, rag_document_id)
            if doc is None:
                return "skipped"

            try:
                await self._run_pipeline(db, doc)
                doc.status = "completed"
                doc.error_message = None
                doc.completed_at = _utcnow()
                doc.failed_at = None
                await db.commit()
                return "completed"
            except Exception as exc:
                # 失败：回滚当前事务，写 failed + 脱敏错误（可重试则注明）
                await db.rollback()
                await self._mark_failed(
                    rag_document_id,
                    sanitize_error_message(str(exc)),
                    retryable=isinstance(exc, RetryableIndexingError),
                )
                # 重新抛出，让上层（Celery task）决定是否重试
                raise

    async def _claim_processing(self, rag_document_id: int) -> bool:
        """原子抢占状态：只允许 pending/failed → processing。

        用 UPDATE ... WHERE id=:id AND status IN ('pending','failed') 的 rowcount
        判断是否抢占成功，避免重复消息并发处理同一文档。
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(RagDocument)
                .where(RagDocument.id == rag_document_id)
                .where(RagDocument.status.in_(["pending", "failed"]))
                .values(
                    status="processing",
                    processing_started_at=_utcnow(),
                    error_message=None,
                )
            )
            await db.commit()
            return (result.rowcount or 0) > 0

    async def _load_document(
        self, db: AsyncSession, rag_document_id: int
    ) -> RagDocument | None:
        """读取 RagDocument；不存在则静默返回 None。"""
        result = await db.execute(
            select(RagDocument).where(RagDocument.id == rag_document_id)
        )
        return result.scalar_one_or_none()

    async def _mark_failed(
        self, rag_document_id: int, message: str, retryable: bool = False
    ) -> None:
        """把 RagDocument 标记为 failed：写入脱敏错误、retry_count +1、failed_at。

        可重试错误会在错误信息前加「将自动重试」标记，便于管理端区分。
        """
        final_message = f"【将自动重试】{message}" if retryable else message
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RagDocument)
                .where(RagDocument.id == rag_document_id)
                .values(
                    status="failed",
                    error_message=final_message,
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
            # 文件已被删除（或 file_id 已被置空）：最终失败，不重试
            raise ValueError(f"Wiki 文件已被删除: file_id={doc.file_id}")

        content_bytes = await get_file_content(file.storage_key)
        if content_bytes is None:
            raise RetryableIndexingError(
                f"S3 文件为空或不存在: {file.storage_key}"
            )
        return content_bytes


async def reset_stale_processing_documents() -> list[int]:
    """把超时的 processing 状态文档重置为 pending，返回被重置的 id 列表。

    只重置 processing_started_at 早于阈值（或为 NULL）的任务，
    避免误伤正在被 rag-worker 处理中的任务。
    调用方负责把这些 id 重新 enqueue 到 Celery 队列。
    """
    cutoff = _utcnow() - timedelta(seconds=STALE_PROCESSING_TIMEOUT_SECONDS)
    async with AsyncSessionLocal() as db:
        # 先取出将被重置的 id
        stale_result = await db.execute(
            select(RagDocument.id)
            .where(RagDocument.status == "processing")
            .where(
                or_(
                    RagDocument.processing_started_at.is_(None),
                    RagDocument.processing_started_at < cutoff,
                )
            )
        )
        stale_ids = [row[0] for row in stale_result.all()]
        if not stale_ids:
            return []

        await db.execute(
            update(RagDocument)
            .where(RagDocument.id.in_(stale_ids))
            .where(RagDocument.status == "processing")
            .values(
                status="pending",
                error_message=None,
                processing_started_at=None,
            )
        )
        await db.commit()
        return stale_ids


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
