"""
聊天服务 —— RAG 查询链路的唯一编排入口。

将 retriever → prompt_builder → llm 串成完整的查询管线，
上层（FastAPI 路由）只需调用 ask() 或 ask_stream()。
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
        prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        chat_history: list[dict[str, str]] | None = None,
        workspace_id: str = "default",
        user_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式 RAG 查询：检索 → 组装 prompt → LLM 流式回答。

        Args:
            question: 用户自然语言问题。
            db: 数据库会话。
            prompt: 自定义 system prompt（为空则用默认）。
            model: 自定义 LLM 模型名（为空则用配置默认）。
            temperature: 生成温度（为空则用默认 0.7）。
            chat_history: 同会话最近若干条历史消息，可为空。
            workspace_id: 命名空间，决定检索哪个知识域。
            user_id: 用户 ID，用于召回长期记忆（为空则不召回）。
        """
        self.last_sources = []

        if not question.strip():
            yield "请输入问题。"
            return

        # 1. Retrieve (filtered by workspace)
        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store, workspace_id=workspace_id)
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

        # 2. Recall long-term memories (kept separate from documents)
        memory_texts: list[str] = []
        if settings.MEMORY_ENABLED and user_id is not None:
            memory_texts = await self._recall_memories(
                db, user_id, workspace_id, question
            )

        # 3. Build prompt (documents + memories in separate sections)
        context = self._build_context(retriever, results, memory_texts)
        builder = PromptBuilder(system_prompt=prompt)
        messages = builder.build(
            question=question,
            context=context,
            chat_history=chat_history,
        )

        # 3. 调 LLM（传入自定义 model 与 temperature）
        llm = LLM(model=model)
        temp = temperature if temperature is not None else 0.7
        async for token in llm.chat_stream(messages, temperature=temp):
            yield token

    async def ask(
        self,
        question: str,
        db: AsyncSession,
        prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        chat_history: list[dict[str, str]] | None = None,
        workspace_id: str = "default",
        user_id: int | None = None,
    ) -> str:
        """非流式 RAG 查询，返回完整回答。

        Args:
            question: 用户自然语言问题。
            db: 数据库会话。
            prompt: 自定义 system prompt（为空则用默认）。
            model: 自定义 LLM 模型名（为空则用配置默认）。
            temperature: 生成温度（为空则用默认 0.7）。
            chat_history: 同会话最近若干条历史消息，可为空。
            workspace_id: 命名空间，决定检索哪个知识域。
            user_id: 用户 ID，用于召回长期记忆（为空则不召回）。

        Returns:
            LLM 的完整回答文本。
        """
        if not question.strip():
            return "请输入问题。"

        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store, workspace_id=workspace_id)
        results = await retriever.retrieve(question)

        if not results:
            return "抱歉，知识库中没有找到相关信息。"

        memory_texts: list[str] = []
        if settings.MEMORY_ENABLED and user_id is not None:
            memory_texts = await self._recall_memories(
                db, user_id, workspace_id, question
            )

        context = self._build_context(retriever, results, memory_texts)
        builder = PromptBuilder(system_prompt=prompt)
        messages = builder.build(
            question=question,
            context=context,
            chat_history=chat_history,
        )

        llm = LLM(model=model)
        temp = temperature if temperature is not None else 0.7
        return await llm.chat(messages, temperature=temp)

    async def _recall_memories(
        self,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        query: str,
    ) -> list[str]:
        """召回该用户在该工作区的长期记忆，返回内容文本列表。"""
        from rag.memory_service import MemoryService

        service = MemoryService(db)
        memories = await service.recall(user_id, workspace_id, query)
        return [m["content"] for m in memories]

    def _build_context(
        self,
        retriever: Retriever,
        results: list,
        memory_texts: list[str],
    ) -> str:
        """分开标注拼装上下文：文档块与记忆块分栏，避免 LLM 混淆两类来源。"""
        parts: list[str] = []
        doc_block = retriever.format_context(results)
        if doc_block:
            parts.append(f"=== 知识库资料 ===\n{doc_block}")
        if memory_texts:
            memory_block = "\n".join(f"- {m}" for m in memory_texts)
            parts.append(f"=== 关于你的长期记忆 ===\n{memory_block}")
        return "\n\n".join(parts)
