"""
检索模块 —— 替代 AnythingLLM 的 performSimilaritySearch。

编排 Embedder + VectorStore，将用户自然语言问题转换为最相关的 Chunk 列表。
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from rag.embedding import Embedder
from rag.schemas import Chunk
from rag.vector_store import VectorStore


@dataclass
class RetrievalResult:
    """单条检索结果。"""

    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever:
    """RAG 检索器 —— 组合 Embedder 和 VectorStore。

    用法:
        retriever = Retriever(embedder, vector_store)
        results = await retriever.retrieve("光合作用的原理是什么？")
    """

    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        top_k: int | None = None,
    ):
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k or settings.TOP_K

    async def retrieve(self, query: str) -> list[RetrievalResult]:
        """检索与 query 最相关的 Chunk。

        Args:
            query: 用户自然语言问题。

        Returns:
            按相似度降序排列的检索结果列表。
        """
        if not query.strip():
            return []

        # 1. 把问题向量化（和索引阶段用同一个 Embedder）
        query_chunk = Chunk.create(doc_id="query", text=query)
        query_vectors = await self.embedder.embed([query_chunk])
        query_vector = query_vectors[0]

        # 2. 向量相似度搜索
        rows = await self.vector_store.search(query_vector, top_k=self.top_k)

        # 3. 组装结果
        return [
            RetrievalResult(
                chunk_id=row["chunk_id"],
                text=row["text"],
                score=row["score"],
                metadata=row["metadata"],
            )
            for row in rows
        ]

    def format_context(self, results: list[RetrievalResult]) -> str:
        """将检索结果拼接为 LLM 可用的 context 字符串。

        Args:
            results: retrieve() 的返回值。

        Returns:
            用双换行分隔的上下文字符串。
        """
        if not results:
            return ""

        parts: list[str] = []
        for i, result in enumerate(results, 1):
            title = result.metadata.get("title", result.metadata.get("source", ""))
            header = f"[来源 {i}]" + (f" {title}" if title else "")
            parts.append(f"{header}\n{result.text}")

        return "\n\n".join(parts)
