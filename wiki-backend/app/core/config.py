from pathlib import Path

from pydantic_settings import BaseSettings


ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application settings."""

    APP_NAME: str = "Wiki Backend"
    DEBUG: bool = False

    # CORS settings
    CORS_ORIGINS: list[str] = ["*"]

    # Database settings (PostgreSQL)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "duhakeer"
    DB_NAME: str = "postgres"

    @property
    def DATABASE_URL(self) -> str:
        """Async PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync PostgreSQL connection URL for database creation."""
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def DATABASE_URL_ADMIN(self) -> str:
        """Admin connection URL (connects to postgres database for creating new databases)."""
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/postgres"

    # Wiki storage settings (S3/RustFS)
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "wiki-bucket"

    # JWT authentication secret
    JWT_SECRET: str = "change-me-in-production"

    # RAG settings
    LLM_API_URL: str = "https://api.deepseek.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v4-flash"
    EMBEDDING_API_URL: str =  "https://ws-9a2hqxduvazwrik2.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-v3"
    VECTOR_DIM: int = 1024  # text-embedding-v3 输出维度
    EMBEDDING_BATCH_SIZE: int = 8
    EMBEDDING_MAX_CHARS: int = 2000
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 5
    SYSTEM_PROMPT: str = ""
    # 默认生成温度（安全默认值，管理员可通过请求体覆盖）
    LLM_TEMPERATURE: float = 0.7
    # 混合检索开关：True 时向量检索 + 关键词全文检索（tsvector）用 RRF 融合；
    # 默认 True 开启混合检索，中文场景效果更佳。
    HYBRID_SEARCH: bool = True
    # Rerank switch: True re-ranks candidates after coarse recall, before format_context.
    # Default False keeps pure coarse recall, backward compatible.
    RERANK_ENABLED: bool = False
    # OpenAI-compatible /rerank endpoint URL (required when RERANK_ENABLED=True).
    RERANK_API_URL: str = ""
    # rerank API key; falls back to EMBEDDING_API_KEY when empty (same vendor most likely).
    RERANK_API_KEY: str = ""
    # rerank model name; bge-reranker family is the common choice.
    RERANK_MODEL: str = "bge-reranker-v2-m3"
    # Coarse recall candidate count when rerank is on (should exceed TOP_K).
    RERANK_CANDIDATE_K: int = 20

    # Memory settings: long-term memory distilled from conversations.
    # MEMORY_ENABLED gates recall + extraction; default False keeps old behavior.
    MEMORY_ENABLED: bool = False
    # Whether to extract memories asynchronously after each turn via LLM.
    MEMORY_EXTRACT_ENABLED: bool = True
    # How many memories to recall and merge into context.
    MEMORY_TOP_K: int = 3
    # Explicit "remember" phrases that force a memory to be kept (importance=1.0).
    MEMORY_EXPLICIT_KEYWORDS: list[str] = ["记住", "别忘了", "请记住"]

    # Whether to auto-apply HNSW vector indexes at startup.
    # Building HNSW on an existing large table can block startup for a long time;
    # keep False in production and run migrations/0004_add_vector_indexes.sql
    # manually during a low-traffic window instead.
    AUTO_APPLY_VECTOR_INDEXES: bool = False

    # Redis / Celery 消息队列设置（RAG 入库任务调度）
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"
    RAG_TASK_MAX_RETRIES: int = 3
    RAG_TASK_RETRY_DELAY_SECONDS: int = 30

    class Config:
        env_file = ROOT_ENV_FILE
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
