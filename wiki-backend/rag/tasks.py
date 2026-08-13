"""
Celery 任务 —— RAG 入库任务。

process_rag_document: 接收 rag_document_id，调用 RagIndexingProcessor 执行流水线。
成功/失败都通过 RagDocument 状态表可观测；可重试错误触发 Celery 自动重试。
"""

import asyncio

from app.core.config import settings
from rag.celery_app import celery_app
from rag.task_worker import RagIndexingProcessor, RetryableIndexingError


@celery_app.task(
    bind=True,
    name="rag.tasks.process_rag_document",
    max_retries=settings.RAG_TASK_MAX_RETRIES,
)
def process_rag_document(self, rag_document_id: int) -> dict:
    """处理单个 RAG 入库任务。

    任务内部自己创建 AsyncSessionLocal()，不复用 FastAPI request db session。
    Celery task 是同步函数，内部用 asyncio.run() 调用异步处理逻辑。
    """
    processor = RagIndexingProcessor()

    try:
        asyncio.run(processor.process(rag_document_id))
        return {"rag_document_id": rag_document_id, "status": "completed"}
    except RetryableIndexingError as exc:
        # 可重试错误：延迟后重试
        raise self.retry(
            exc=exc,
            countdown=settings.RAG_TASK_RETRY_DELAY_SECONDS,
        )
    except Exception:
        # 不可重试错误：状态已由 processor 标记为 failed，这里不再重试
        return {"rag_document_id": rag_document_id, "status": "failed"}


def enqueue_rag_document_task(rag_document_id: int) -> bool:
    """把 RAG 入库任务投递到 Celery 队列。

    返回 True 表示投递成功，False 表示投递失败（Redis 不可用等）。
    投递失败时由调用方负责把 RagDocument 标记为 failed。
    """
    try:
        process_rag_document.delay(rag_document_id)
        return True
    except Exception:
        return False
