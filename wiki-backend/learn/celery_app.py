from celery import Celery
celery_app = Celery

celery_app= Celery(
    "learn_rag",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)
