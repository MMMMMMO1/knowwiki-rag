"""评估集 —— 用标准问题量化知识库检索质量。

离线可跑：evaluate_retrieval 接受一个 retrieve_fn(question) -> sources 的回调，
不依赖真实数据库或外部 LLM。真实项目可替换 EVAL_DATASET 为从 Wiki 文档抽样
生成的条目（见 generate_from_documents）。
"""

from __future__ import annotations

from typing import Any, Callable

# 示例评估集：question + 期望命中的文件/关键词/必含事实。
# expected_files 与 sources 的 title / full_path 匹配；
# expected_keywords 必须全部出现在召回文本里；
# must_include 用于「回答是否包含关键事实」维度（需外部 LLM 时可选启用）。
EVAL_DATASET: list[dict[str, Any]] = [
    {
        "question": "什么是 RAG？",
        "expected_files": ["rag.md"],
        "expected_keywords": ["检索", "增强"],
        "must_include": ["检索增强生成"],
    },
    {
        "question": "向量数据库的作用是什么？",
        "expected_files": ["vector-db.md"],
        "expected_keywords": ["向量", "相似度"],
        "must_include": ["近邻搜索"],
    },
    {
        "question": "如何评估检索质量？",
        "expected_files": ["evaluation.md"],
        "expected_keywords": ["召回", "命中率"],
        "must_include": ["评估"],
    },
    {
        "question": "什么是 embedding？",
        "expected_files": ["embedding.md"],
        "expected_keywords": ["向量", "语义"],
        "must_include": ["嵌入"],
    },
    {
        "question": "混合检索是什么？",
        "expected_files": ["hybrid-search.md"],
        "expected_keywords": ["向量", "关键词"],
        "must_include": ["混合"],
    },
    {
        "question": "什么是 rerank？",
        "expected_files": ["rerank.md"],
        "expected_keywords": ["重排序", "精排"],
        "must_include": ["重排"],
    },
    {
        "question": "如何对文档分块？",
        "expected_files": ["chunking.md"],
        "expected_keywords": ["分块", "chunk"],
        "must_include": ["切分"],
    },
    {
        "question": "什么是多租户？",
        "expected_files": ["multi-tenancy.md"],
        "expected_keywords": ["隔离", "命名空间"],
        "must_include": ["租户"],
    },
    {
        "question": "长期记忆如何存储？",
        "expected_files": ["memory.md"],
        "expected_keywords": ["记忆", "向量"],
        "must_include": ["长期记忆"],
    },
    {
        "question": "什么是查询改写？",
        "expected_files": ["query-rewrite.md"],
        "expected_keywords": ["改写", "检索"],
        "must_include": ["改写"],
    },
]

RetrieveFn = Callable[[str], list[dict[str, Any]]]


def evaluate_retrieval(retrieve_fn: RetrieveFn) -> dict[str, Any]:
    """逐条调用 retrieve_fn 并统计召回命中情况。

    返回 {total, hits, hit_rate, failures}，失败样例附带 detail 与 sources。
    """
    hits = 0
    failures: list[dict[str, Any]] = []
    for item in EVAL_DATASET:
        try:
            sources = retrieve_fn(item["question"])
        except Exception as exc:
            failures.append({**item, "error": str(exc)})
            continue
        score = _score_item(item, sources)
        if score["passed"]:
            hits += 1
        else:
            failures.append({**item, "detail": score, "sources": sources})

    total = len(EVAL_DATASET)
    return {
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "failures": failures,
    }


def _score_item(
    item: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """根据 sources 判断是否命中目标文件与关键词。"""
    titles = {s.get("title", "") for s in sources}
    paths = {s.get("full_path", "") for s in sources}
    text = " ".join(s.get("text", "") for s in sources)

    expected_files = set(item.get("expected_files", []))
    file_hit = bool(expected_files) and bool(
        expected_files & titles or expected_files & paths
    )

    expected_keywords = item.get("expected_keywords", [])
    keyword_hit = all(keyword in text for keyword in expected_keywords)

    return {
        "file_hit": file_hit,
        "keyword_hit": keyword_hit,
        "passed": file_hit and keyword_hit,
        "sources_count": len(sources),
    }


def generate_from_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从文档列表抽样生成初始评估集（问题模板，供人工补充 must_include）。"""
    items: list[dict[str, Any]] = []
    for doc in documents:
        title = doc.get("title", "")
        content = doc.get("content", "")
        if not title or not content:
            continue
        items.append(
            {
                "question": f"{title} 主要讲了什么？",
                "expected_files": [title],
                "expected_keywords": [],
                "must_include": [],
            }
        )
    return items


if __name__ == "__main__":
    # 离线示例：用全命中 fake retriever 演示评估输出格式。
    def _fake_retriever(question: str) -> list[dict[str, Any]]:
        item = next(i for i in EVAL_DATASET if i["question"] == question)
        return [
            {
                "title": item["expected_files"][0],
                "full_path": item["expected_files"][0],
                "text": " ".join(item["expected_keywords"]),
                "score": 0.9,
                "chunk_index": 0,
            }
        ]

    result = evaluate_retrieval(_fake_retriever)
    print(f"total={result['total']} hits={result['hits']} hit_rate={result['hit_rate']}")
    for failure in result["failures"]:
        print("FAIL:", failure["question"], failure.get("detail"))
