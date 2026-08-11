"""
文档加载模块 —— 替代 AnythingLLM 的 collector/utils/files。

索引链路唯一的文档解析入口。基于 Microsoft MarkItDown，
支持 PDF、DOCX、PPTX、XLSX、HTML、图片、音频、EPUB、CSV 等格式，
统一产出 Markdown 文本。
"""

import io
from pathlib import Path
from typing import Any

from markitdown import MarkItDown, StreamInfo

from rag.schemas import Document


class DocumentLoader:
    """文档加载器 —— 索引链路唯一的解析入口。

    基于 Microsoft MarkItDown，支持数十种文件格式，输出统一 Markdown。

    两种加载方式：
    - load(file_path): 从本地文件路径加载
    - load_bytes(file_name, content, metadata): 从字节流加载（S3 等）
    """

    def __init__(self):
        self._md = MarkItDown()

    # ── 公开接口 ──────────────────────────────────────────

    def load(self, file_path: str) -> Document:
        """从本地文件路径加载。"""
        path = Path(file_path)
        return self._convert(path.name, path.read_bytes(), {"source": str(path)})

    def load_bytes(
        self,
        file_name: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """从字节流加载（S3、HTTP 等）。

        Args:
            file_name: 文件名，如 "report.pdf"。
            content: 文件原始字节。
            metadata: 附加元信息（如 file_id、storage_key）。
        """
        return self._convert(file_name, content, metadata or {})

    # ── 内部：统一 MarkItDown 转换 ─────────────────────────

    def _convert(
        self, file_name: str, content: bytes, metadata: dict[str, Any]
    ) -> Document:
        """通过 MarkItDown 将任意格式文件转为 Markdown 文本。"""
        suffix = Path(file_name).suffix.lower()
        stream = io.BytesIO(content)

        result = self._md.convert_stream(
            stream,
            stream_info=StreamInfo(extension=suffix, filename=file_name),
        )

        return Document.create(
            title=file_name,
            content=result.text_content,
            metadata={**metadata, "file_type": suffix.lstrip(".")},
        )

