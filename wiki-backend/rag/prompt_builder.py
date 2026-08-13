"""
Prompt 组装模块 —— 将检索结果和用户问题组装为 LLM 对话格式。

将 system prompt、检索上下文、用户问题、对话历史组装为
LLM 可直接消费的 OpenAI 兼容 messages 列表。
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings


class PromptBuilder:
    """RAG Prompt 组装器。

    用法:
        builder = PromptBuilder()
        messages = builder.build(
            question="光合作用的原理是什么？",
            context=retriever.format_context(results),
        )
        # 直接喂给 LLM:
        # response = await openai.chat.completions.create(
        #     model="deepseek-v4-flash", messages=messages)
    """

    def __init__(self, system_prompt: str | None = None):
        self.system_prompt = system_prompt or settings.SYSTEM_PROMPT

    def build(
        self,
        question: str,
        context: str = "",
        chat_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """组装完整的 messages 列表。

        Args:
            question: 用户当前问题。
            context: 检索到的相关资料文本（来自 retriever.format_context()）。
            chat_history: 可选的历史对话，格式 [{"role":"user","content":"..."}, ...]。

        Returns:
            OpenAI 兼容的 messages 列表。
        """
        messages: list[dict[str, Any]] = []

        # 1. System message：角色定义 + 行为边界
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # 2. 对话历史
        if chat_history:
            messages.extend(chat_history)

        # 3. User message：上下文 + 问题
        user_content = self._build_user_content(question, context)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, question: str, context: str) -> str:
        """组装 user message 内容。"""
        if not context:
            return question

        return (
            f"请根据以下参考资料回答用户问题。\n"
            f"如果参考资料中没有相关信息，请如实告知用户。\n\n"
            f"=== 参考资料 ===\n"
            f"{context}\n"
            f"=== 参考资料结束 ===\n\n"
            f"用户问题：{question}"
        )
