"""RAG Debug 接口测试 —— 中间结果、字段完整、权限。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models import User


def test_retrieve_debug_exposes_stages() -> None:
    """retrieve_debug 返回 vector/keyword/merged/rerank/final 各阶段中间结果。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[
            {
                "chunk_id": "a", "text": "A", "score": 0.9,
                "metadata": {"title": "t.md", "full_path": "t", "chunk_index": 0},
            }
        ])
        store.keyword_search = AsyncMock(return_value=[
            {
                "chunk_id": "b", "text": "B", "score": 8.0,
                "metadata": {"title": "u.md", "full_path": "u", "chunk_index": 1},
            }
        ])

        reranker = MagicMock()
        reranker.rerank = AsyncMock(side_effect=lambda q, candidates: candidates)

        retriever = Retriever(embedder, store, top_k=5)
        with patch("rag.retriever.settings.HYBRID_SEARCH", True), \
                patch("rag.retriever.settings.RERANK_ENABLED", True), \
                patch.object(Retriever, "_build_reranker", return_value=reranker):
            debug = await retriever.retrieve_debug("q")

        assert debug["vector_results"]
        assert debug["keyword_results"]
        assert debug["merged_results"]
        assert debug["rerank_results"]
        assert debug["final_results"]
        first = debug["final_results"][0]
        assert first["title"] == "t.md"
        assert first["full_path"] == "t"
        assert first["chunk_index"] == 0
        assert "score" in first and "text" in first

    asyncio.run(run())


def test_chat_service_debug_returns_full_fields() -> None:
    """ChatService.debug 返回原问题/改写问题/各阶段/最终 sources/prompt 等字段。"""
    from rag.chat_service import ChatService

    async def run():
        service = ChatService()
        service._rewrite_query = AsyncMock(return_value="改写后的问题")

        final = {
            "chunk_id": "a", "text": "A", "score": 0.9,
            "title": "t.md", "full_path": "t", "storage_key": "t",
            "file_id": 1, "chunk_index": 0,
        }

        class FakeRetriever:
            def __init__(self, *args, **kwargs):
                pass

            async def retrieve_debug(self, query):
                return {
                    "vector_results": [final],
                    "keyword_results": [],
                    "merged_results": [],
                    "rerank_results": [],
                    "final_results": [final],
                }

            def format_context(self, results):
                return "ctx"

        with patch("rag.chat_service.Retriever", FakeRetriever), \
                patch("rag.chat_service.settings.MEMORY_ENABLED", False):
            debug = await service.debug("原始问题", MagicMock(), chat_history=None)

        assert debug["original_question"] == "原始问题"
        assert debug["retrieval_query"] == "改写后的问题"
        assert debug["final_sources"][0]["title"] == "t.md"
        assert debug["prompt_messages"]
        assert "model" in debug and "temperature" in debug

    asyncio.run(run())


def test_rag_debug_endpoint_returns_debug() -> None:
    """/rag/debug 返回 debug 结构，并从 session 自动取历史。"""
    from app.api.v1.rag import DebugRequest, rag_debug

    class FakeChatService:
        async def debug(self, **kwargs):
            return {"original_question": kwargs["question"], "retrieval_query": kwargs["question"]}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeDB:
        async def execute(self, *args, **kwargs):
            return FakeResult()

    async def run():
        admin = User(id=1, username="a", role="admin")
        with patch("rag.chat_service.ChatService", FakeChatService):
            return await rag_debug(
                DebugRequest(question="q", session_id="s"),
                admin,
                FakeDB(),
            )

    result = asyncio.run(run())
    assert result["original_question"] == "q"


def test_debug_requires_admin() -> None:
    """非 admin（reader）被 debug 依赖拒绝。"""
    from app.core.security import require_roles

    reader = User(id=1, username="r", role="reader")
    admin = User(id=2, username="a", role="admin")
    dep = require_roles("admin")

    with pytest.raises(HTTPException):
        asyncio.run(dep(reader))
    assert asyncio.run(dep(admin)).role == "admin"
