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


def test_build_sources_excludes_internal_storage_key() -> None:
    """普通聊天来源保留公开溯源字段，但不返回内部 storage_key。"""
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

        async def ingest(self, file_id, workspace_id=None):
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
                type("Admin", (), {"role": "admin"})(),
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

        async def ingest(self, file_id, workspace_id=None):
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
                type("Admin", (), {"role": "admin"})(),
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

    class FakeUpdateResult:
        rowcount = 1

    class FakeDB:
        async def execute(self, *args, **kwargs):
            return FakeUpdateResult()

    async def run():
        processor = RagIndexingProcessor()
        processor._load_raw_bytes = AsyncMock(return_value=(b"x", file))
        with patch("rag.task_worker.DocumentLoader", FakeLoader), \
                patch("rag.task_worker.Embedder", FakeEmbedder), \
                patch("rag.task_worker.VectorStore", FakeStore):
            published = await processor._run_pipeline(FakeDB(), doc, 1)
            assert published is True

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


def test_ask_populates_last_sources_without_internal_storage_key() -> None:
    """普通聊天来源包含公开字段，但不泄露内部 storage_key。"""
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
        assert "storage_key" not in s
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


def test_reader_workspace_id_falls_back_to_default() -> None:
    """reader 传 workspace_id='other' 时实际用 'default'；admin 可传自定义。"""
    from app.api.v1.chat import ChatStreamRequest, _resolve_workspace_id
    from app.models import User

    request = ChatStreamRequest(message="hi", session_id="s", workspace_id="other")
    reader = User(id=1, username="r", role="reader")
    admin = User(id=2, username="a", role="admin")

    assert _resolve_workspace_id(request, reader) == "default"
    assert _resolve_workspace_id(request, admin) == "other"
    # admin 未指定时也回退 default
    empty = ChatStreamRequest(message="hi", session_id="s")
    assert _resolve_workspace_id(empty, admin) == "default"


def test_vector_index_migration_gated_by_config() -> None:
    """默认配置下不自动执行 HNSW 建索引；开启后执行一次。"""
    from unittest.mock import MagicMock, patch

    async def run(flag):
        from app.core import database as dbmod

        class FakeConn:
            async def execute(self, *a, **k):
                pass

            async def run_sync(self, fn, *a, **k):
                pass  # skip create_all

        class FakeCtx:
            async def __aenter__(self):
                return FakeConn()

            async def __aexit__(self, *a):
                return False

        class FakeScalars:
            def first(self):
                return MagicMock()  # non-None → skip seeding

        class FakeResult:
            def scalars(self):
                return FakeScalars()

        class FakeSession:
            async def execute(self, *a, **k):
                return FakeResult()

        class FakeSessionCtx:
            async def __aenter__(self):
                return FakeSession()

            async def __aexit__(self, *a):
                return False

        class FakeEngine:
            def begin(self):
                return FakeCtx()

        vec_mock = AsyncMock()
        with patch.object(dbmod, "engine", new=FakeEngine()), \
                patch.object(dbmod, "_apply_rag_queue_migration", new=AsyncMock()), \
                patch.object(dbmod, "_apply_hybrid_search_migration", new=AsyncMock()), \
                patch.object(dbmod, "_apply_workspace_memory_migration", new=AsyncMock()), \
                patch.object(dbmod, "_apply_vector_index_migration", new=vec_mock), \
                patch.object(dbmod, "AsyncSessionLocal", new=FakeSessionCtx), \
                patch.object(dbmod.settings, "AUTO_APPLY_VECTOR_INDEXES", flag):
            await dbmod.init_db()
        return vec_mock.await_count

    assert asyncio.run(run(False)) == 0
    assert asyncio.run(run(True)) == 1
