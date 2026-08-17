"""知识库管理测试 —— 文件索引状态、单文件重建、覆盖上传。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.models import File, RagDocument


def test_knowledge_files_returns_rag_status() -> None:
    """/knowledge/files 返回每个文件的 RAG 索引状态。"""
    from app.api.v1.admin import rag_knowledge_files

    files = [File(id=1, title="a.md", slug="a", full_path="a", storage_key="a.md")]
    doc = RagDocument(id=10, file_id=1, status="completed", chunk_count=5)

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
            return FakeResult([doc])

    resp = asyncio.run(rag_knowledge_files("dummy-token", FakeDB()))
    assert resp["success"] is True
    assert resp["files"][0]["rag_status"] == "completed"
    assert resp["files"][0]["rag_chunk_count"] == 5


def test_rebuild_file_success() -> None:
    """/knowledge/rebuild-file 成功时重新入队并返回 pending。"""
    from app.api.v1.admin import rag_rebuild_file

    doc = RagDocument(id=10, file_id=1, status="pending")

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return doc

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("rag.ingest_service.IngestService", FakeIngest), \
                patch("rag.tasks.enqueue_rag_document_task", return_value=True):
            return await rag_rebuild_file(1, "dummy-token", FakeDB())

    resp = asyncio.run(run())
    assert resp["success"] is True
    assert resp["file_id"] == 1
    assert resp["status"] == "pending"


def test_rebuild_file_enqueue_failure_raises_500() -> None:
    """/knowledge/rebuild-file 投递失败时返回 500。"""
    from app.api.v1.admin import rag_rebuild_file

    doc = RagDocument(id=10, file_id=1, status="pending")

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return doc

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("rag.ingest_service.IngestService", FakeIngest), \
                patch("rag.tasks.enqueue_rag_document_task", return_value=False), \
                patch("rag.task_worker.mark_rag_document_failed", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc_info:
                await rag_rebuild_file(1, "dummy-token", FakeDB())
            return exc_info.value

    exc = asyncio.run(run())
    assert exc.status_code == 500


def test_upload_without_overwrite_rejects_existing() -> None:
    """不带 overwrite 上传同名文件仍报 400。"""
    from app.api.v1.admin import upload_file

    existing = File(id=1, title="a", slug="a", full_path="a", storage_key="a.md")

    class FakeUpload:
        filename = "a.md"

        async def read(self):
            return b"content"

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("app.api.v1.admin.get_file_by_full_path", AsyncMock(return_value=existing)), \
                patch("app.api.v1.admin.normalize_slug", return_value="a"):
            with pytest.raises(HTTPException) as exc_info:
                await upload_file(
                    file=FakeUpload(), folder_id=None, overwrite=False,
                    _="token", db=FakeDB(),
                )
            return exc_info.value

    exc = asyncio.run(run())
    assert exc.status_code == 400


def test_upload_overwrite_updates_and_requeues() -> None:
    """overwrite=True 时覆盖成功，更新 File 字段并重新入队。"""
    from app.api.v1.admin import upload_file

    existing = File(id=1, title="old", slug="a", full_path="a", storage_key="old.md")
    rag_doc = RagDocument(id=10, file_id=1, title="a", status="pending")

    class FakeUpload:
        filename = "a.md"

        async def read(self):
            return b"new content"

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return rag_doc

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("app.api.v1.admin.get_file_by_full_path", AsyncMock(return_value=existing)), \
                patch("app.core.storage.save_file_content", AsyncMock(return_value=True)), \
                patch("app.api.v1.admin.normalize_title", return_value="A"), \
                patch("app.api.v1.admin.normalize_slug", return_value="a"), \
                patch("app.api.v1.admin.extract_sort_order", return_value=0), \
                patch("rag.ingest_service.IngestService", FakeIngest), \
                patch("rag.tasks.enqueue_rag_document_task", return_value=True):
            return await upload_file(
                file=FakeUpload(), folder_id=None, overwrite=True,
                _="token", db=FakeDB(),
            )

    resp = asyncio.run(run())
    assert resp.success is True
    assert "overwritten" in resp.message.lower()
    assert existing.storage_key == "a.md"  # 更新了 storage_key


def test_upload_overwrite_enqueue_failure_marks_failed() -> None:
    """覆盖上传时 Celery 投递失败：文件仍保存，但索引标记 failed。"""
    from app.api.v1.admin import upload_file

    existing = File(id=1, title="old", slug="a", full_path="a", storage_key="old.md")
    rag_doc = RagDocument(id=10, file_id=1, title="a", status="pending")
    mark_failed = AsyncMock()

    class FakeUpload:
        filename = "a.md"

        async def read(self):
            return b"new content"

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return rag_doc

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("app.api.v1.admin.get_file_by_full_path", AsyncMock(return_value=existing)), \
                patch("app.core.storage.save_file_content", AsyncMock(return_value=True)), \
                patch("app.api.v1.admin.normalize_title", return_value="A"), \
                patch("app.api.v1.admin.normalize_slug", return_value="a"), \
                patch("app.api.v1.admin.extract_sort_order", return_value=0), \
                patch("rag.ingest_service.IngestService", FakeIngest), \
                patch("rag.tasks.enqueue_rag_document_task", return_value=False), \
                patch("rag.task_worker.mark_rag_document_failed", new=mark_failed):
            return await upload_file(
                file=FakeUpload(), folder_id=None, overwrite=True,
                _="token", db=FakeDB(),
            )

    resp = asyncio.run(run())
    assert resp.success is True  # 文件已保存
    assert "入队失败" in resp.message
    mark_failed.assert_awaited_once()


# ── 强制全量重建（force）──

def _make_rebuild_db(files, docs):
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
            return FakeResult(docs)

        async def commit(self):
            pass

    return FakeDB()


def test_rebuild_force_false_skips_completed() -> None:
    """force=False：completed 不重投。"""
    from app.api.v1.admin import rag_knowledge_rebuild

    files = [File(id=1, title="a.md", slug="a", full_path="a", storage_key="a.md")]
    completed = RagDocument(id=10, file_id=1, status="completed")

    async def run():
        with patch("rag.tasks.enqueue_rag_document_task", return_value=True):
            return await rag_knowledge_rebuild(
                False, "token", _make_rebuild_db(files, [completed])
            )

    resp = asyncio.run(run())
    assert resp["forced"] is False
    assert resp["requeued"] == 0
    assert resp["skipped"] == 1
    assert resp["enqueued"] == 0


def test_rebuild_force_true_requeues_completed() -> None:
    """force=True：completed 重置为 pending 并重新入队。"""
    from app.api.v1.admin import rag_knowledge_rebuild

    files = [File(id=1, title="a.md", slug="a", full_path="a", storage_key="a.md")]
    completed = RagDocument(id=10, file_id=1, status="completed")

    async def run():
        with patch("rag.tasks.enqueue_rag_document_task", return_value=True):
            return await rag_knowledge_rebuild(
                True, "token", _make_rebuild_db(files, [completed])
            )

    resp = asyncio.run(run())
    assert resp["forced"] is True
    assert resp["requeued"] == 1
    assert resp["enqueued"] == 1
    assert completed.status == "pending"


def test_rebuild_force_true_skips_processing() -> None:
    """force=True：processing 跳过，不被重置。"""
    from app.api.v1.admin import rag_knowledge_rebuild

    files = [File(id=1, title="a.md", slug="a", full_path="a", storage_key="a.md")]
    processing = RagDocument(id=10, file_id=1, status="processing")

    async def run():
        with patch("rag.tasks.enqueue_rag_document_task", return_value=True):
            return await rag_knowledge_rebuild(
                True, "token", _make_rebuild_db(files, [processing])
            )

    resp = asyncio.run(run())
    assert resp["skipped_processing"] == 1
    assert resp["requeued"] == 0
    assert processing.status == "processing"


def test_rebuild_force_enqueue_failure_marks_failed() -> None:
    """force=True 投递失败：标记 failed。"""
    from app.api.v1.admin import rag_knowledge_rebuild

    files = [File(id=1, title="a.md", slug="a", full_path="a", storage_key="a.md")]
    completed = RagDocument(id=10, file_id=1, status="completed")
    mark_failed = AsyncMock()

    async def run():
        with patch("rag.tasks.enqueue_rag_document_task", return_value=False), \
                patch("rag.task_worker.mark_rag_document_failed", new=mark_failed):
            return await rag_knowledge_rebuild(
                True, "token", _make_rebuild_db(files, [completed])
            )

    resp = asyncio.run(run())
    assert resp["failed_enqueue"] == 1
    mark_failed.assert_awaited_once()
