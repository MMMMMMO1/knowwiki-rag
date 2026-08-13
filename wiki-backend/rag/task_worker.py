"""
后台工人 —— 轮询 rag_documents 表中 pending 的记录，执行完整 RAG 流水线。

流水线: loader → splitter → embedder → vector_store
状态机: pending → processing → completed | failed
"""

from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import RagDocument
from rag.embedding import Embedder
from rag.loader import DocumentLoader
from rag.splitter import TextSplitter
from rag.vector_store import VectorStore


class TaskWorker:
    """后台 RAG 入库工人。

    用法:
        worker = TaskWorker()
        await worker.run()  # 阻塞，持续轮询
    """

    def __init__(self, poll_interval: float = 1.0):
        self.poll_interval = poll_interval
        self._running = False

    async def run(self) -> None:
        """启动轮询循环（阻塞调用）。"""
        self._running = True
        print("[TaskWorker] 启动，等待待处理文档...")

        while self._running:
            async with AsyncSessionLocal() as db:
                try:
                    processed = await self._process_one(db)
                    if not processed:
                        await asyncio.sleep(self.poll_interval)
                except Exception as exc:
                    print(f"[TaskWorker] 轮询异常: {exc}")
                    await asyncio.sleep(self.poll_interval)

    async def _process_one(self, db: AsyncSession) -> bool:
        """取一条 pending 记录并处理。返回 True 表示处理了一条。"""
        # 1. 取一条 pending 记录并锁定为 processing
        result = await db.execute(
            select(RagDocument)
            .where(RagDocument.status == "pending")
            .order_by(RagDocument.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return False

        doc.status = "processing"
        await db.flush()

        print(f"[TaskWorker] 开始处理: file_id={doc.file_id}, title={doc.title}")

        try:
            # 2. 从 S3 加载文件内容，交给 DocumentLoader 统一解析
            content_bytes = await self._load_raw_bytes(db, doc)
            loader = self._create_loader()
            document = loader.load_bytes(
                file_name=doc.title,
                content=content_bytes,
                metadata={"file_id": doc.file_id},
            )

            # 3. 空文本检测
            if not document.content or not document.content.strip():
                raise ValueError("文档内容为空，无法索引")

            # 4. 计算 content_hash（去重用）
            content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
            doc.content_hash = content_hash

            # 5. 如果同一 file_id 已有旧 chunks，先清理（支持重新上传）
            store = VectorStore(db)
            await store.delete_by_document(doc)

            # 6. 跑流水线（splitter → embedder → vector_store）
            splitter = TextSplitter()
            embedder = Embedder()

            chunks = splitter.split(document)
            vectors = await embedder.embed(chunks)
            await store.insert(doc, chunks, vectors)

            # 成功：清除错误信息
            doc.error_message = None
            await db.commit()
            print(
                f"[TaskWorker] 完成: {doc.title}, {len(chunks)} chunks"
            )

        except Exception as exc:
            await db.rollback()
            doc.status = "failed"
            doc.error_message = str(exc)
            await db.commit()
            print(f"[TaskWorker] 失败: {doc.title}, 错误: {exc}")

        return True

    async def _load_raw_bytes(self, db: AsyncSession, doc: RagDocument) -> bytes:
        """从 S3 读取文件原始字节。"""
        from sqlalchemy import select
        from app.models import File
        from app.core.storage import get_file_content

        result = await db.execute(select(File).where(File.id == doc.file_id))
        file = result.scalar_one_or_none()
        if not file:
            raise ValueError(f"Wiki 文件不存在: file_id={doc.file_id}")

        content_bytes = await get_file_content(file.storage_key)
        if content_bytes is None:
            raise ValueError(f"S3 文件为空或不存在: {file.storage_key}")
        return content_bytes

    @staticmethod
    def _create_loader() -> DocumentLoader:
        """创建文档加载器（后续可注入不同解析策略）。"""
        return DocumentLoader()

    def stop(self) -> None:
        """停止轮询。"""
        self._running = False
