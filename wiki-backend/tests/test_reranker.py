"""Rerank 精排测试 —— OpenAI 兼容接口重排、开关向后兼容。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_openai_reranker_orders_by_relevance_score() -> None:
    """OpenAIReranker 按 relevance_score 降序重排，并回写 score。"""
    from rag.reranker import OpenAIReranker
    from rag.schemas import RetrievalResult

    candidates = [
        RetrievalResult(chunk_id="a", text="A", score=0.9, metadata={}),
        RetrievalResult(chunk_id="b", text="B", score=0.8, metadata={}),
        RetrievalResult(chunk_id="c", text="C", score=0.7, metadata={}),
    ]

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "results": [
                    {"index": 0, "relevance_score": 0.2},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": 0.5},
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            self.payload = kwargs["json"]
            return FakeResponse()

    async def run():
        reranker = OpenAIReranker(api_url="http://test", api_key="k", model="m")
        fake = FakeClient()
        with patch("rag.reranker.httpx.AsyncClient", return_value=fake):
            ranked = await reranker.rerank("q", candidates)

        assert [c.chunk_id for c in ranked] == ["b", "c", "a"]
        # score 被替换为 relevance_score
        assert ranked[0].score == 0.9
        # 请求体包含 documents 文本列表
        assert fake.payload["documents"] == ["A", "B", "C"]
        assert fake.payload["query"] == "q"
        assert fake.payload["model"] == "m"

    asyncio.run(run())


def test_openai_reranker_empty_candidates_no_request() -> None:
    """空候选集直接返回，不发请求。"""
    from rag.reranker import OpenAIReranker

    async def run():
        reranker = OpenAIReranker(api_url="http://test", api_key="k", model="m")
        with patch("rag.reranker.httpx.AsyncClient") as mock_client:
            ranked = await reranker.rerank("q", [])
        assert ranked == []
        mock_client.assert_not_called()

    asyncio.run(run())


def test_retriever_rerank_disabled_passthrough() -> None:
    """RERANK_ENABLED=False：行为与现状一致，不触发 rerank，粗召回即 top_k。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[
            {"chunk_id": f"c{i}", "text": f"t{i}", "metadata": {}, "score": 0.9}
            for i in range(3)
        ])

        retriever = Retriever(embedder, store, top_k=3)
        with patch("rag.retriever.settings.HYBRID_SEARCH", False):
            with patch("rag.retriever.settings.RERANK_ENABLED", False):
                with patch.object(Retriever, "_build_reranker") as build_mock:
                    results = await retriever.retrieve("query")

        assert len(results) == 3
        build_mock.assert_not_called()
        # 粗召回用 top_k 而非候选集大小
        store.search.assert_awaited_once()
        assert store.search.await_args.kwargs.get("top_k") == 3

    asyncio.run(run())


def test_retriever_rerank_enabled_recalls_more_and_truncates() -> None:
    """RERANK_ENABLED=True：粗召回 RERANK_CANDIDATE_K 条，精排后截断回 top_k。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[
            {"chunk_id": f"c{i}", "text": f"t{i}", "metadata": {}, "score": 0.9}
            for i in range(20)
        ])

        reranker = MagicMock()

        async def fake_rerank(query, candidates):
            return list(reversed(candidates))

        reranker.rerank = AsyncMock(side_effect=fake_rerank)

        retriever = Retriever(embedder, store, top_k=5)
        with patch("rag.retriever.settings.HYBRID_SEARCH", False):
            with patch("rag.retriever.settings.RERANK_ENABLED", True):
                with patch("rag.retriever.settings.RERANK_CANDIDATE_K", 20):
                    with patch.object(Retriever, "_build_reranker", return_value=reranker):
                        results = await retriever.retrieve("query")

        # 粗召回 20 条
        store.search.assert_awaited_once()
        assert store.search.await_args.kwargs.get("top_k") == 20
        # 精排后截断回 top_k=5
        assert len(results) == 5
        # 反转后第一条是 c19（原最后一条）
        assert results[0].chunk_id == "c19"

    asyncio.run(run())


def test_retriever_falls_back_when_reranker_fails() -> None:
    """精排服务异常时保留粗召回结果，聊天链路不失败。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[
            {"chunk_id": f"c{i}", "text": f"t{i}", "metadata": {}, "score": 0.9 - i / 10}
            for i in range(4)
        ])
        reranker = MagicMock()
        reranker.rerank = AsyncMock(side_effect=RuntimeError("rerank unavailable"))

        retriever = Retriever(embedder, store, top_k=2)
        with patch("rag.retriever.settings.HYBRID_SEARCH", False), \
                patch("rag.retriever.settings.RERANK_ENABLED", True), \
                patch("rag.retriever.settings.RERANK_CANDIDATE_K", 4), \
                patch.object(Retriever, "_build_reranker", return_value=reranker):
            results = await retriever.retrieve("query")

        assert [item.chunk_id for item in results] == ["c0", "c1"]

    asyncio.run(run())
