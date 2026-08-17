"""Query rewrite 测试 —— 多轮改写、失败降级、无历史直通。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_rewrite_query_no_history_returns_question() -> None:
    """无对话历史时直接返回原问题，不调用 LLM。"""
    from rag.chat_service import ChatService

    async def run():
        service = ChatService()
        with patch("rag.chat_service.LLM") as mock_llm_cls:
            result = await service._rewrite_query("什么是 RAG？", None)
        assert result == "什么是 RAG？"
        mock_llm_cls.assert_not_called()

    asyncio.run(run())


def test_rewrite_query_with_history_calls_llm() -> None:
    """有历史时调用 LLM 改写，返回改写结果。"""
    from rag.chat_service import ChatService

    class FakeLLM:
        async def chat(self, messages, temperature=0.7, max_tokens=None, timeout=120.0):
            return "什么是 RAG 检索增强生成？"

    async def run():
        service = ChatService()
        with patch("rag.chat_service.LLM", return_value=FakeLLM()):
            result = await service._rewrite_query(
                "它有什么优点？",
                [
                    {"role": "user", "content": "什么是 RAG？"},
                    {"role": "assistant", "content": "RAG 是检索增强生成。"},
                ],
            )
        assert result == "什么是 RAG 检索增强生成？"

    asyncio.run(run())


def test_rewrite_query_failure_falls_back_to_question() -> None:
    """LLM 改写失败时降级返回原始问题，不抛异常。"""
    from rag.chat_service import ChatService

    class BoomLLM:
        async def chat(self, messages, temperature=0.7, max_tokens=None, timeout=120.0):
            raise RuntimeError("LLM 不可用")

    async def run():
        service = ChatService()
        with patch("rag.chat_service.LLM", return_value=BoomLLM()):
            result = await service._rewrite_query(
                "它有什么优点？",
                [{"role": "user", "content": "什么是 RAG？"}],
            )
        assert result == "它有什么优点？"

    asyncio.run(run())


def test_ask_uses_retrieval_query_for_retrieve() -> None:
    """ask 流程：检索用改写后的 retrieval_query，回答仍用原始 question。"""
    from rag.chat_service import ChatService

    captured = {}

    class FakeLLM:
        async def chat(self, messages, temperature=0.7):
            captured["answer_prompt"] = messages[-1]["content"]
            return "答案"

    class FakeResult:
        chunk_id = "c1"
        text = "text"
        score = 0.9
        metadata = {}

    class FakeRetriever:
        def __init__(self, *args, **kwargs):
            pass

        async def retrieve(self, query):
            captured["retrieval_query"] = query
            return [FakeResult()]

        def format_context(self, results):
            return "context"

    async def run():
        service = ChatService()
        service._rewrite_query = AsyncMock(return_value="改写后的问题")
        with patch("rag.chat_service.Retriever", FakeRetriever), \
                patch("rag.chat_service.LLM", return_value=FakeLLM()), \
                patch("rag.chat_service.settings.MEMORY_ENABLED", False):
            answer = await service.ask(
                "它有什么优点？",
                MagicMock(),
                chat_history=[{"role": "user", "content": "什么是 RAG？"}],
            )

        assert captured["retrieval_query"] == "改写后的问题"
        assert "它有什么优点？" in captured["answer_prompt"]
        assert "改写后的问题" not in captured["answer_prompt"]
        assert answer == "答案"

    asyncio.run(run())


def test_rewrite_query_empty_result_falls_back() -> None:
    """LLM 改写返回空字符串时降级为原始问题。"""
    from rag.chat_service import ChatService

    class EmptyLLM:
        async def chat(self, messages, temperature=0.7, max_tokens=None, timeout=120.0):
            return "   "

    async def run():
        service = ChatService()
        with patch("rag.chat_service.LLM", return_value=EmptyLLM()):
            result = await service._rewrite_query(
                "它有什么优点？",
                [{"role": "user", "content": "什么是 RAG？"}],
            )
        assert result == "它有什么优点？"

    asyncio.run(run())
