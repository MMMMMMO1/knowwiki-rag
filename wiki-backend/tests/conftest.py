"""pytest 全局配置 —— 环境未安装 celery 时注入最小假模块。

rag.tasks / rag.celery_app 在导入时需要 celery；本地测试不跑真实 worker，
因此用假模块保证这些模块可导入，投递逻辑再由各测试自行 mock。
放在 conftest 中是为了让所有测试（不依赖 test_rag_task_queue 的导入顺序）都能
独立导入 rag.tasks。
"""

import sys
import types
from unittest.mock import MagicMock


def _install_fake_celery() -> None:
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


try:
    import celery  # noqa: F401
except ImportError:
    _install_fake_celery()
