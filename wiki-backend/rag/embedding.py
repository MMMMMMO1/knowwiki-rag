"""
Embedding 模块 —— 调用 OpenAI 兼容 API 将文本转为向量。

将 Chunk 的文本转换为向量，调用 OpenAI 兼容的 /v1/embeddings API。
支持分批请求和单条文本长度截断。支持阿里百炼 text-embedding-v3（1024 维）。
"""

import httpx

from app.core.config import settings
from rag.schemas import Chunk


class Embedder:
    """OpenAI 兼容的 embedding 客户端。

    支持分批请求（EMBEDDING_BATCH_SIZE）和单条文本长度限制（EMBEDDING_MAX_CHARS）。
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        max_chars: int | None = None,
    ):
        self.api_url = (api_url or settings.EMBEDDING_API_URL).rstrip("/")
        self.api_key = api_key or settings.EMBEDDING_API_KEY
        self.model = model or settings.EMBEDDING_MODEL
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self.max_chars = max_chars or settings.EMBEDDING_MAX_CHARS

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _truncate(self, text: str) -> str:
        """截断超过 max_chars 的文本。"""
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars]

    async def embed(self, chunks: list[Chunk]) -> list[list[float]]:
        """将 Chunk 列表转换为向量列表，顺序与输入一一对应。

        按 batch_size 分批请求，对超过 max_chars 的文本截断。
        """
        if not chunks:
            return []

        # 截断长文本
        texts = [self._truncate(chunk.text) for chunk in chunks]
        all_embeddings: list[list[float]] = []

        async with httpx.AsyncClient() as client:
            for batch_idx in range(0, len(texts), self.batch_size):
                batch = texts[batch_idx : batch_idx + self.batch_size]
                batch_num = batch_idx // self.batch_size + 1

                try:
                    response = await client.post(
                        f"{self.api_url}/embeddings",
                        headers=self._headers,
                        json={
                            "model": self.model,
                            "input": batch,
                        },
                        timeout=120.0,
                    )
                    response.raise_for_status()
                    result = response.json()

                    batch_embeddings = sorted(
                        result["data"], key=lambda x: x["index"]
                    )
                    all_embeddings.extend(
                        [item["embedding"] for item in batch_embeddings]
                    )

                except Exception as e:
                    raise RuntimeError(
                        f"Embedding 失败: model={self.model}, "
                        f"batch={batch_num}, batch_size={len(batch)}, "
                        f"error={e}"
                    )

        return all_embeddings
