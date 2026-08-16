# 说明：
# 使用 Python slim 作为基础镜像，避免拉取完整 Debian 版 uv 镜像导致构建层过大。
# uv 仍在镜像内安装并负责同步 uv.lock，保持项目依赖管理方式一致。
FROM python:3.12-slim-bookworm

WORKDIR /app

# 说明：
# UV_LINK_MODE=copy 可以避免跨 Docker layer 的硬链接告警；
# PYTHONUNBUFFERED 确保容器日志实时输出，便于 compose logs 排查问题。
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# 说明：
# 容器构建阶段需要 uv 读取 uv.lock 并创建隔离依赖环境。
RUN pip install --no-cache-dir uv

# 说明：
# 先复制依赖清单并安装依赖，让后续业务代码变更时能复用依赖缓存。
COPY pyproject.toml uv.lock ./
# 说明：允许构建时用 --build-arg UV_DEFAULT_INDEX=<镜像源> 覆盖 PyPI 源，网络受限环境可加速。
ARG UV_DEFAULT_INDEX="https://pypi.org/simple"
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
RUN uv sync --frozen --no-install-project
RUN uv pip install pgvector 'markitdown[all]'

# 说明：
# 只复制运行 FastAPI 所需的应用代码，测试缓存和本地虚拟环境会被 .dockerignore 排除。
COPY app ./app
COPY rag ./rag

EXPOSE 8000

# 说明：
# 运行时使用 --no-sync，避免容器启动时再次解析或修改依赖环境。
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
