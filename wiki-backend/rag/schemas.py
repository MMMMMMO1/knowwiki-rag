"""
RAG 统一数据结构。

Document 代表从原始文件加载后的完整文本；
Chunk 代表从 Document 切分出的片段，后续用于 embedding 和检索。
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class Document:
    """一份已加载的原始文档。"""

    doc_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> "Document":
        return cls(
            doc_id=str(uuid4()),
            title=title,
            content=content,
            metadata=metadata or {},
        )


@dataclass
class Chunk:
    """Document 切分后的一个文本片段。"""

    chunk_id: str
    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> "Chunk":
        return cls(
            chunk_id=str(uuid4()),
            doc_id=doc_id,
            text=text,
            metadata=metadata or {},
        )


@dataclass
class RetrievalResult:
    """单条检索结果（粗召回与精排后统一使用）。"""

    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
