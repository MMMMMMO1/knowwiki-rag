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
    check_and_create_database()
    await init_db()
    
    from app.core.storage import ensure_bucket_exists
    await ensure_bucket_exists()
    
    print("Database and Storage initialized.")

    # Start RAG TaskWorker in background
    import asyncio
    from rag.task_worker import TaskWorker
    worker = TaskWorker()
    worker_task = asyncio.create_task(worker.run())
    print("TaskWorker started.")

    yield

    # Shutdown
    worker.stop()
    await worker_task
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
