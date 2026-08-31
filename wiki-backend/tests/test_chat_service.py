"""聊天上下文传递测试 —— 验证 PromptBuilder 接收历史、ChatService 传递历史。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_prompt_builder_includes_history() -> None:
    """PromptBuilder 能把 chat_history 插入 messages，且当前问题不与历史重复。"""
    from rag.prompt_builder import PromptBuilder

    builder = PromptBuilder(system_prompt="sys")
    history = [
        {"role": "user", "content": "上一轮问题"},
        {"role": "assistant", "content": "上一轮回答"},
    ]
    messages = builder.build(question="当前问题", context="ctx", chat_history=history)

    assert messages[0] == {"role": "system", "content": "sys"}
    assert {"role": "user", "content": "上一轮问题"} in messages
    assert {"role": "assistant", "content": "上一轮回答"} in messages
    # 最后一条是包含当前问题的 user 消息
    assert messages[-1]["role"] == "user"
    assert "当前问题" in messages[-1]["content"]


def test_prompt_builder_without_history() -> None:
    """不传历史时不额外插入消息。"""
    from rag.prompt_builder import PromptBuilder

    builder = PromptBuilder(system_prompt="sys")
    messages = builder.build(question="q", context="ctx")
    # 只有 system + user 两条
    assert len(messages) == 2
    assert [m["role"] for m in messages] == ["system", "user"]


def test_chat_service_passes_history_to_prompt_builder() -> None:
    """ChatService.ask_stream 把 chat_history 原样传给 PromptBuilder.build。"""
    from rag.chat_service import ChatService

    async def run():
        service = ChatService()
        history = [
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮回答"},
        ]

        fake_result = MagicMock()
        fake_result.chunk_id = "c1"
        fake_result.text = "some text"
        fake_result.score = 0.9
        fake_result.metadata = {"title": "t", "file_id": 1}

        with patch("rag.chat_service.Retriever") as MockRetriever, \
                patch("rag.chat_service.VectorStore"), \
                patch("rag.chat_service.Embedder"), \
                patch("rag.chat_service.LLM") as MockLLM, \
                patch("rag.chat_service.PromptBuilder") as MockBuilder:
            retriever = MockRetriever.return_value
            retriever.retrieve = AsyncMock(return_value=[fake_result])
            retriever.format_context = MagicMock(return_value="ctx")

            llm = MockLLM.return_value

            async def fake_stream(messages, temperature=None):
                yield "ok"

            llm.chat_stream = fake_stream

            builder = MockBuilder.return_value
            builder.build.return_value = [{"role": "system", "content": "sys"}]

            tokens = []
            async for token in service.ask_stream(
                "q", db=None, chat_history=history
            ):
                tokens.append(token)

            assert builder.build.call_args.kwargs.get("chat_history") == history
            return tokens

    tokens = asyncio.run(run())
    assert tokens == ["ok"]


def test_chat_service_memory_failure_degrades_gracefully() -> None:
    """长期记忆召回异常时仍使用知识库结果完成回答。"""
    from rag.chat_service import ChatService

    async def run():
        service = ChatService()
        fake_result = MagicMock(
            chunk_id="c1",
            text="knowledge",
            score=0.9,
            metadata={"title": "doc.md", "full_path": "doc.md", "chunk_index": 0},
        )

        with patch("rag.chat_service.Retriever") as MockRetriever, \
                patch("rag.chat_service.VectorStore"), \
                patch("rag.chat_service.Embedder"), \
                patch("rag.chat_service.LLM") as MockLLM, \
                patch("rag.chat_service.settings.MEMORY_ENABLED", True), \
                patch.object(service, "_recall_memories", new=AsyncMock(side_effect=RuntimeError("memory down"))):
            retriever = MockRetriever.return_value
            retriever.retrieve = AsyncMock(return_value=[fake_result])
            retriever.format_context = MagicMock(return_value="ctx")

            async def fake_stream(messages, temperature=None):
                yield "ok"

            MockLLM.return_value.chat_stream = fake_stream
            return [token async for token in service.ask_stream("q", db=None, user_id=1)]

    assert asyncio.run(run()) == ["ok"]
