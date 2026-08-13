"""
聊天服务 —— RAG 查询链路的唯一编排入口。

将 retriever → prompt_builder → llm 串成完整的查询管线，
上层（FastAPI 路由）只需调用 ask() 或 ask_stream()。
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from rag.embedding import Embedder
from rag.llm import LLM
from rag.prompt_builder import PromptBuilder
from rag.retriever import Retriever
from rag.vector_store import VectorStore


class ChatService:
    """RAG 聊天服务 —— 查询链路编排器。

    ask_stream() 除了 yield token，还会把检索到的 sources 存入 self.last_sources。
    """

    def __init__(self):
        self.last_sources: list[dict] = []

    async def ask_stream(
        self,
        question: str,
        db: AsyncSession,
    ) -> AsyncGenerator[str, None]:
        """流式 RAG 查询：检索 → 组装 prompt → LLM 流式回答。"""
        self.last_sources = []

        if not question.strip():
            yield "请输入问题。"
            return

        # 1. 检索
        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store)
        results = await retriever.retrieve(question)

        if not results:
            yield "抱歉，知识库中没有找到相关信息。"
            return

        # 记录 sources
        self.last_sources = [
            {
                "chunk_id": r.chunk_id,
                "text": r.text[:200],
                "score": r.score,
                "title": r.metadata.get("title", ""),
                "file_id": r.metadata.get("file_id"),
            }
            for r in results
        ]

        # 2. 组装 prompt
        context = retriever.format_context(results)
        builder = PromptBuilder()
        messages = builder.build(question=question, context=context)

        # 3. 调 LLM
        llm = LLM()
        async for token in llm.chat_stream(messages):
            yield token

    async def ask(
        self,
        question: str,
        db: AsyncSession,
    ) -> str:
        """非流式 RAG 查询，返回完整回答。

        Args:
            question: 用户自然语言问题。
            db: 数据库会话。

        Returns:
            LLM 的完整回答文本。
        """
        if not question.strip():
            return "请输入问题。"

        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store)
        results = await retriever.retrieve(question)

        if not results:
            return "抱歉，知识库中没有找到相关信息。"

        context = retriever.format_context(results)
        builder = PromptBuilder()
        messages = builder.build(question=question, context=context)

        llm = LLM()
        return await llm.chat(messages)
