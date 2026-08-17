"""评估集测试 —— 离线可跑，不连真实数据库或外部 LLM。"""

from rag.eval import EVAL_DATASET, _score_item, evaluate_retrieval, generate_from_documents


def test_evaluate_retrieval_full_hit() -> None:
    """全命中 fake retriever：命中率 1.0，无失败样例。"""
    def fake(question):
        item = next(i for i in EVAL_DATASET if i["question"] == question)
        return [{
            "title": item["expected_files"][0],
            "full_path": item["expected_files"][0],
            "text": " ".join(item["expected_keywords"]),
            "score": 0.9,
            "chunk_index": 0,
        }]

    result = evaluate_retrieval(fake)
    assert result["total"] == len(EVAL_DATASET)
    assert result["hits"] == result["total"]
    assert result["hit_rate"] == 1.0
    assert result["failures"] == []


def test_evaluate_retrieval_empty_sources_fails() -> None:
    """空召回：命中率 0.0，全部记为失败样例。"""
    result = evaluate_retrieval(lambda question: [])
    assert result["hits"] == 0
    assert result["hit_rate"] == 0.0
    assert len(result["failures"]) == len(EVAL_DATASET)


def test_score_item_matches_files_and_keywords() -> None:
    """_score_item 判断文件命中与关键词命中。"""
    item = {"expected_files": ["rag.md"], "expected_keywords": ["检索", "增强"]}
    good = [{"title": "rag.md", "full_path": "rag", "text": "检索增强生成", "score": 0.9}]
    score = _score_item(item, good)
    assert score["file_hit"] is True
    assert score["keyword_hit"] is True
    assert score["passed"] is True

    # 关键词缺失 → 不通过
    bad = [{"title": "rag.md", "full_path": "rag", "text": "别的内容", "score": 0.9}]
    assert _score_item(item, bad)["passed"] is False


def test_generate_from_documents() -> None:
    """从文档抽样生成初始评估集，跳过空标题/空内容。"""
    docs = [
        {"title": "a.md", "content": "hello"},
        {"title": "", "content": ""},
    ]
    items = generate_from_documents(docs)
    assert len(items) == 1
    assert items[0]["expected_files"] == ["a.md"]
    assert "a.md" in items[0]["question"]
