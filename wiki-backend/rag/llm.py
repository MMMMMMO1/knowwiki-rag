"""
LLM 调用模块 —— 替代 AnythingLLM 的 AiProviders。

调用 OpenAI 兼容的 /chat/completions API，支持流式和非流式。
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from app.core.config import settings


class LLM:
    """OpenAI 兼容的 LLM 客户端。

    用法:
        llm = LLM()
        # 非流式
        answer = await llm.chat(messages)
        # 流式
        async for token in llm.chat_stream(messages):
            print(token, end="")
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_url = (api_url or settings.LLM_API_URL).rstrip("/")
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ── 非流式 ────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
    ) -> str:
        """发送 messages 并返回完整回答。

        Args:
            messages: PromptBuilder.build() 产出的 messages 列表。
            temperature: 生成温度。

        Returns:
            LLM 的完整回答文本。
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/chat/completions",
                headers=self._headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"]

    # ── 流式 ──────────────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """流式发送 messages，逐 token yield。

        Args:
            messages: PromptBuilder.build() 产出的 messages 列表。
            temperature: 生成温度。

        Yields:
            每个生成的文本片段（token 或 token 组）。
        """
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.api_url}/chat/completions",
                headers=self._headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
                timeout=120.0,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # 去掉 "data: " 前缀
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
