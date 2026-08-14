"""RAG 配置可用性检查测试 —— 只返回 boolean 与缺失项，不泄露密钥值。"""

import asyncio
from unittest.mock import patch


def test_rag_config_status_reports_missing() -> None:
    from app.api.v1.rag import rag_config_status
    from app.core.config import settings

    with patch.object(settings, "LLM_API_KEY", ""), \
            patch.object(settings, "EMBEDDING_API_KEY", "sk-xxx"), \
            patch.object(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0"):
        resp = asyncio.run(rag_config_status())

    assert resp["success"] is True
    assert resp["ready"] is False
    assert "LLM_API_KEY" in resp["missing"]
    assert resp["llm_configured"] is False
    assert resp["embedding_configured"] is True
    assert resp["queue_configured"] is True
    # 不输出密钥值：响应里只包含名称与 boolean
    assert "sk-xxx" not in str(resp)


def test_rag_config_status_ready_when_all_configured() -> None:
    from app.api.v1.rag import rag_config_status
    from app.core.config import settings

    with patch.object(settings, "LLM_API_KEY", "key-a"), \
            patch.object(settings, "EMBEDDING_API_KEY", "key-b"), \
            patch.object(settings, "CELERY_BROKER_URL", "redis://redis:6379/0"):
        resp = asyncio.run(rag_config_status())

    assert resp["ready"] is True
    assert resp["missing"] == []
