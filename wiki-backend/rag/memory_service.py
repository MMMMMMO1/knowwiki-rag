"""
Memory service —— 长期记忆的提取、存储与召回编排。

提取时机（谁决定什么该被记住）：
- 每轮对话结束后，由 Celery 后台任务调用 extract_and_save()，用 LLM 审视对话
  并输出「值得记住的事实」JSON，再向量化入库；
- 用户显式说「记住 XXX」时命中关键词，该条 importance 置为 1.0 强制保留。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from rag.embedding import Embedder
from rag.llm import LLM
from rag.memory_store import MemoryStore
from rag.schemas import Chunk


_MEMORY_EXTRACT_PROMPT = (
    "You are a memory extractor for a knowledge assistant. "
    "Review the conversation below and extract facts worth remembering long-term "
    "(user preferences, identity, project context, decisions, conclusions). "
    "Ignore greetings, small talk, and one-off questions. "
    'Respond with ONLY a JSON array, each item {"content": string, "importance": 0.0~1.0}. '
    "Return [] if nothing is worth remembering."
)


class MemoryService:
    """长期记忆编排：提取 → 向量化 → 存储；以及召回。"""

    def __init__(
        self,
        db: AsyncSession,
        embedder: Embedder | None = None,
        llm: LLM | None = None,
    ):
        self.db = db
        self.embedder = embedder or Embedder()
        self.llm = llm or LLM()

    async def extract_and_save(
        self,
        user_id: int,
        workspace_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> int:
        """从一轮对话中提取长期记忆并入库，返回新增条数。"""
        conversation = f"User: {user_message}\nAssistant: {assistant_message}"

        # 1. LLM extracts facts worth remembering
        facts = await self._extract_facts(conversation)

        # 2. Explicit "remember" phrase forces retention (importance=1.0)
        explicit = any(kw in user_message for kw in settings.MEMORY_EXPLICIT_KEYWORDS)

        # 3. Embed + persist
        store = MemoryStore(self.db)
        saved = 0
        for fact in facts:
            content = fact.get("content", "").strip()
            if not content:
                continue
            importance = 1.0 if explicit else float(fact.get("importance", 0.5))
            vectors = await self.embedder.embed(
                [Chunk.create(doc_id="memory", text=content)]
            )
            await store.insert(
                user_id=user_id,
                workspace_id=workspace_id,
                content=content,
                embedding=vectors[0],
                importance=importance,
                source_session_id=session_id,
            )
            saved += 1
        return saved

    async def recall(
        self,
        user_id: int,
        workspace_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """召回该用户在该工作区的相关记忆。"""
        top_k = top_k or settings.MEMORY_TOP_K
        vectors = await self.embedder.embed(
            [Chunk.create(doc_id="memory-query", text=query)]
        )
        store = MemoryStore(self.db)
        return await store.search(vectors[0], user_id, workspace_id, top_k)

    async def _extract_facts(self, conversation: str) -> list[dict[str, Any]]:
        """调用 LLM 提取事实列表；解析失败降级为空列表（不阻断主流程）。"""
        messages = [
            {"role": "system", "content": _MEMORY_EXTRACT_PROMPT},
            {"role": "user", "content": conversation},
        ]
        try:
            raw = await self.llm.chat(messages, temperature=0.2)
            return self._parse_facts(raw)
        except Exception:
            # Extraction runs in background; never break the chat flow on failure.
            return []

    @staticmethod
    def _parse_facts(raw: str) -> list[dict[str, Any]]:
        """稳健解析 LLM 输出的 JSON 数组（容忍 markdown 围栏）。"""
        text = raw.strip()
        # strip ```json fences if present
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []
        return []
