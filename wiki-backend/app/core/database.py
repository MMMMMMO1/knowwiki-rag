from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings

# Create async engine for normal operations
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency for getting database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# 与 migrations/0001_add_rag_queue_fields.sql 保持一致，便于已有数据库无感升级。
_RAG_QUEUE_MIGRATION_STATEMENTS = [
    "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS queued_at TIMESTAMPTZ",
    "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ",
    "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_rag_documents_status ON rag_documents (status)",
    "CREATE INDEX IF NOT EXISTS ix_rag_documents_retry_count ON rag_documents (retry_count)",
]

# 与 migrations/0002_add_chunk_search_text.sql 保持一致。
# search_text 存 jieba 分词后的空格分隔文本，GIN 索引建在 to_tsvector('simple', ...) 表达式上。
_HYBRID_SEARCH_MIGRATION_STATEMENTS = [
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS search_text TEXT",
    "CREATE INDEX IF NOT EXISTS ix_rag_chunks_search_text_tsv "
    "ON rag_chunks USING gin (to_tsvector('simple', search_text))",
]

# Keep in sync with migrations/0003_add_workspace_and_memories.sql.
# workspace_id is the namespace tag written at ingest time; retrieval filters on it.
# Existing rows backfill 'default'; the memories table is created by create_all.
_WORKSPACE_MEMORY_MIGRATION_STATEMENTS = [
    "ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(100) NOT NULL DEFAULT 'default'",
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(100) NOT NULL DEFAULT 'default'",
    "CREATE INDEX IF NOT EXISTS ix_rag_documents_workspace_id ON rag_documents (workspace_id)",
    "CREATE INDEX IF NOT EXISTS ix_rag_chunks_workspace_id ON rag_chunks (workspace_id)",
]

# Keep in sync with migrations/0004_add_vector_indexes.sql.
# HNSW index accelerates cosine-distance nearest-neighbor search as data grows.
# NOTE: building an HNSW index on an existing large table can block startup for a
# long time. This automatic migration targets dev environments / near-empty tables;
# for production with existing data, run migrations/0004_add_vector_indexes.sql
# manually during a low-traffic window instead.
_VECTOR_INDEX_MIGRATION_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw "
    "ON rag_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw "
    "ON memories USING hnsw (embedding vector_cosine_ops)",
]


async def _apply_rag_queue_migration(conn) -> None:
    """幂等补齐 rag_documents 的消息队列列（对新建表为 no-op）。"""
    try:
        for statement in _RAG_QUEUE_MIGRATION_STATEMENTS:
            await conn.execute(text(statement))
    except ProgrammingError:
        # 表尚不存在（首次启动 create_all 尚未建表时）——由 create_all 保证完整建表
        pass


async def _apply_hybrid_search_migration(conn) -> None:
    """幂等补齐 rag_chunks 的关键词检索列与 GIN 索引。"""
    try:
        for statement in _HYBRID_SEARCH_MIGRATION_STATEMENTS:
            await conn.execute(text(statement))
    except ProgrammingError:
        # 表尚不存在（首次启动 create_all 尚未建表时）——由 create_all 保证完整建表
        pass


async def _apply_workspace_memory_migration(conn) -> None:
    """幂等补齐 rag_documents/rag_chunks 的 workspace_id 命名空间列。"""
    try:
        for statement in _WORKSPACE_MEMORY_MIGRATION_STATEMENTS:
            await conn.execute(text(statement))
    except ProgrammingError:
        # 表尚不存在（首次启动 create_all 尚未建表时）——由 create_all 保证完整建表
        pass


async def _apply_vector_index_migration(conn) -> None:
    """幂等创建 embedding 列的 HNSW 向量索引。"""
    try:
        for statement in _VECTOR_INDEX_MIGRATION_STATEMENTS:
            await conn.execute(text(statement))
    except ProgrammingError:
        # 表尚不存在（首次启动 create_all 尚未建表时）——由 create_all 保证完整建表
        pass


def check_and_create_database() -> bool:
    """
    Check if the database exists, create it if not.
    Returns True if database exists or was created successfully.
    """
    from sqlalchemy_utils import database_exists, create_database

    sync_url = settings.DATABASE_URL_SYNC

    try:
        if not database_exists(sync_url):
            print(f"Database '{settings.DB_NAME}' does not exist. Creating...")
            create_database(sync_url)
            print(f"Database '{settings.DB_NAME}' created successfully.")
            return True
        else:
            print(f"Database '{settings.DB_NAME}' already exists.")
            return True
    except Exception as e:
        print(f"Error checking/creating database: {e}")
        # Try alternative method using raw SQL
        try:
            admin_engine = create_engine(settings.DATABASE_URL_ADMIN, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                # Check if database exists
                result = conn.execute(
                    text(f"SELECT 1 FROM pg_database WHERE datname = '{settings.DB_NAME}'")
                )
                if not result.fetchone():
                    conn.execute(text(f'CREATE DATABASE "{settings.DB_NAME}"'))
                    print(f"Database '{settings.DB_NAME}' created successfully.")
                else:
                    print(f"Database '{settings.DB_NAME}' already exists.")
            admin_engine.dispose()
            return True
        except Exception as e2:
            print(f"Failed to create database: {e2}")
            return False


async def verify_connection() -> bool:
    """Verify database connection is working."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            print("Database connection verified successfully.")
            return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


async def init_db():
    """Initialize database tables."""
    # Import models to register them with Base
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        # 确保 pgvector 扩展已启用
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # 幂等迁移：为已有数据库补齐消息队列新增列（create_all 不会修改已存在的表）
        await _apply_rag_queue_migration(conn)
        # 幂等迁移：补齐关键词检索列与 GIN 索引
        await _apply_hybrid_search_migration(conn)
        # 幂等迁移：补齐 workspace 命名空间列
        await _apply_workspace_memory_migration(conn)
        # 幂等迁移：创建 embedding 列的 HNSW 向量索引（仅显式开启时执行，避免大表阻塞启动）
        if settings.AUTO_APPLY_VECTOR_INDEXES:
            await _apply_vector_index_migration(conn)
    print("Database tables initialized.")

    # Seed default admin user if no users exist
    from sqlalchemy import select
    from app.core.security import get_password_hash
    import os

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(models.User).limit(1))
            user = result.scalars().first()
            if not user:
                print("No users found. Seeding default administrator...")
                admin_username = os.getenv("ADMIN_USERNAME", "admin")
                admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

                hashed_pw = get_password_hash(admin_password)
                default_admin = models.User(
                    username=admin_username,
                    hashed_password=hashed_pw,
                    role="admin",
                    is_active=True
                )
                session.add(default_admin)
                await session.commit()
                print(f"Default admin user '{admin_username}' seeded successfully.")
            else:
                print("Database already contains users. Seeding skipped.")
        except Exception as e:
            print(f"Failed to seed default admin: {e}")
            await session.rollback()
