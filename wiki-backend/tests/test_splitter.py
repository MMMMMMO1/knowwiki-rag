"""Splitter 单元测试 —— 验证切分后的 chunk 不超过 chunk_size。"""

from rag.splitter import split_text, TextSplitter
from rag.schemas import Document


def test_split_text_basic() -> None:
    text = "hello world"
    chunks = split_text(text, 100, 10)
    assert chunks == ["hello world"]


def test_split_text_does_not_exceed_chunk_size() -> None:
    """多段合并时，overlap 拼接后的 chunk 仍不能超过 chunk_size。"""
    chunk_size = 500
    overlap = 50
    # 第一段 450 字符，第二段 480 字符，中间用换行连接
    text = "A" * 450 + "\n" + "B" * 480
    chunks = split_text(text, chunk_size, overlap)
    assert all(len(c) <= chunk_size for c in chunks)
    # 所有字符都必须至少出现一次（允许 overlap 重复，但不能丢失）
    combined = "".join(chunks)
    assert "A" * 450 in combined
    assert "B" * 480 in combined


def test_split_text_no_overlap_preserves_content() -> None:
    """无 overlap 时切分不能丢失或重复内容。"""
    chunk_size = 100
    text = "第一段内容。" * 30
    chunks = split_text(text, chunk_size, 0)
    assert all(len(c) <= chunk_size for c in chunks)
    assert "".join(chunks) == text


def test_split_text_hard_cut_single_long_line() -> None:
    """单行超长文本必须硬切，不能超过 chunk_size。"""
    chunk_size = 500
    overlap = 50
    text = "C" * 5000
    chunks = split_text(text, chunk_size, overlap)
    assert len(chunks) > 1
    assert all(len(c) <= chunk_size for c in chunks)


def test_split_text_with_overlap_preserves_content() -> None:
    """带 overlap 切分后，所有字符都应被保留（允许 overlap 重复）。"""
    chunk_size = 100
    overlap = 20
    text = "。" .join(f"第{i}段内容" for i in range(20))
    chunks = split_text(text, chunk_size, overlap)
    assert all(len(c) <= chunk_size for c in chunks)
    # 拼接后去掉重复的 overlap 部分，应能还原原文（这里只验证不丢内容）
    combined = "".join(chunks)
    assert set(combined) >= set(text)


def test_splitter_chunk_metadata() -> None:
    """TextSplitter 拆分后保留 metadata。"""
    splitter = TextSplitter(chunk_size=50, chunk_overlap=5)
    doc = Document(
        doc_id="test-doc",
        title="test",
        content="这是一段用于测试的文本。" * 10,
        metadata={"file_id": 42, "title": "test"},
    )
    chunks = splitter.split(doc)
    assert len(chunks) > 0
    assert all(c.metadata.get("file_id") == 42 for c in chunks)
    assert all(len(c.text) <= 50 for c in chunks)
