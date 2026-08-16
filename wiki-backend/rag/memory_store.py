"""
Memory store —— 长期记忆的数据访问层。

与 VectorStore 类似，但操作 memories 表：写入（向量化后的记忆）与向量召回，
均按 user_id + workspace_id 隔离，保证记忆只属于「某个用户 + 某个工作区」。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory


class MemoryStore:
    """memories 表的读写 —— 长期记忆向量存取。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(
        self,
        user_id: int,
        workspace_id: str,
        content: str,
        embedding: list[float],
        importance: float = 0.5,
        source_session_id: str | None = None,
    ) -> Memory:
        """写入一条长期记忆。"""
        memory = Memory(
            user_id=user_id,
            workspace_id=workspace_id,
            content=content,
            embedding=embedding,
            importance=importance,
            source_session_id=source_session_id,
        )
        self.db.add(memory)
        await self.db.flush()
        return memory

    async def search(
        self,
        query_vector: list[float],
        user_id: int,
        workspace_id: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """向量召回该用户在该工作区的相关记忆，按相似度降序。"""
        query = (
            select(
                Memory.content,
                Memory.importance,
                (1 - Memory.embedding.cosine_distance(query_vector)).label("score"),
            )
            .where(Memory.user_id == user_id)
            .where(Memory.workspace_id == workspace_id)
            .where(Memory.embedding.is_not(None))
            .order_by(Memory.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
        result = await self.db.execute(query)
        return [
            {
                "content": row.content,
                "importance": row.importance,
                "score": round(float(row.score), 4),
            }
            for row in result.all()
        ]
