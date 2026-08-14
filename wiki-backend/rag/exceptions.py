"""
RAG 索引异常类型。

RetryableIndexingError: 可重试的入库错误（网络抖动、S3 暂不可用、embedding API 限流/5xx 等），
    抛出后由 Celery 在延迟后自动重试。
其他异常（如 ValueError）默认视为最终失败，不会被自动重试。
"""


class RetryableIndexingError(Exception):
    """可重试的入库错误，会触发 Celery 自动重试。"""
