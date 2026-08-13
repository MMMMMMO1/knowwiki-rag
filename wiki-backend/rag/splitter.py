"""
文本切分模块 —— 递归按分隔符降级切分长文本为固定大小的块。

将 Document 切分为 Chunk 列表，每个 Chunk 不超过 chunk_size 字符，
相邻 Chunk 之间有 chunk_overlap 字符的重叠。
"""

from app.core.config import settings
from rag.schemas import Chunk, Document


# 分隔符优先级：段落 > 行 > 中文句号 > 空格 > 字符
_SEPARATORS = ["\n\n", "\n", "。", " ", ""]


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """将纯文本递归切分为不超过 chunk_size 的字符串列表。"""
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) 必须小于 chunk_size ({chunk_size})"
        )

    # 找第一个能把文本分开的分隔符
    separator = _SEPARATORS[-1]  # 兜底：逐字符切
    for sep in _SEPARATORS:
        if sep == "":
            break
        if sep in text:
            separator = sep
            break

    # 用选中的分隔符拆分
    splits = text.split(separator) if separator else list(text)

    chunks: list[str] = []
    current = ""

    for split in splits:
        piece = split if not separator else split
        # 如果单段已超过 chunk_size，先硬切该段
        if len(piece) > chunk_size:
            # 先把 current 存起来
            if current:
                chunks.append(current)
            # 硬切超长段
            for i in range(0, len(piece), chunk_size - chunk_overlap):
                sub = piece[i:i + chunk_size]
                chunks.append(sub)
            current = ""
            continue

        if current and len(current) + len(separator) + len(piece) > chunk_size:
            # 当前块已满，保存并开始新块
            chunks.append(current)
            # 如果有 overlap，用当前块末尾作为新块的开头
            if chunk_overlap > 0:
                overlap_text = current[-chunk_overlap:]
                current = overlap_text + separator + piece if separator else overlap_text + piece
            else:
                current = piece
        else:
            if current:
                current += separator + piece
            else:
                current = piece

    if current:
        chunks.append(current)

    return chunks


class TextSplitter:
    """将 Document 切分为 Chunk 列表。"""

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP

    def split(self, document: Document) -> list[Chunk]:
        """将一个 Document 切分为多个 Chunk。"""
        texts = split_text(document.content, self.chunk_size, self.chunk_overlap)
        return [
            Chunk.create(
                doc_id=document.doc_id,
                text=text,
                metadata={**document.metadata},
            )
            for text in texts
        ]
