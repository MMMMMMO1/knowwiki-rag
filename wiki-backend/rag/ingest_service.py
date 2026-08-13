"""
入库服务 —— 接收文档入库请求，创建处理记录并返回。

不执行实际流水线，只写 rag_documents 记录（status=pending）。
实际处理由 task_worker 在后台完成。
"""

from uuid import uuid4

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

    async def ingest(self, file_id: int) -> RagDocument:
        """为指定 Wiki 文件创建 RAG 入库记录（对 file_id 幂等）。

        只创建记录，不执行 loader/splitter/embedder。
        实际处理由 Celery rag-worker 在后台完成。

        幂等策略：同一 file_id 已有记录则重置为 pending 并复用，
        顺带清理历史遗留的重复记录，避免 scalar_one_or_none() 报错。
        """
        from sqlalchemy import select
        from app.models import File, RagDocument

        # 查 Wiki 文件
        result = await self.db.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()
        if not file:
            raise ValueError(f"文件不存在: file_id={file_id}")

        # 幂等：同一 file_id 已有记录则复用，不重复创建
        existing_result = await self.db.execute(
            select(RagDocument).where(RagDocument.file_id == file_id)
        )
        existing_docs = list(existing_result.scalars().all())

        if existing_docs:
            doc = existing_docs[0]
            # 清理历史遗留的重复记录
            for extra in existing_docs[1:]:
                await self.db.delete(extra)
            doc.status = "pending"
            doc.error_message = None
            doc.title = file.title
            await self.db.flush()
            return doc

        # 创建 RAG 文档记录，doc_id 在 pending 阶段就生成 UUID
        doc = RagDocument(
            file_id=file.id,
            doc_id=str(uuid4()),
            title=file.title,
            status="pending",
        )
        self.db.add(doc)
        await self.db.flush()

        return doc
