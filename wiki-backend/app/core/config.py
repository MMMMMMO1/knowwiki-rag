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

    # AnythingLLM sync settings
    ANYTHINGLLM_API_URL: str = "http://127.0.0.1:3001"
    ANYTHINGLLM_API_KEY: str = ""
    ANYTHINGLLM_WORKSPACE_SLUG: str = ""
    ANYTHINGLLM_SYNC_MAX_RETRIES: int = 3

    class Config:
        env_file = ROOT_ENV_FILE
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
