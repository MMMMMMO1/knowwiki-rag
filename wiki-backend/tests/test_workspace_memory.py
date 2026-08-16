"""工作区隔离 + 长期记忆测试 —— 命名空间过滤、记忆存取、向后兼容。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_vector_store_search_filters_by_workspace() -> None:
    """search 生成带 workspace_id 过滤的 SQL。"""
    from rag.vector_store import VectorStore

    captured = {}

    class FakeResult:
        def all(self):
            return []

    class FakeDB:
        async def execute(self, stmt, *args, **kwargs):
            captured["stmt"] = stmt
            return FakeResult()

    async def run():
        store = VectorStore(FakeDB())
        await store.search([0.0] * 1024, top_k=5, workspace_id="ws-a")

    asyncio.run(run())
    sql = str(captured["stmt"])
    compiled = captured["stmt"].compile()
    assert "workspace_id" in sql
    assert "ws-a" in compiled.params.values()


def test_memory_store_search_scopes_user_and_workspace() -> None:
    """MemoryStore.search 生成 user + workspace 过滤的 SQL。"""
    from rag.memory_store import MemoryStore

    captured = {}

    class FakeResult:
        def all(self):
            return []

    class FakeDB:
        async def execute(self, stmt, *args, **kwargs):
            captured["stmt"] = stmt
            return FakeResult()

    async def run():
        store = MemoryStore(FakeDB())
        await store.search([0.0] * 1024, user_id=7, workspace_id="ws-a", top_k=3)

    asyncio.run(run())
    sql = str(captured["stmt"])
    assert "user_id" in sql
    assert "workspace_id" in sql


def test_memory_service_parse_facts_handles_json_and_fences() -> None:
    """_parse_facts 稳健解析：纯 JSON、markdown 围栏、非 JSON 均正确处理。"""
    from rag.memory_service import MemoryService

    assert MemoryService._parse_facts('[{"content": "a", "importance": 0.8}]') == [
        {"content": "a", "importance": 0.8}
    ]
    assert MemoryService._parse_facts(
        '```json\n[{"content": "b", "importance": 0.5}]\n```'
    ) == [{"content": "b", "importance": 0.5}]
    assert MemoryService._parse_facts("no json here") == []


def test_memory_service_extract_and_save() -> None:
    """extract_and_save：LLM 提取 → 向量化 → 入库；显式「记住」强制 importance=1.0。"""
    from rag.memory_service import MemoryService

    class FakeLLM:
        async def chat(self, messages, temperature=0.7):
            return '[{"content": "user prefers English code comments", "importance": 0.6}]'

    class FakeEmbedder:
        async def embed(self, chunks):
            return [[0.0] * 1024 for _ in chunks]

    captured = {}

    class FakeMemoryStore:
        def __init__(self, db):
            pass

        async def insert(self, **kwargs):
            captured.update(kwargs)

    async def run():
        service = MemoryService(MagicMock(), embedder=FakeEmbedder(), llm=FakeLLM())
        with patch("rag.memory_service.MemoryStore", FakeMemoryStore):
            with patch("rag.memory_service.settings.MEMORY_EXPLICIT_KEYWORDS", ["记住"]):
                saved = await service.extract_and_save(
                    user_id=1,
                    workspace_id="default",
                    session_id="s1",
                    user_message="请记住：我喜欢英文注释",
                    assistant_message="好的",
                )
        assert saved == 1
        assert captured["content"] == "user prefers English code comments"
        assert captured["importance"] == 1.0  # 显式记住 → 强制 1.0

    asyncio.run(run())


def test_retriever_passes_workspace_to_search() -> None:
    """Retriever 把 workspace_id 透传给 vector_store.search。"""
    from rag.retriever import Retriever

    async def run():
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.0] * 1024])
        store = MagicMock()
        store.search = AsyncMock(return_value=[])

        retriever = Retriever(embedder, store, top_k=3, workspace_id="ws-x")
        with patch("rag.retriever.settings.HYBRID_SEARCH", False):
            with patch("rag.retriever.settings.RERANK_ENABLED", False):
                await retriever.retrieve("q")

        assert store.search.await_args.kwargs.get("workspace_id") == "ws-x"

    asyncio.run(run())


def test_chat_service_build_context_separates_doc_and_memory() -> None:
    """_build_context 分开标注文档块与记忆块。"""
    from rag.chat_service import ChatService

    class FakeRetriever:
        def format_context(self, results):
            return "[来源 1] doc-text"

    service = ChatService()
    context = service._build_context(
        FakeRetriever(), [MagicMock()], ["memory-1", "memory-2"]
    )
    assert "=== 知识库资料 ===" in context
    assert "[来源 1] doc-text" in context
    assert "=== 关于你的长期记忆 ===" in context
    assert "- memory-1" in context
    assert "- memory-2" in context

    # 无记忆时只有文档块
    context2 = service._build_context(FakeRetriever(), [MagicMock()], [])
    assert "=== 关于你的长期记忆 ===" not in context2
