"""混合检索测试 —— RRF 融合、关键词检索 SQL、向后兼容开关。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rag.retriever import rrf_fuse


def test_rrf_fuse_merges_by_rank() -> None:
    """RRF 按名次融合：两路都命中的 chunk 分数最高，score 被替换为 RRF 分数。"""
    vector_rows = [
        {"chunk_id": "a", "text": "A", "metadata": {}, "score": 0.95},
        {"chunk_id": "b", "text": "B", "metadata": {}, "score": 0.90},
    ]
    keyword_rows = [
        {"chunk_id": "c", "text": "C", "metadata": {}, "score": 10.0},
        {"chunk_id": "a", "text": "A", "metadata": {}, "score": 5.0},
    ]

    merged = rrf_fuse(vector_rows, keyword_rows, top_k=3)

    # "a" 同时出现在两路，RRF 分数最高
    assert merged[0]["chunk_id"] == "a"
    assert len(merged) == 3
    # score 已替换为 RRF 分数（0~1 之间的小数），不再是原始余弦分/ts_rank 分
    assert all(0 < row["score"] < 1 for row in merged)


def test_rrf_fuse_respects_top_k() -> None:
    """RRF 只返回前 top_k 条。"""
    rows = [{"chunk_id": str(i), "text": str(i), "metadata": {}, "score": 1.0} for i in range(10)]
    merged = rrf_fuse(rows, [], top_k=4)
    assert len(merged) == 4


def test_segment_text_never_crashes() -> None:
    """分词函数无论 jieba 是否安装都应返回非空字符串。"""
    from rag.vector_store import _segment_text

    result = _segment_text("蓝色星河计划的负责人")
    assert result


def test_keyword_search_uses_tsvector() -> None:
    """keyword_search 生成 to_tsvector / plainto_tsquery 全文检索 SQL。"""
    from rag.vector_store import VectorStore

    captured = {}

    class FakeResult:
        def all(self):
            return []

    class FakeDB:
        async def execute(self, stmt, *args, **kwargs):
            captured["stmt"] = stmt
            return FakeResult()

    async def run():
        store = VectorStore(FakeDB())
        with patch("rag.vector_store._segment_text", return_value="蓝色 星河 计划"):
            await store.keyword_search("蓝色星河计划", top_k=5)

    asyncio.run(run())
    sql = str(captured["stmt"]).lower()
    assert "to_tsvector" in sql
    assert "plainto_tsquery" in sql


def test_retriever_hybrid_off_by_default() -> None:
    """HYBRID_SEARCH 默认关闭：retrieve 只走向量检索，不调关键词检索。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[
            {"chunk_id": "c1", "text": "t1", "metadata": {}, "score": 0.9},
        ])
        store.keyword_search = AsyncMock(return_value=[])

        retriever = Retriever(embedder, store, top_k=3)
        with patch("rag.retriever.settings.HYBRID_SEARCH", False):
            results = await retriever.retrieve("query")

        assert len(results) == 1
        assert results[0].chunk_id == "c1"
        store.keyword_search.assert_not_awaited()

    asyncio.run(run())


def test_retriever_hybrid_on_calls_keyword_and_fuses() -> None:
    """HYBRID_SEARCH 开启：同时调关键词检索并用 RRF 融合。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[
            {"chunk_id": "a", "text": "A", "metadata": {}, "score": 0.9},
        ])
        store.keyword_search = AsyncMock(return_value=[
            {"chunk_id": "a", "text": "A", "metadata": {}, "score": 8.0},
            {"chunk_id": "b", "text": "B", "metadata": {}, "score": 4.0},
        ])

        retriever = Retriever(embedder, store, top_k=3)
        with patch("rag.retriever.settings.HYBRID_SEARCH", True):
            results = await retriever.retrieve("query")

        store.keyword_search.assert_awaited_once_with("query", top_k=3, workspace_id="default")
        assert results[0].chunk_id == "a"  # 两路都命中，RRF 分数最高

    asyncio.run(run())
