"""
Embedding 模块 —— 替代 AnythingLLM 的 EmbeddingEngines。

将 Chunk 的文本转换为向量，调用 OpenAI 兼容的 /v1/embeddings API。
"""

import httpx

from app.core.config import settings
from rag.schemas import Chunk


class Embedder:
    """OpenAI 兼容的 embedding 客户端。

    调用 EMBEDDING_API_URL + /embeddings 端点，将文本列表转换为向量列表。
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_url = (api_url or settings.EMBEDDING_API_URL).rstrip("/")
        self.api_key = api_key or settings.EMBEDDING_API_KEY
        self.model = model or settings.EMBEDDING_MODEL

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def embed(self, chunks: list[Chunk]) -> list[list[float]]:
        """将 Chunk 列表转换为向量列表，顺序与输入一一对应。

        Args:
            chunks: 待向量化的 Chunk 列表。

        Returns:
            与 chunks 等长的向量列表，每个向量是 float 列表。
        """
        if not chunks:
            return []

        texts = [chunk.text for chunk in chunks]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/embeddings",
                headers=self._headers,
                json={
                    "model": self.model,
                    "input": texts,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()

        # OpenAI 兼容格式: {"data": [{"embedding": [...], "index": 0}, ...]}
        embeddings = sorted(result["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in embeddings]
