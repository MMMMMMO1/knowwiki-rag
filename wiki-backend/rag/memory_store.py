"""
Memory store —— 长期记忆的数据访问层。

与 VectorStore 类似，但操作 memories 表：写入（向量化后的记忆）与向量召回，
均按 user_id + workspace_id 隔离，保证记忆只属于「某个用户 + 某个工作区」。
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory
from app.core.config import settings


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
        """按内容哈希幂等写入，并限制单用户工作区的记忆总量。"""
        normalized_content = content.strip()
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        importance = min(1.0, max(0.0, float(importance)))

        lock_key = int(content_hash[:15], 16)
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        existing_result = await self.db.execute(
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.workspace_id == workspace_id)
            # 兼容 0006 迁移中由 PostgreSQL md5() 回填的旧记录；命中后
            # 统一升级为 SHA-256，避免迁移后的首次写入产生重复记忆。
            .where(
                or_(
                    Memory.content_hash == content_hash,
                    Memory.content == normalized_content,
                )
            )
            .with_for_update()
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            existing.content_hash = content_hash
            existing.importance = max(existing.importance, importance)
            existing.embedding = embedding
            existing.source_session_id = source_session_id
            await self.db.flush()
            return existing

        memory = Memory(
            user_id=user_id,
            workspace_id=workspace_id,
            content=normalized_content,
            content_hash=content_hash,
            embedding=embedding,
            importance=importance,
            source_session_id=source_session_id,
        )
        self.db.add(memory)
        await self.db.flush()
        await self._prune(user_id, workspace_id)
        return memory

    async def _prune(self, user_id: int, workspace_id: str) -> None:
        """保留重要性最高且最近更新的有限条记忆。"""
        max_items = max(1, settings.MEMORY_MAX_PER_USER_WORKSPACE)
        result = await self.db.execute(
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.workspace_id == workspace_id)
            .order_by(Memory.importance.desc(), Memory.updated_at.desc(), Memory.id.desc())
            .offset(max_items)
        )
        for stale in result.scalars().all():
            await self.db.delete(stale)

    async def search(
        self,
        query_vector: list[float],
        user_id: int,
        workspace_id: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """向量召回该用户在该工作区的相关记忆，按相似度降序。"""
        score_expr = 1 - Memory.embedding.cosine_distance(query_vector)
        query = (
            select(
                Memory.content,
                Memory.importance,
                score_expr.label("score"),
            )
            .where(Memory.user_id == user_id)
            .where(Memory.workspace_id == workspace_id)
            .where(Memory.embedding.is_not(None))
            .where(score_expr >= settings.MEMORY_MIN_SCORE)
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
