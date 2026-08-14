"""RagIndexingProcessor 单元测试 —— 用 mock 模拟 DB 和流水线组件。"""

import asyncio
from unittest.mock import AsyncMock, patch

from rag.exceptions import RetryableIndexingError
from rag.task_worker import (
    RagIndexingProcessor,
    reset_stale_processing_documents,
    sanitize_error_message,
)
from app.models import RagDocument


def _make_doc(status: str = "pending") -> RagDocument:
    doc = RagDocument(id=1, file_id=10, doc_id="uuid", title="test", status=status)
    doc.id = 1
    return doc


class _FakeResult:
    def __init__(self, item):
        self._item = item

    def scalar_one_or_none(self):
        return self._item


class _FakeSession:
    """模拟 AsyncSession：execute 返回文档，支持 commit / rollback。"""

    def __init__(self, doc: RagDocument | None):
        self.doc = doc
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, *args, **kwargs):
        return _FakeResult(self.doc)

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


def _patch_pipeline_session(doc: RagDocument | None):
    """patch AsyncSessionLocal，返回 pipeline 阶段的 fake session。"""
    session = _FakeSession(doc)
    return patch(
        "rag.task_worker.AsyncSessionLocal",
        return_value=session,
    ), session


def test_sanitize_error_message_redacts_keys() -> None:
    msg = "Embedding 失败: error=401, key=sk-test-fake-key-123456, auth=Bearer fake-token-abc"
    clean = sanitize_error_message(msg)
    assert "sk-test-fake-key-123456" not in clean
    assert "fake-token-abc" not in clean
    assert "***" in clean


def _claim_true(self, rag_document_id):
    async def _inner():
        return True
    return _inner()


def test_processor_success_marks_completed() -> None:
    doc = _make_doc(status="processing")
    ctx, session = _patch_pipeline_session(doc)

    async def fake_pipeline(self, db, d):
        d.chunk_count = 5

    with ctx, \
            patch.object(RagIndexingProcessor, "_claim_processing", _claim_true), \
            patch.object(RagIndexingProcessor, "_run_pipeline", fake_pipeline):
        processor = RagIndexingProcessor()
        result = asyncio.run(processor.process(1))

    assert result == "completed"
    assert doc.status == "completed"
    assert doc.error_message is None
    assert session.commit_count >= 1


def test_processor_skips_when_claim_fails() -> None:
    """重复消息 / 已完成任务：抢占失败时跳过，不重复处理。"""
    doc = _make_doc(status="completed")
    ctx, _ = _patch_pipeline_session(doc)

    async def claim_false(self, rag_document_id):
        return False

    with ctx, patch.object(RagIndexingProcessor, "_claim_processing", claim_false):
        processor = RagIndexingProcessor()
        result = asyncio.run(processor.process(1))

    assert result == "skipped"
    assert doc.status == "completed"


def test_processor_failure_marks_failed_and_reraises() -> None:
    doc = _make_doc(status="processing")
    ctx, _ = _patch_pipeline_session(doc)

    async def fake_pipeline(self, db, d):
        raise ValueError("文档内容为空，无法索引")

    with ctx, \
            patch.object(RagIndexingProcessor, "_claim_processing", _claim_true), \
            patch.object(RagIndexingProcessor, "_run_pipeline", fake_pipeline), \
            patch.object(RagIndexingProcessor, "_mark_failed", new_callable=AsyncMock) as mark_failed:
        processor = RagIndexingProcessor()
        try:
            asyncio.run(processor.process(1))
            assert False, "应重新抛出异常"
        except ValueError:
            pass

    mark_failed.assert_awaited_once()
    # 错误信息经过脱敏，且 retryable=False
    args = mark_failed.await_args.args
    assert "文档内容为空" in args[1]
    assert mark_failed.await_args.kwargs.get("retryable") is False


def test_processor_retryable_error_reraises_retryable() -> None:
    """可重试错误：重新抛出 RetryableIndexingError，并标注 retryable=True。"""
    doc = _make_doc(status="processing")
    ctx, _ = _patch_pipeline_session(doc)

    async def fake_pipeline(self, db, d):
        raise RetryableIndexingError("S3 文件为空或不存在")

    with ctx, \
            patch.object(RagIndexingProcessor, "_claim_processing", _claim_true), \
            patch.object(RagIndexingProcessor, "_run_pipeline", fake_pipeline), \
            patch.object(RagIndexingProcessor, "_mark_failed", new_callable=AsyncMock) as mark_failed:
        processor = RagIndexingProcessor()
        try:
            asyncio.run(processor.process(1))
            assert False, "应重新抛出 RetryableIndexingError"
        except RetryableIndexingError:
            pass

    # retryable=True 被传给 _mark_failed
    assert mark_failed.await_args.kwargs.get("retryable") is True


def test_load_raw_bytes_deleted_file_is_final() -> None:
    """文件已被删除（file_id 无对应 File）：最终失败，抛 ValueError。"""
    doc = _make_doc()
    session = _FakeSession(None)  # scalar_one_or_none 返回 None → 文件不存在

    processor = RagIndexingProcessor()
    try:
        asyncio.run(processor._load_raw_bytes(session, doc))
        assert False, "应抛 ValueError"
    except ValueError as e:
        assert "已被删除" in str(e)


class _FakeStaleResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeStaleSession:
    """模拟 reset_stale_processing_documents 用到的 session。"""

    def __init__(self, ids):
        self._ids = ids

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, *args, **kwargs):
        return _FakeStaleResult([(i,) for i in self._ids])

    async def commit(self):
        pass


def test_reset_stale_processing_documents_returns_ids() -> None:
    """有僵尸任务：重置为 pending 并返回被重置的 id 列表。"""
    session = _FakeStaleSession([1, 2])
    with patch("rag.task_worker.AsyncSessionLocal", return_value=session):
        ids = asyncio.run(reset_stale_processing_documents())

    assert ids == [1, 2]


def test_reset_stale_processing_documents_empty() -> None:
    """无僵尸任务：返回空列表。"""
    session = _FakeStaleSession([])
    with patch("rag.task_worker.AsyncSessionLocal", return_value=session):
        ids = asyncio.run(reset_stale_processing_documents())

    assert ids == []
