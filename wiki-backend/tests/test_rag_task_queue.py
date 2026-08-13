"""RAG 消息队列投递测试 —— 验证 Celery 任务投递逻辑。"""

from unittest.mock import patch

import pytest

# celery/redis 未安装时跳过（Docker 内 uv sync 后可用）
celery = pytest.importorskip("celery", reason="celery 未安装")


def test_enqueue_rag_document_task_calls_delay() -> None:
    from rag.tasks import enqueue_rag_document_task

    with patch("rag.tasks.process_rag_document.delay") as mock_delay:
        result = enqueue_rag_document_task(123)

    assert result is True
    mock_delay.assert_called_once_with(123)


def test_enqueue_rag_document_task_returns_false_on_failure() -> None:
    from rag.tasks import enqueue_rag_document_task

    with patch("rag.tasks.process_rag_document.delay", side_effect=Exception("redis down")):
        result = enqueue_rag_document_task(123)

    assert result is False


def test_process_rag_document_task_registered() -> None:
    """验证任务名已注册到 Celery app。"""
    from rag.tasks import process_rag_document

    assert process_rag_document.name == "rag.tasks.process_rag_document"
    assert process_rag_document.max_retries >= 1
