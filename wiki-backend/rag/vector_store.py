"""
向量存储模块 —— 基于 PostgreSQL pgvector 的向量索引与检索。

基于 PostgreSQL + pgvector，提供 Chunk + 向量的增删查。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RagChunk, RagDocument
from rag.schemas import Chunk


class VectorStore:
    """PostgreSQL + pgvector 向量存储。

    提供三个核心操作：
    - insert: 批量写入 Chunk + 向量
    - search: 余弦相似度检索
    - delete_by_document: 按文档删除
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 写入 ──────────────────────────────────────────────

    async def insert(
        self,
        document: RagDocument,
        chunks: list[Chunk],
        vectors: list[list[float]],
    ) -> list[RagChunk]:
        """批量写入 Chunk 及其向量。

        Args:
            document: 已持久化的 RagDocument 记录。
            chunks: Splitter 产出的 Chunk 列表。
            vectors: Embedder 产出的向量列表，与 chunks 一一对应。

        Returns:
            持久化后的 RagChunk 列表。
        """
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks 与 vectors 数量不匹配: {len(chunks)} vs {len(vectors)}"
            )

        records: list[RagChunk] = []
        for chunk, vector in zip(chunks, vectors):
            record = RagChunk(
                document_id=document.id,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                embedding=vector,
                metadata_=chunk.metadata,
            )
            self.db.add(record)
            records.append(record)

        document.chunk_count = len(chunks)
        document.status = "completed"

        await self.db.flush()
        return records

    # ── 检索 ──────────────────────────────────────────────

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """余弦相似度检索 —— 返回最相关的 Chunk。

        Args:
            query_vector: 查询文本的向量。
            top_k: 返回数量。

        Returns:
            列表，每项包含 chunk_id, text, score, metadata。
        """
        # pgvector 余弦相似度：1 - cosine_distance <=> cosine_similarity
        query = (
            select(
                RagChunk.chunk_id,
                RagChunk.text,
                RagChunk.metadata_,
                (1 - RagChunk.embedding.cosine_distance(query_vector)).label("score"),
            )
            .where(RagChunk.embedding.is_not(None))
            .order_by(RagChunk.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
        result = await self.db.execute(query)
        return [
            {
                "chunk_id": row.chunk_id,
                "text": row.text,
                "metadata": row.metadata_,
                "score": round(float(row.score), 4),
            }
            for row in result.all()
        ]

    # ── 删除 ──────────────────────────────────────────────

    async def delete_by_document(self, document: RagDocument) -> None:
        """删除一个文档的所有 Chunk 及其向量。"""
        await self.db.execute(
            text("DELETE FROM rag_chunks WHERE document_id = :doc_id"),
            {"doc_id": document.id},
        )
        document.chunk_count = 0
        document.status = "pending"
        await self.db.flush()

    async def delete_by_file_id(self, file_id: int) -> None:
        """按 Wiki 文件 ID 删除对应 RAG 索引。"""
        doc = await self.get_document_by_file_id(file_id)
        if doc:
            await self.db.execute(
                text("DELETE FROM rag_chunks WHERE document_id = :doc_id"),
                {"doc_id": doc.id},
            )
            await self.db.delete(doc)
            await self.db.flush()

    async def delete_by_file_ids(self, file_ids: list[int]) -> None:
        """批量按 file_id 删除 RAG 索引。"""
        if not file_ids:
            return
        docs_result = await self.db.execute(
            select(RagDocument).where(RagDocument.file_id.in_(file_ids))
        )
        docs = docs_result.scalars().all()
        for doc in docs:
            await self.db.execute(
                text("DELETE FROM rag_chunks WHERE document_id = :doc_id"),
                {"doc_id": doc.id},
            )
            await self.db.delete(doc)
        await self.db.flush()

    # ── 工具 ──────────────────────────────────────────────

    async def get_document_by_file_id(self, file_id: int) -> RagDocument | None:
        """按 Wiki 文件 ID 查找 RAG 文档记录。"""
        result = await self.db.execute(
            select(RagDocument).where(RagDocument.file_id == file_id)
        )
        return result.scalar_one_or_none()

    async def get_document_by_doc_id(self, doc_id: str) -> RagDocument | None:
        """按 RAG doc_id 查找文档记录。"""
        result = await self.db.execute(
            select(RagDocument).where(RagDocument.doc_id == doc_id)
        )
        return result.scalar_one_or_none()

    async def create_document(
        self, doc_id: str, title: str, content_hash: str, file_id: int | None = None
    ) -> RagDocument:
        """创建 RAG 文档处理记录。"""
        document = RagDocument(
            file_id=file_id,
            doc_id=doc_id,
            title=title,
            content_hash=content_hash,
            status="processing",
        )
        self.db.add(document)
        await self.db.flush()
        return document
