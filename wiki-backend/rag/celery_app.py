"""
Celery 应用 —— RAG 入库任务的调度入口。

职责：
- 创建 Celery app，配置 Redis broker / result backend。
- 声明任务路由（rag-indexing 队列）。
- 只负责调度，不负责业务逻辑（业务在 tasks.py / task_worker.py）。
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "wiki_rag",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    # 任务路由：所有 rag 任务进 rag-indexing 队列
    task_routes={
        "rag.tasks.process_rag_document": {"queue": "rag-indexing"},
        "rag.tasks.extract_memories": {"queue": "rag-indexing"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    # 防止任务无限挂起：单个任务最长 15 分钟
    task_time_limit=900,
    task_soft_time_limit=840,
    # 失败任务不立即丢弃，配合 task 内的 max_retries 重试
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # broker 快速失败：Redis 不可用时，投递在几秒内报错而不是长时间挂起
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "socket_keepalive": True,
    },
    result_backend_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
    },
)

# 让 celery 能找到任务（worker 启动时通过 -A rag.celery_app:celery_app 自动导入）
celery_app.autodiscover_tasks(["rag"])
