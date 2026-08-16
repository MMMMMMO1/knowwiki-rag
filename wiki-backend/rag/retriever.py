"""
检索模块 —— 编排 embedding + 向量检索流程。

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


# RRF 融合的常量 k：名次权重分母里的平滑项，业界常用 60。
RRF_K = 60


def rrf_fuse(
    vector_rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    top_k: int = 5,
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """用 RRF（Reciprocal Rank Fusion）融合两路检索结果。

    每路结果按名次贡献 1/(k + rank + 1)，同名次累加；
    只比较名次、不比较原始分数绝对值，绕开余弦分与 ts_rank 分数量纲不一致的问题。
    """
    scores: dict[str, float] = {}
    data: dict[str, dict[str, Any]] = {}

    for rank, row in enumerate(vector_rows):
        key = row["chunk_id"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        data[key] = row
    for rank, row in enumerate(keyword_rows):
        key = row["chunk_id"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        data[key] = row

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [
        {**data[key], "score": round(score, 6)}
        for key, score in ranked
    ]


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
        vector_rows = await self.vector_store.search(query_vector, top_k=self.top_k)

        # 3. 混合检索：配置开启时叠加关键词检索，用 RRF 融合；默认只走向量，向后兼容
        if not settings.HYBRID_SEARCH:
            return self._to_results(vector_rows)

        keyword_rows = await self.vector_store.keyword_search(query, top_k=self.top_k)
        merged = rrf_fuse(vector_rows, keyword_rows, top_k=self.top_k)
        return self._to_results(merged)

    def _to_results(self, rows: list[dict[str, Any]]) -> list[RetrievalResult]:
        """把 vector_store 返回的 dict 列表组装成 RetrievalResult。"""
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
