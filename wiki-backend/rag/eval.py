"""评估集 —— 用标准问题量化知识库检索质量。

离线可跑：evaluate_retrieval 接受一个 retrieve_fn(question) -> sources 的回调，
不依赖真实数据库或外部 LLM。真实项目可替换 EVAL_DATASET 为从 Wiki 文档抽样
生成的条目（见 generate_from_documents）。
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
from pathlib import Path
from typing import Any, Awaitable, Callable

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
AsyncRetrieveFn = Callable[[str], Awaitable[list[Any]]]
AnswerFn = Callable[[str, list[dict[str, Any]]], str]
AsyncAnswerFn = Callable[[str, list[dict[str, Any]]], Awaitable[str]]


def evaluate_retrieval(
    retrieve_fn: RetrieveFn,
    dataset: list[dict[str, Any]] | None = None,
    answer_fn: AnswerFn | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """逐条调用 retrieve_fn 并统计召回命中情况。

    返回 {total, hits, hit_rate, failures}，失败样例附带 detail 与 sources。
    """
    dataset = dataset or EVAL_DATASET
    scores: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in dataset:
        try:
            raw_sources = retrieve_fn(item["question"])
            if inspect.isawaitable(raw_sources):
                raise TypeError("异步 retrieve_fn 请使用 evaluate_retrieval_async()")
            sources = _normalize_sources(raw_sources)
            answer = answer_fn(item["question"], sources) if answer_fn else None
        except Exception as exc:
            failures.append({**item, "error": str(exc)})
            continue
        score = _score_item(item, sources, answer=answer, top_k=top_k)
        scores.append(score)
        if not score["passed"]:
            failures.append({**item, "detail": score, "sources": sources})

    return _summarize(dataset, scores, failures, top_k)


async def evaluate_retrieval_async(
    retrieve_fn: AsyncRetrieveFn,
    dataset: list[dict[str, Any]] | None = None,
    answer_fn: AsyncAnswerFn | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """异步评估真实 Retriever/数据库链路。"""
    dataset = dataset or EVAL_DATASET
    scores: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in dataset:
        try:
            sources = _normalize_sources(await retrieve_fn(item["question"]))
            answer = await answer_fn(item["question"], sources) if answer_fn else None
        except Exception as exc:
            failures.append({**item, "error": str(exc)})
            continue
        score = _score_item(item, sources, answer=answer, top_k=top_k)
        scores.append(score)
        if not score["passed"]:
            failures.append({**item, "detail": score, "sources": sources})
    return _summarize(dataset, scores, failures, top_k)


async def evaluate_retriever(
    retriever: Any,
    dataset: list[dict[str, Any]] | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """真实 Retriever 适配器。"""
    return await evaluate_retrieval_async(
        retriever.retrieve,
        dataset=dataset,
        top_k=top_k,
    )


def _normalize_sources(sources: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for source in sources:
        if isinstance(source, dict):
            normalized.append(source)
            continue
        metadata = getattr(source, "metadata", {}) or {}
        normalized.append(
            {
                "chunk_id": getattr(source, "chunk_id", ""),
                "text": getattr(source, "text", ""),
                "score": getattr(source, "score", 0.0),
                "title": metadata.get("title", ""),
                "full_path": metadata.get("full_path", ""),
                "chunk_index": metadata.get("chunk_index"),
            }
        )
    return normalized


def _score_item(
    item: dict[str, Any],
    sources: list[dict[str, Any]],
    answer: str | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """计算单条 Recall@K、MRR、NDCG、关键词和答案事实命中。"""
    top_k = top_k or len(sources) or 1
    expected_files = set(item.get("expected_files", []))
    relevant_ranks = [
        rank
        for rank, source in enumerate(sources, 1)
        if source.get("title", "") in expected_files
        or source.get("full_path", "") in expected_files
    ]
    first_rank = min(relevant_ranks) if relevant_ranks else None
    text = " ".join(s.get("text", "") for s in sources)
    file_hit = first_rank is not None

    expected_keywords = item.get("expected_keywords", [])
    keyword_hit = all(keyword in text for keyword in expected_keywords)

    must_include = item.get("must_include", [])
    answer_fact_hit = None
    if answer is not None and must_include:
        answer_fact_hit = all(fact in answer for fact in must_include)

    reciprocal_rank = 1.0 / first_rank if first_rank is not None else 0.0
    ndcg = 1.0 / math.log2(first_rank + 1) if first_rank is not None else 0.0
    passed = file_hit and keyword_hit and answer_fact_hit is not False

    return {
        "file_hit": file_hit,
        "keyword_hit": keyword_hit,
        "answer_fact_hit": answer_fact_hit,
        "recall_at_k": 1.0 if first_rank is not None and first_rank <= top_k else 0.0,
        "reciprocal_rank": reciprocal_rank,
        "ndcg": ndcg,
        "first_relevant_rank": first_rank,
        "passed": passed,
        "sources_count": len(sources),
    }


def _summarize(
    dataset: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    top_k: int | None,
) -> dict[str, Any]:
    total = len(dataset)
    hits = sum(1 for score in scores if score["passed"])
    answer_scores = [score for score in scores if score["answer_fact_hit"] is not None]
    denominator = total or 1
    return {
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / denominator, 4) if total else 0.0,
        "recall_at_k": round(sum(s["recall_at_k"] for s in scores) / denominator, 4) if total else 0.0,
        "mrr": round(sum(s["reciprocal_rank"] for s in scores) / denominator, 4) if total else 0.0,
        "ndcg": round(sum(s["ndcg"] for s in scores) / denominator, 4) if total else 0.0,
        "keyword_hit_rate": round(sum(bool(s["keyword_hit"]) for s in scores) / denominator, 4) if total else 0.0,
        "answer_fact_rate": (
            round(sum(bool(s["answer_fact_hit"]) for s in answer_scores) / len(answer_scores), 4)
            if answer_scores else None
        ),
        "top_k": top_k,
        "failures": failures,
    }


def load_dataset(path: str | Path) -> list[dict[str, Any]]:
    """从 JSON 文件加载可版本化的真实评估集。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("评估集必须是 JSON 对象数组")
    return data


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


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from rag.embedding import Embedder
    from rag.retriever import Retriever
    from rag.vector_store import VectorStore

    dataset = load_dataset(args.dataset)
    async with AsyncSessionLocal() as db:
        retriever = Retriever(
            Embedder(),
            VectorStore(db),
            top_k=args.top_k,
            workspace_id=args.workspace,
        )
        return await evaluate_retriever(retriever, dataset=dataset, top_k=args.top_k)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行真实 RAG 检索评估")
    parser.add_argument("--dataset", required=True, help="JSON 评估集路径")
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", help="可选 JSON 报告输出路径")
    cli_args = parser.parse_args()
    result = asyncio.run(_run_cli(cli_args))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if cli_args.output:
        Path(cli_args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
