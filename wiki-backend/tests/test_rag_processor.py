"""RagIndexingProcessor 单元测试 —— 用 mock 模拟 DB 和流水线组件。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rag.task_worker import (
    RagIndexingProcessor,
    RetryableIndexingError,
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


def _patch_session(doc: RagDocument | None):
    """patch AsyncSessionLocal，返回可重复进入的 fake session。"""
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


def test_processor_success_marks_completed() -> None:
    doc = _make_doc(status="pending")
    ctx, session = _patch_session(doc)

    async def fake_pipeline(self, db, d):
        d.chunk_count = 5

    with ctx, patch.object(RagIndexingProcessor, "_run_pipeline", fake_pipeline):
        processor = RagIndexingProcessor()
        asyncio.run(processor.process(1))

    assert doc.status == "completed"
    assert doc.error_message is None
    assert session.commit_count >= 1


def test_processor_failure_marks_failed_and_reraises() -> None:
    doc = _make_doc(status="pending")
    ctx, _ = _patch_session(doc)

    async def fake_pipeline(self, db, d):
        raise ValueError("文档内容为空，无法索引")

    with ctx, patch.object(RagIndexingProcessor, "_run_pipeline", fake_pipeline), \
            patch.object(RagIndexingProcessor, "_mark_failed", new_callable=AsyncMock) as mark_failed:
        processor = RagIndexingProcessor()
        with patch.object(RagIndexingProcessor, "_mark_failed", mark_failed):
            try:
                asyncio.run(processor.process(1))
                assert False, "应重新抛出异常"
            except ValueError:
                pass

    mark_failed.assert_awaited_once()
    # 错误信息经过脱敏
    args = mark_failed.await_args.args
    assert "文档内容为空" in args[1]


def test_processor_retryable_error_reraises_retryable() -> None:
    doc = _make_doc(status="pending")
    ctx, _ = _patch_session(doc)

    async def fake_pipeline(self, db, d):
        raise RetryableIndexingError("S3 文件为空或不存在")

    with ctx, patch.object(RagIndexingProcessor, "_run_pipeline", fake_pipeline), \
            patch.object(RagIndexingProcessor, "_mark_failed", new_callable=AsyncMock):
        processor = RagIndexingProcessor()
        try:
            asyncio.run(processor.process(1))
            assert False, "应重新抛出 RetryableIndexingError"
        except RetryableIndexingError:
            pass
