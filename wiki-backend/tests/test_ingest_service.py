"""IngestService 幂等性测试 —— 验证同一 file_id 不会创建多条 RagDocument。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from rag.ingest_service import IngestService
from app.models import File, RagDocument


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalar_one_or_none(self):
        return self._items[0] if len(self._items) == 1 else None

    def scalars(self):
        return _FakeScalars(self._items)


def _make_db(execute_side_effect) -> AsyncMock:
    """构造一个混合 mock：execute/flush/delete 为 async，add 为 sync。"""
    db = AsyncMock()
    db.execute.side_effect = execute_side_effect
    db.add = MagicMock()  # SQLAlchemy 的 add 是同步方法
    return db


def _make_file(file_id: int = 42) -> File:
    return File(id=file_id, title="test", slug="test", full_path="test", storage_key="test.txt")


def _make_doc(file_id: int, title: str = "test", status: str = "completed") -> RagDocument:
    doc = RagDocument(file_id=file_id, doc_id="doc-uuid", title=title, status=status)
    doc.id = 1
    return doc


def test_ingest_creates_record_when_none_exists() -> None:
    """无历史记录时创建新记录。"""
    file = _make_file()
    db = _make_db([
        _FakeResult([file]),   # 第一次查询 File
        _FakeResult([]),       # 查询 RagDocument（无记录）
    ])
    service = IngestService(db)

    doc = asyncio.run(service.ingest(file_id=42))

    assert doc is not None
    assert doc.status == "pending"
    assert doc.file_id == 42
    # 调用了一次 add
    db.add.assert_called_once()


def test_ingest_is_idempotent_same_file_id() -> None:
    """同一 file_id 已有记录时复用并重置为 pending，不新建。"""
    file = _make_file()
    existing = _make_doc(file_id=42, status="failed")
    existing.error_message = "old error"

    db = _make_db([
        _FakeResult([file]),          # 查询 File
        _FakeResult([existing]),      # 查询 RagDocument（已有 1 条）
    ])
    service = IngestService(db)

    doc = asyncio.run(service.ingest(file_id=42))

    # 复用原记录，而不是新建
    assert doc is existing
    assert doc.status == "pending"
    assert doc.error_message is None
    # 未调用 add（没有新建记录）
    db.add.assert_not_called()


def test_ingest_cleans_duplicate_records() -> None:
    """历史遗留的多条重复记录：保留第一条，删除其余。"""
    file = _make_file()
    first = _make_doc(file_id=42, status="completed")
    first.id = 1
    dup = _make_doc(file_id=42, status="completed")
    dup.id = 2

    db = _make_db([
        _FakeResult([file]),               # 查询 File
        _FakeResult([first, dup]),         # 查询 RagDocument（2 条重复）
    ])
    service = IngestService(db)

    doc = asyncio.run(service.ingest(file_id=42))

    # 保留第一条
    assert doc is first
    assert doc.status == "pending"
    # 删除多余的那条
    db.delete.assert_called_once_with(dup)
    # 未新建
    db.add.assert_not_called()
