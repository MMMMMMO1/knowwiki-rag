"""Source metadata 与入队失败状态测试。"""

import asyncio
from unittest.mock import AsyncMock, patch

from rag.schemas import RetrievalResult


def test_splitter_adds_chunk_index() -> None:
    """splitter.split 给每个 chunk 的 metadata 加 chunk_index（从 0 开始）。"""
    from rag.splitter import TextSplitter
    from rag.schemas import Document

    doc = Document.create(title="t", content="a" * 2000, metadata={"file_id": 1})
    splitter = TextSplitter(chunk_size=500, chunk_overlap=0)
    chunks = splitter.split(doc)
    assert len(chunks) >= 2
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_build_sources_includes_full_metadata() -> None:
    """_build_sources 返回完整溯源字段（title/file_id/full_path/storage_key/chunk_index）。"""
    from rag.chat_service import ChatService

    result = RetrievalResult(
        chunk_id="c1",
        text="x" * 300,
        score=0.9,
        metadata={
            "title": "doc.md",
            "file_id": 42,
            "full_path": "docs/doc.md",
            "storage_key": "docs/doc.md",
            "chunk_index": 3,
        },
    )
    sources = ChatService()._build_sources([result])
    assert sources[0] == {
        "chunk_id": "c1",
        "text": "x" * 200,  # 截断 200
        "score": 0.9,
        "title": "doc.md",
        "file_id": 42,
        "full_path": "docs/doc.md",
        "storage_key": "docs/doc.md",
        "chunk_index": 3,
    }


def test_rag_ingest_enqueue_failure_returns_failed() -> None:
    """/rag/ingest 投递失败时响应 status 为 failed。"""
    from app.api.v1.rag import IngestRequest, rag_ingest
    from app.models import RagDocument

    doc = RagDocument(id=10, file_id=1, title="a.md", status="pending")

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return doc

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("app.api.v1.rag.IngestService", FakeIngest), \
                patch("rag.tasks.enqueue_rag_document_task", return_value=False), \
                patch("rag.task_worker.mark_rag_document_failed", new=AsyncMock()):
            return await rag_ingest(
                IngestRequest(file_id=1),
                FakeDB(),
                "dummy-token",
            )

    resp = asyncio.run(run())
    assert resp.status == "failed"
    assert resp.id == 10


def test_rag_ingest_enqueue_success_returns_pending() -> None:
    """/rag/ingest 投递成功时响应 status 为 pending。"""
    from app.api.v1.rag import IngestRequest, rag_ingest
    from app.models import RagDocument

    doc = RagDocument(id=11, file_id=2, title="b.md", status="pending")

    class FakeIngest:
        def __init__(self, db):
            pass

        async def ingest(self, file_id):
            return doc

    class FakeDB:
        async def commit(self):
            pass

    async def run():
        with patch("app.api.v1.rag.IngestService", FakeIngest), \
                patch("rag.tasks.enqueue_rag_document_task", return_value=True):
            return await rag_ingest(
                IngestRequest(file_id=2),
                FakeDB(),
                "dummy-token",
            )

    resp = asyncio.run(run())
    assert resp.status == "pending"


def test_pipeline_metadata_flows_to_chunks() -> None:
    """task_worker 写入 chunk 时 metadata 含 title/full_path/storage_key/chunk_index。"""
    from unittest.mock import patch

    from app.models import File, RagDocument
    from rag.schemas import Document
    from rag.task_worker import RagIndexingProcessor

    doc = RagDocument(id=1, file_id=5, title="a.md", content_hash=None, status="processing")
    file = File(id=5, title="a.md", slug="a", full_path="docs/a.md", storage_key="docs/a.md")

    captured = {}

    class FakeLoader:
        def load_bytes(self, file_name, content, metadata):
            captured["doc_metadata"] = metadata
            return Document.create(title=file_name, content="hello " * 200, metadata=metadata)

    class FakeEmbedder:
        async def embed(self, chunks):
            return [[0.0] * 1024 for _ in chunks]

    class FakeStore:
        def __init__(self, db):
            pass

        async def delete_by_document(self, document):
            pass

        async def insert(self, document, chunks, vectors):
            captured["chunks"] = chunks

    class FakeDB:
        pass

    async def run():
        processor = RagIndexingProcessor()
        processor._load_raw_bytes = AsyncMock(return_value=(b"x", file))
        with patch("rag.task_worker.DocumentLoader", FakeLoader), \
                patch("rag.task_worker.Embedder", FakeEmbedder), \
                patch("rag.task_worker.VectorStore", FakeStore):
            await processor._run_pipeline(FakeDB(), doc)

    asyncio.run(run())

    assert captured["doc_metadata"] == {
        "file_id": 5, "title": "a.md", "full_path": "docs/a.md", "storage_key": "docs/a.md",
    }
    chunks = captured["chunks"]
    assert len(chunks) >= 2
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert c.metadata["title"] == "a.md"
        assert c.metadata["full_path"] == "docs/a.md"
        assert c.metadata["storage_key"] == "docs/a.md"


def test_ask_populates_last_sources_with_full_metadata() -> None:
    """ChatService.ask 后 last_sources 从真实 RetrievalResult.metadata 输出完整字段。"""
    from unittest.mock import MagicMock, patch

    from rag.chat_service import ChatService

    class FakeLLM:
        async def chat(self, messages, temperature=0.7, max_tokens=None, timeout=120.0):
            return "答案"

    class FakeRetriever:
        def __init__(self, *args, **kwargs):
            pass

        async def retrieve(self, query):
            return [
                RetrievalResult(
                    chunk_id="c1", text="text", score=0.9,
                    metadata={
                        "title": "a.md", "file_id": 5,
                        "full_path": "docs/a.md", "storage_key": "docs/a.md",
                        "chunk_index": 0,
                    },
                )
            ]

        def format_context(self, results):
            return "context"

    async def run():
        service = ChatService()
        service._rewrite_query = AsyncMock(return_value="q")
        with patch("rag.chat_service.Retriever", FakeRetriever), \
                patch("rag.chat_service.LLM", return_value=FakeLLM()), \
                patch("rag.chat_service.settings.MEMORY_ENABLED", False):
            await service.ask("hi", MagicMock(), chat_history=None)

        s = service.last_sources[0]
        assert s["title"] == "a.md"
        assert s["file_id"] == 5
        assert s["full_path"] == "docs/a.md"
        assert s["storage_key"] == "docs/a.md"
        assert s["chunk_index"] == 0

    asyncio.run(run())


def test_reader_cannot_override_rag_params() -> None:
    """普通用户无法覆盖 prompt/model/temperature，admin 可以。"""
    from app.api.v1.chat import ChatStreamRequest, _resolve_chat_overrides
    from app.models import User

    request = ChatStreamRequest(
        message="hi", session_id="s", prompt="evil", model="expensive", temperature=0.1
    )
    reader = User(id=1, username="r", role="reader")
    admin = User(id=2, username="a", role="admin")

    assert _resolve_chat_overrides(request, reader) == (None, None, None)
    assert _resolve_chat_overrides(request, admin) == ("evil", "expensive", 0.1)
