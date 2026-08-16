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
    # 混合检索开关：True 时向量检索 + 关键词全文检索（tsvector）用 RRF 融合；
    # 默认 False 保持纯向量检索，向后兼容。
    HYBRID_SEARCH: bool = False

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
