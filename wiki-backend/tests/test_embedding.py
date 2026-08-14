"""Embedder 错误分类测试 —— 验证可重试/不可重试错误的划分。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from rag.embedding import Embedder
from rag.exceptions import RetryableIndexingError
from rag.schemas import Chunk


def _make_chunks(n: int = 1) -> list[Chunk]:
    return [Chunk.create(doc_id="doc", text=f"hello {i}") for i in range(n)]


class _FakeResponse:
    def __init__(self, status_code: int, dim: int = 1024):
        self.status_code = status_code
        self._dim = dim

    def json(self):
        return {"data": [{"index": 0, "embedding": [0.0] * self._dim}]}


class _FakeClient:
    """伪造的 httpx.AsyncClient，避免真实建连（沙箱代理导致 ImportError）。"""

    def __init__(self, response_or_exc):
        self._response_or_exc = response_or_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc


def _run_embed(response_or_exc):
    """用伪造的 httpx.AsyncClient 跑一次 embed，返回结果或抛出异常。"""

    async def _run():
        embedder = Embedder(model="text-embedding-v3")
        with patch("httpx.AsyncClient", return_value=_FakeClient(response_or_exc)):
            with patch("rag.embedding.settings.VECTOR_DIM", 1024):
                return await embedder.embed(_make_chunks())

    return asyncio.run(_run())


def test_embedding_429_is_retryable() -> None:
    try:
        _run_embed(_FakeResponse(429))
        assert False, "应抛 RetryableIndexingError"
    except RetryableIndexingError as e:
        assert "429" in str(e)


def test_embedding_5xx_is_retryable() -> None:
    try:
        _run_embed(_FakeResponse(500))
        assert False, "应抛 RetryableIndexingError"
    except RetryableIndexingError as e:
        assert "500" in str(e)


def test_embedding_timeout_is_retryable() -> None:
    try:
        _run_embed(httpx.TimeoutException("timeout"))
        assert False, "应抛 RetryableIndexingError"
    except RetryableIndexingError as e:
        assert "超时" in str(e)


def test_embedding_transport_error_is_retryable() -> None:
    try:
        _run_embed(httpx.TransportError("connection refused"))
        assert False, "应抛 RetryableIndexingError"
    except RetryableIndexingError as e:
        assert "连接失败" in str(e)


def test_embedding_401_is_final() -> None:
    """401 认证失败属于最终失败（不可重试），抛普通 RuntimeError。"""
    try:
        _run_embed(_FakeResponse(401))
        assert False, "应抛 RuntimeError"
    except RuntimeError as e:
        assert "401" in str(e)
    except RetryableIndexingError:
        assert False, "401 不应是可重试错误"


def test_embedding_dimension_mismatch_is_final() -> None:
    """维度不匹配属于最终失败。"""
    try:
        _run_embed(_FakeResponse(200, dim=1025))
        assert False, "应抛 ValueError"
    except ValueError as e:
        assert "维度不匹配" in str(e)
