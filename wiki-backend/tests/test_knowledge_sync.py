"""知识库手动重试与全量补齐测试。"""

import asyncio
from unittest.mock import patch

from app.models import File, RagDocument


def test_knowledge_sync_covers_failed_and_pending() -> None:
    """/knowledge/sync 的查询筛选 failed + pending，不触碰 processing。"""
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
    # 用带引号的字面量匹配状态值，避免与列名（如 processing_started_at）混淆
    assert "'failed'" in sql
    assert "'pending'" in sql
    assert "'processing'" not in sql
    assert "'completed'" not in sql
    assert "'skipped'" not in sql

    # 空结果：返回 0 个待处理，且没有入队失败
    assert resp["scheduled"] == 0
    assert resp["enqueued"] == 0
    assert resp["failed_enqueue"] == 0


def test_knowledge_rebuild_creates_and_requeues() -> None:
    """/knowledge/rebuild 扫描 files：缺失的创建、failed/pending 重投、其余跳过。"""
    from app.api.v1.admin import rag_knowledge_rebuild

    files = [
        File(id=1, title="a.md"),
        File(id=2, title="b.md"),
        File(id=3, title="c.md"),
    ]
    failed_doc = RagDocument(id=20, file_id=2, status="failed")
    completed_doc = RagDocument(id=30, file_id=3, status="completed")

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class FakeDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResult(files)
            return FakeResult([failed_doc, completed_doc])

        async def commit(self):
            pass

    fake_new_doc = RagDocument(id=10, file_id=1, status="pending")

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return fake_new_doc

    fake_db = FakeDB()
    with patch("rag.ingest_service.IngestService", FakeIngest), \
            patch("rag.tasks.enqueue_rag_document_task", return_value=True):
        resp = asyncio.run(rag_knowledge_rebuild("dummy-token", fake_db))

    # file 1 无记录 → created；file 2 failed → requeued；file 3 completed → skipped
    assert resp["created"] == 1
    assert resp["requeued"] == 1
    assert resp["skipped"] == 1
    assert resp["enqueued"] == 2
    assert resp["failed_enqueue"] == 0
