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
    """将纯文本递归切分为不超过 chunk_size 的字符串列表。

    保证：
    - 所有返回的字符串长度都 <= chunk_size。
    - 分隔符不会被丢失（分隔符附加在片段末尾，最后一个片段除外）。
    - chunk_overlap > 0 时，相邻 chunk 有重叠字符用于保持上下文。
    """
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) 必须小于 chunk_size ({chunk_size})"
        )

    # 找第一个能把文本分开的分隔符
    separator = None
    for sep in _SEPARATORS:
        if sep == "":
            break
        if sep in text:
            separator = sep
            break

    if separator is None:
        # 无可用分隔符：逐字符硬切
        return _hard_cut(text, chunk_size, chunk_overlap)

    # 按分隔符拆分，分隔符附加在片段末尾（最后一个片段除外，避免多出尾部分隔符）
    parts = text.split(separator)
    pieces = [p + separator for p in parts[:-1]]
    if parts[-1]:
        pieces.append(parts[-1])

    chunks: list[str] = []
    current = ""

    for piece in pieces:
        # 超长单段：先保存 current，再硬切该段
        if len(piece) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_cut(piece, chunk_size, chunk_overlap))
            continue

        candidate = current + piece

        if len(candidate) <= chunk_size:
            current = candidate
            continue

        # candidate 超长：保存 current，新块以 overlap 前缀开头
        chunks.append(current)
        if chunk_overlap > 0 and current:
            prefix = current[-chunk_overlap:]
            new_candidate = prefix + piece
            if len(new_candidate) <= chunk_size:
                current = new_candidate
            else:
                # overlap 前缀 + piece 仍超长：先放能放下的，其余硬切
                available = chunk_size - len(prefix)
                if available > 0:
                    chunks.append(prefix + piece[:available])
                    chunks.extend(_hard_cut(piece[available:], chunk_size, chunk_overlap))
                else:
                    chunks.extend(_hard_cut(piece, chunk_size, chunk_overlap))
                current = ""
        else:
            current = piece

    if current:
        chunks.append(current)

    return chunks


def _hard_cut(s: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """把字符串硬切为 <= chunk_size 的片段（带 overlap 链）。"""
    result: list[str] = []
    step = chunk_size - chunk_overlap if chunk_overlap > 0 else chunk_size
    step = max(step, 1)
    for i in range(0, len(s), step):
        result.append(s[i : i + chunk_size])
    return result


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
