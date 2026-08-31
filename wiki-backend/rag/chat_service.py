"""
聊天服务 —— RAG 查询链路的唯一编排入口。

将 retriever → prompt_builder → llm 串成完整的查询管线，
上层（FastAPI 路由）只需调用 ask() 或 ask_stream()。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from rag.embedding import Embedder
from rag.llm import LLM
from rag.prompt_builder import PromptBuilder
from rag.retriever import Retriever
from rag.vector_store import VectorStore


logger = logging.getLogger(__name__)


# Prompt for rewriting a multi-turn follow-up into a standalone retrieval question.
_REWRITE_PROMPT = (
    "你是查询改写器。根据对话历史，把用户当前的追问改写为一个"
    "完整、独立、不依赖上下文、适合向量检索的中文问题。"
    "只输出改写后的问题，不要输出任何解释或额外内容。"
)


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

        # 0. Rewrite multi-turn question into a standalone retrieval query
        retrieval_query = await self._rewrite_query(question, chat_history)

        # 1. Retrieve (filtered by workspace)
        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store, workspace_id=workspace_id)
        results = await retriever.retrieve(retrieval_query)

        if not results:
            yield "抱歉，知识库中没有找到相关信息。"
            return

        # 记录前端需要的公开来源字段；内部 storage_key 不进入普通用户响应。
        self.last_sources = self._build_sources(results)

        # 2. Recall long-term memories (kept separate from documents)
        memory_texts: list[str] = []
        if settings.MEMORY_ENABLED and user_id is not None:
            try:
                memory_texts = await self._recall_memories(
                    db, user_id, workspace_id, retrieval_query
                )
            except Exception as exc:
                logger.warning(
                    "Memory recall unavailable; continuing without memory: %s",
                    type(exc).__name__,
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
        temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
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

        retrieval_query = await self._rewrite_query(question, chat_history)

        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store, workspace_id=workspace_id)
        results = await retriever.retrieve(retrieval_query)

        if not results:
            return "抱歉，知识库中没有找到相关信息。"

        self.last_sources = self._build_sources(results)

        memory_texts: list[str] = []
        if settings.MEMORY_ENABLED and user_id is not None:
            try:
                memory_texts = await self._recall_memories(
                    db, user_id, workspace_id, retrieval_query
                )
            except Exception as exc:
                logger.warning(
                    "Memory recall unavailable; continuing without memory: %s",
                    type(exc).__name__,
                )

        context = self._build_context(retriever, results, memory_texts)
        builder = PromptBuilder(system_prompt=prompt)
        messages = builder.build(
            question=question,
            context=context,
            chat_history=chat_history,
        )

        llm = LLM(model=model)
        temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
        return await llm.chat(messages, temperature=temp)

    async def debug(
        self,
        question: str,
        db: AsyncSession,
        chat_history: list[dict[str, str]] | None = None,
        workspace_id: str = "default",
        user_id: int | None = None,
        prompt: str | None = None,
    ) -> dict:
        """运行完整检索链路并返回各阶段中间结果（不调用 LLM 生成回答）。"""
        retrieval_query = await self._rewrite_query(question, chat_history)

        store = VectorStore(db)
        embedder = Embedder()
        retriever = Retriever(embedder, store, workspace_id=workspace_id)
        retrieval = await retriever.retrieve_debug(retrieval_query)

        # 记忆召回（与检索一致，使用 retrieval_query）
        memory_texts: list[str] = []
        if settings.MEMORY_ENABLED and user_id is not None:
            try:
                memory_texts = await self._recall_memories(
                    db, user_id, workspace_id, retrieval_query
                )
            except Exception as exc:
                logger.warning(
                    "Memory recall unavailable; continuing without memory: %s",
                    type(exc).__name__,
                )

        # 组装 prompt（不调用 LLM，只返回 messages 供排查）
        results = self._dicts_to_results(retrieval["final_results"])
        context = self._build_context(retriever, results, memory_texts)
        builder = PromptBuilder(system_prompt=prompt)
        messages = builder.build(
            question=question,
            context=context,
            chat_history=chat_history,
        )

        return {
            "original_question": question,
            "retrieval_query": retrieval_query,
            "chat_history": chat_history or [],
            "vector_results": retrieval["vector_results"],
            "keyword_results": retrieval["keyword_results"],
            "merged_results": retrieval["merged_results"],
            "rerank_results": retrieval["rerank_results"],
            "final_sources": retrieval["final_results"],
            "memory_texts": memory_texts,
            "prompt_messages": messages,
            "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE,
        }

    @staticmethod
    def _dicts_to_results(items: list[dict]) -> list:
        """把 debug 的统一 dict 转回 RetrievalResult，供 _build_context 复用。"""
        from rag.schemas import RetrievalResult

        return [
            RetrievalResult(
                chunk_id=item["chunk_id"],
                text=item["text"],
                score=item["score"],
                metadata={
                    "title": item.get("title", ""),
                    "full_path": item.get("full_path", ""),
                    "storage_key": item.get("storage_key", ""),
                    "file_id": item.get("file_id"),
                    "chunk_index": item.get("chunk_index"),
                },
            )
            for item in items
        ]

    async def _rewrite_query(
        self,
        question: str,
        chat_history: list[dict[str, str]] | None,
    ) -> str:
        """把多轮追问改写为可独立检索的问题；无历史或失败时降级为原始问题。

        低延迟保护：低温度、限制 max_tokens、短超时；不使用用户传入的 model。
        """
        if not chat_history:
            return question
        try:
            history_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in chat_history
            )
            llm = LLM()
            messages = [
                {"role": "system", "content": _REWRITE_PROMPT},
                {
                    "role": "user",
                    "content": f"对话历史：\n{history_text}\n\n用户当前追问：{question}",
                },
            ]
            rewritten = (
                await llm.chat(messages, temperature=0.0, max_tokens=64, timeout=15.0)
            ).strip()
            return rewritten or question
        except Exception:
            # Rewrite must never block the chat flow; fall back to the original question.
            return question

    def _build_sources(self, results: list) -> list[dict]:
        """把检索结果组装为前端 sources，仅包含可公开的引用信息。"""
        return [
            {
                "chunk_id": r.chunk_id,
                "text": r.text[:200],
                "score": r.score,
                "title": r.metadata.get("title", ""),
                "file_id": r.metadata.get("file_id"),
                "full_path": r.metadata.get("full_path", ""),
                "chunk_index": r.metadata.get("chunk_index"),
            }
            for r in results
        ]

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
