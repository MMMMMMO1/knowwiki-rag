"""RAG 消息队列投递测试 —— 用 mock 测试 Celery 投递，不依赖真实 Redis/celery。

若 celery 未安装，注入一个最小可用的假 celery 模块，让 rag.tasks 可导入，
再通过 mock 掉 .delay() 验证投递逻辑，全程不触碰真实 Redis。
"""

import sys
import types
from unittest.mock import MagicMock, patch

# 若 celery 未安装，注入最小可用的假 celery 模块。
try:
    import celery  # noqa: F401
except ImportError:
    class _FakeConf:
        def update(self, **kwargs):
            pass

    class _FakeCelery:
        def __init__(self, *args, **kwargs):
            self.conf = _FakeConf()

        def task(self, bind=False, name=None, max_retries=None):
            def decorator(func):
                func.name = name or func.__name__
                func.max_retries = max_retries or 0
                func.delay = MagicMock()
                func.apply_async = MagicMock()
                return func
            return decorator

        def autodiscover_tasks(self, *args, **kwargs):
            pass

    celery_stub = types.ModuleType("celery")
    celery_stub.Celery = _FakeCelery
    sys.modules["celery"] = celery_stub


def test_enqueue_rag_document_task_calls_delay() -> None:
    from rag.tasks import enqueue_rag_document_task, process_rag_document

    process_rag_document.delay = MagicMock()
    result = enqueue_rag_document_task(123)

    assert result is True
    process_rag_document.delay.assert_called_once_with(123)


def test_enqueue_rag_document_task_returns_false_on_failure() -> None:
    from rag.tasks import enqueue_rag_document_task, process_rag_document

    process_rag_document.delay = MagicMock(side_effect=Exception("redis down"))
    result = enqueue_rag_document_task(123)

    assert result is False


def test_process_rag_document_task_registered() -> None:
    """验证任务名与重试次数已正确注册。"""
    from rag.tasks import process_rag_document

    assert process_rag_document.name == "rag.tasks.process_rag_document"
    assert process_rag_document.max_retries >= 1


def test_enqueue_rag_document_tasks_counts_batch() -> None:
    """批量投递：返回 (成功数量, 失败数量)。"""
    from rag.tasks import enqueue_rag_document_tasks, enqueue_rag_document_task

    # 第 2 个投递失败
    original = enqueue_rag_document_task
    calls = {"n": 0}

    def fake_enqueue(rid: int) -> bool:
        calls["n"] += 1
        return calls["n"] != 2

    with patch("rag.tasks.enqueue_rag_document_task", side_effect=fake_enqueue):
        enqueued, failed = enqueue_rag_document_tasks([1, 2, 3])

    assert enqueued == 2
    assert failed == 1


def test_enqueue_rag_document_tasks_empty() -> None:
    """空列表：直接返回 (0, 0)。"""
    from rag.tasks import enqueue_rag_document_tasks

    assert enqueue_rag_document_tasks([]) == (0, 0)
