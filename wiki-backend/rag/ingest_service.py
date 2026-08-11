"""
入库服务 —— 接收文档入库请求，创建处理记录并返回。

不执行实际流水线，只写 rag_documents 记录（status=pending）。
实际处理由 task_worker 在后台完成。
"""

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
        """为指定 Wiki 文件创建 RAG 入库记录。

        只创建记录，不执行 loader/splitter/embedder。
        实际处理由 TaskWorker 在后台完成。
        """
        from sqlalchemy import select
        from app.models import File

        # 查 Wiki 文件
        result = await self.db.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()
        if not file:
            raise ValueError(f"文件不存在: file_id={file_id}")

        # 创建 RAG 文档记录
        doc = RagDocument(
            file_id=file.id,
            doc_id="",  # TaskWorker 会填充
            title=file.title,
            content_hash="",  # TaskWorker 会填充
            status="pending",
        )
        self.db.add(doc)
        await self.db.flush()

        return doc
