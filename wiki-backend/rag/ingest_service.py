"""
入库服务 —— 接收文档入库请求，创建处理记录并返回。

不执行实际流水线，只写 rag_documents 记录（status=pending，queued_at 已记录）。
实际处理由 Celery rag-worker 在后台完成。
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RagDocument


class IngestService:
    """文档异步入库入口。

    用法:
        service = IngestService(db)
        doc = await service.ingest(file_id=42)
        # 立即返回，status=pending
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ingest(self, file_id: int, workspace_id: str | None = None) -> RagDocument:
        """为指定 Wiki 文件创建 RAG 入库记录（对 file_id 幂等）。

        只创建记录，不执行 loader/splitter/embedder。
        实际处理由 Celery rag-worker 在后台完成。

        并发策略：用 PostgreSQL 事务级 advisory lock 串行化同一 file_id 的请求。
        processing 期间的新请求只递增 generation，不重置状态；当前 worker 会在
        发布前发现版本过期，回滚旧结果并重新投递最新版本。
        """
        from app.models import File, RagDocument

        normalized_workspace = workspace_id.strip() if workspace_id is not None else None
        if normalized_workspace is not None and not normalized_workspace:
            normalized_workspace = "default"
        if normalized_workspace is not None and len(normalized_workspace) > 100:
            raise ValueError("workspace_id 不能超过 100 个字符")

        # 即使记录尚不存在，也能阻止两个并发请求同时创建相同 file_id。
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:file_id)"),
            {"file_id": file_id},
        )

        # 查 Wiki 文件
        result = await self.db.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()
        if not file:
            raise ValueError(f"文件不存在: file_id={file_id}")

        # 幂等：同一 file_id 已有记录则复用，不重复创建
        existing_result = await self.db.execute(
            select(RagDocument)
            .where(RagDocument.file_id == file_id)
            .with_for_update()
        )
        doc = existing_result.scalar_one_or_none()

        if doc is not None:
            doc.generation = (doc.generation or 1) + 1
            doc.error_message = None
            doc.title = file.title
            if normalized_workspace is not None:
                doc.workspace_id = normalized_workspace
            doc.queued_at = datetime.now(timezone.utc)
            doc.completed_at = None
            doc.failed_at = None
            doc.retry_count = 0

            if doc.status != "processing":
                doc.status = "pending"
                doc.processing_generation = None
                doc.processing_started_at = None

            await self.db.flush()
            return doc

        # 创建 RAG 文档记录，doc_id 在 pending 阶段就生成 UUID
        doc = RagDocument(
            file_id=file.id,
            doc_id=str(uuid4()),
            title=file.title,
            workspace_id=normalized_workspace or "default",
            status="pending",
            generation=1,
            queued_at=datetime.now(timezone.utc),
        )
        self.db.add(doc)
        await self.db.flush()

        return doc
