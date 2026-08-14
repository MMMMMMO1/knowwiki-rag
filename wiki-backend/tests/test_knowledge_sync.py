"""知识库手动重试范围测试 —— 验证 /knowledge/sync 只处理 failed。"""

import asyncio
from unittest.mock import patch


def test_knowledge_sync_only_selects_failed() -> None:
    """/knowledge/sync 的查询只筛选 failed，不再重投 pending。"""
    from app.api.v1.admin import rag_knowledge_sync

    captured = {}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeDB:
        async def execute(self, stmt, *args, **kwargs):
            captured["stmt"] = stmt
            return FakeResult()

        async def commit(self):
            pass

    with patch("rag.tasks.enqueue_rag_document_task", return_value=True):
        resp = asyncio.run(rag_knowledge_sync("dummy-token", FakeDB()))

    compiled = captured["stmt"].compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled).lower()
    assert "failed" in sql
    assert "pending" not in sql

    # 空结果：返回 0 个待处理，且没有入队失败
    assert resp["scheduled"] == 0
    assert resp["enqueued"] == 0
    assert resp["failed_enqueue"] == 0
