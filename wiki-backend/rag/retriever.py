"""
检索模块 —— 编排 embedding + 向量检索流程。

编排 Embedder + VectorStore，将用户自然语言问题转换为最相关的 Chunk 列表。
"""

import logging
from typing import Any

from app.core.config import settings
from rag.embedding import Embedder
from rag.reranker import OpenAIReranker, Reranker
from rag.schemas import Chunk, RetrievalResult
from rag.vector_store import VectorStore


# RRF 融合的常量 k：名次权重分母里的平滑项，业界常用 60。
RRF_K = 60
logger = logging.getLogger(__name__)


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
        workspace_id: str = "default",
    ):
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k or settings.TOP_K
        self.workspace_id = workspace_id

    async def retrieve(self, query: str) -> list[RetrievalResult]:
        """检索与 query 最相关的 Chunk。

        Args:
            query: 用户自然语言问题。

        Returns:
            按相似度降序排列的检索结果列表。
        """
        if not query.strip():
            return []

        # Recall size: when rerank is enabled, recall more candidates, then truncate to top_k
        recall_k = settings.RERANK_CANDIDATE_K if settings.RERANK_ENABLED else self.top_k

        # 1. 把问题向量化（和索引阶段用同一个 Embedder）
        query_chunk = Chunk.create(doc_id="query", text=query)
        query_vectors = await self.embedder.embed([query_chunk])
        query_vector = query_vectors[0]

        # 2. 向量相似度搜索
        vector_rows = await self.vector_store.search(
            query_vector, top_k=recall_k, workspace_id=self.workspace_id
        )

        # 3. 混合检索：配置开启时叠加关键词检索，用 RRF 融合；默认只走向量，向后兼容
        if not settings.HYBRID_SEARCH:
            results = self._to_results(vector_rows)
        else:
            keyword_rows = await self.vector_store.keyword_search(
                query, top_k=recall_k, workspace_id=self.workspace_id
            )
            merged = rrf_fuse(vector_rows, keyword_rows, top_k=recall_k)
            results = self._to_results(merged)

        # 4. Re-rank: when enabled, re-score candidates with a cross-encoder reranker, keep top_k
        if settings.RERANK_ENABLED and results:
            try:
                reranker = self._build_reranker()
                results = await reranker.rerank(query, results)
            except Exception as exc:
                logger.warning("Rerank unavailable; using recall results: %s", type(exc).__name__)
            results = results[: self.top_k]

        return results

    async def retrieve_debug(self, query: str) -> dict[str, Any]:
        """检索并返回各阶段中间结果（供 debug 接口使用，不改变生产路径）。

        返回 dict：vector_results / keyword_results / merged_results /
        rerank_results / final_results，每条统一为可序列化 dict。
        """
        debug: dict[str, Any] = {
            "vector_results": [],
            "keyword_results": [],
            "merged_results": [],
            "rerank_results": [],
            "rerank_error": None,
            "final_results": [],
        }
        if not query.strip():
            return debug

        recall_k = settings.RERANK_CANDIDATE_K if settings.RERANK_ENABLED else self.top_k

        # 1. 把问题向量化（和索引阶段用同一个 Embedder）
        query_chunk = Chunk.create(doc_id="query", text=query)
        query_vectors = await self.embedder.embed([query_chunk])
        query_vector = query_vectors[0]

        # 2. 向量相似度搜索
        vector_rows = await self.vector_store.search(
            query_vector, top_k=recall_k, workspace_id=self.workspace_id
        )
        debug["vector_results"] = self._rows_to_dicts(vector_rows)

        # 3. 混合检索
        if not settings.HYBRID_SEARCH:
            results = self._to_results(vector_rows)
        else:
            keyword_rows = await self.vector_store.keyword_search(
                query, top_k=recall_k, workspace_id=self.workspace_id
            )
            debug["keyword_results"] = self._rows_to_dicts(keyword_rows)
            merged = rrf_fuse(vector_rows, keyword_rows, top_k=recall_k)
            debug["merged_results"] = self._rows_to_dicts(merged)
            results = self._to_results(merged)

        # 4. 精排
        if settings.RERANK_ENABLED and results:
            try:
                reranker = self._build_reranker()
                reranked = await reranker.rerank(query, results)
                debug["rerank_results"] = [self._result_to_dict(r) for r in reranked]
                results = reranked[: self.top_k]
            except Exception as exc:
                debug["rerank_error"] = type(exc).__name__
                results = results[: self.top_k]

        debug["final_results"] = [self._result_to_dict(r) for r in results]
        return debug

    @staticmethod
    def _rows_to_dicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把 vector_store 的 dict 行转统一 debug 格式。"""
        return [
            {
                "chunk_id": row["chunk_id"],
                "text": row["text"],
                "score": row["score"],
                "title": (row.get("metadata") or {}).get("title", ""),
                "full_path": (row.get("metadata") or {}).get("full_path", ""),
                "storage_key": (row.get("metadata") or {}).get("storage_key", ""),
                "file_id": (row.get("metadata") or {}).get("file_id"),
                "chunk_index": (row.get("metadata") or {}).get("chunk_index"),
            }
            for row in rows
        ]

    @staticmethod
    def _result_to_dict(result: RetrievalResult) -> dict[str, Any]:
        """把 RetrievalResult 转统一 debug 格式。"""
        meta = result.metadata or {}
        return {
            "chunk_id": result.chunk_id,
            "text": result.text,
            "score": result.score,
            "title": meta.get("title", ""),
            "full_path": meta.get("full_path", ""),
            "storage_key": meta.get("storage_key", ""),
            "file_id": meta.get("file_id"),
            "chunk_index": meta.get("chunk_index"),
        }

    def _build_reranker(self) -> Reranker:
        """Build the reranker instance; defaults to OpenAI-compatible /rerank."""
        return OpenAIReranker()

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
