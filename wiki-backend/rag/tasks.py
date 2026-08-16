"""
Celery 任务 —— RAG 入库任务。

process_rag_document: 接收 rag_document_id，调用 RagIndexingProcessor 执行流水线。
成功/失败都通过 RagDocument 状态表可观测；可重试错误触发 Celery 自动重试。
"""

import asyncio

from app.core.config import settings
from rag.celery_app import celery_app
from rag.exceptions import RetryableIndexingError
from rag.task_worker import RagIndexingProcessor


def _run_async(coro):
    """在独立事件循环中执行异步任务，并在循环关闭前 dispose 数据库连接池。

    Celery 每个任务调用一次 asyncio.run()，若连接池里的 asyncpg 连接跨事件循环
    泄漏，下一次任务会触发 "RuntimeError: Event loop is closed"。
    每次任务结束就 dispose，保证连接不跨循环。
    """

    async def _wrapped():
        try:
            return await coro
        finally:
            from app.core.database import engine
            await engine.dispose()

    return asyncio.run(_wrapped())


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
        status = _run_async(processor.process(rag_document_id))
        return {"rag_document_id": rag_document_id, "status": status}
    except RetryableIndexingError as exc:
        # 还有重试机会：交给 Celery 延迟后自动重试
        if self.request.retries < settings.RAG_TASK_MAX_RETRIES:
            raise self.retry(
                exc=exc,
                countdown=settings.RAG_TASK_RETRY_DELAY_SECONDS,
            )
        # 达到最大重试次数：改写为最终失败文案（去掉误导性的「将自动重试」）
        _run_async(processor.finalize_failed(rag_document_id, str(exc)))
        return {"rag_document_id": rag_document_id, "status": "failed"}
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


@celery_app.task(name="rag.tasks.extract_memories")
def extract_memories(
    user_id: int,
    workspace_id: str,
    session_id: str,
    user_message: str,
    assistant_message: str,
) -> dict:
    """异步提取长期记忆：LLM 审视一轮对话 → 向量化 → 写入 memories 表。

    后台任务，失败静默降级（不阻断聊天主流程）。
    """
    from rag.memory_service import MemoryService

    async def _run():
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            service = MemoryService(db)
            return await service.extract_and_save(
                user_id, workspace_id, session_id, user_message, assistant_message
            )

    try:
        saved = _run_async(_run())
        return {"saved": saved}
    except Exception:
        # Memory extraction must never break the chat flow.
        return {"saved": 0}


def enqueue_memory_extraction(
    user_id: int,
    workspace_id: str,
    session_id: str,
    user_message: str,
    assistant_message: str,
) -> bool:
    """投递记忆提取任务到 Celery 队列。返回是否投递成功。"""
    try:
        extract_memories.delay(
            user_id, workspace_id, session_id, user_message, assistant_message
        )
        return True
    except Exception:
        return False


def enqueue_rag_document_tasks(rag_document_ids: list[int]) -> tuple[int, int]:
    """批量投递多个 RAG 入库任务。

    返回 (成功投递数量, 投递失败数量)。
    """
    enqueued = 0
    failed = 0
    for rag_document_id in rag_document_ids:
        if enqueue_rag_document_task(rag_document_id):
            enqueued += 1
        else:
            failed += 1
    return enqueued, failed
