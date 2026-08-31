from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.core.config import settings
from app.core.database import check_and_create_database, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup: Initialize database and S3
    print("Starting up...")
    settings.validate_runtime_security()
    check_and_create_database()
    await init_db()

    from app.core.storage import ensure_bucket_exists
    await ensure_bucket_exists()

    # 恢复遗留的 processing 状态文档（worker 重启/部署后崩溃遗留），重置回 pending 并重新投递
    try:
        from rag.task_worker import reset_stale_processing_documents
        stale_ids = await reset_stale_processing_documents()
        if stale_ids:
            from rag.tasks import enqueue_rag_document_tasks
            enqueued, failed = enqueue_rag_document_tasks(stale_ids)
            print(
                f"Reset {len(stale_ids)} stale processing documents, "
                f"re-enqueued {enqueued}, enqueue failed {failed}."
            )
    except Exception as exc:
        print(f"Failed to reset stale processing documents: {exc}")

    print("Database and Storage initialized.")

    yield

    print("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    description="Wiki Backend API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Welcome to Wiki Backend API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
