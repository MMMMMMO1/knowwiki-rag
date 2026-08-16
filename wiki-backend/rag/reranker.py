"""
Rerank module — re-rank coarse recall candidates (cross-encoder style scoring).

Second stage of two-stage retrieval:
1. Coarse recall (vector + keyword in retriever): bi-encoder style, fast but rough;
2. Re-rank (this module): cross-encoder style, slow but precise, keep top-k.

Why not re-rank the whole corpus: a cross-encoder must score query+doc on the fly,
so latency/cost explode linearly at corpus scale; we must first shrink candidates
to a few dozen via cheap coarse recall.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.core.config import settings
from rag.schemas import RetrievalResult


class Reranker(ABC):
    """Abstract rerank interface.

    Every implementation must provide rerank(query, candidates):
    given a query and candidate set, return candidates re-ranked by relevance.
    """

    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """Re-rank and return the candidate list."""


class OpenAIReranker(Reranker):
    """OpenAI-compatible /rerank endpoint implementation (e.g. bge-reranker).

    Submits candidate texts as documents in one request; the server returns a
    relevance_score per document. Re-sorts by score descending and rewrites score.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_url = (api_url or settings.RERANK_API_URL).rstrip("/")
        # rerank usually shares a vendor with embedding; reuse embedding key when empty
        self.api_key = api_key or settings.RERANK_API_KEY or settings.EMBEDDING_API_KEY
        self.model = model or settings.RERANK_MODEL

        if not self.api_url:
            raise ValueError(
                "RERANK_API_URL 未配置：开启 RERANK_ENABLED 前请先在 .env 里配置 "
                "OpenAI 兼容的 /rerank 接口地址。"
            )

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def rerank(
        self, query: str, candidates: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """Call /rerank and return candidates sorted by relevance_score desc."""
        if not candidates:
            return []

        documents = [candidate.text for candidate in candidates]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/rerank",
                headers=self._headers,
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        # OpenAI-compatible response: {"results": [{"index": 0, "relevance_score": 0.9}, ...]}
        results = sorted(
            data["results"],
            key=lambda item: item.get("relevance_score", 0.0),
            reverse=True,
        )

        ranked: list[RetrievalResult] = []
        for item in results:
            candidate = candidates[int(item["index"])]
            candidate.score = round(float(item["relevance_score"]), 6)
            ranked.append(candidate)

        return ranked
