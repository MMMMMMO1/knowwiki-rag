from fastapi import APIRouter

from app.api.v1 import nodes, admin, auth, chat, rag

router = APIRouter()

# Include v1 routers
router.include_router(nodes.router, prefix="/v1")
router.include_router(admin.router, prefix="/v1")
router.include_router(auth.router, prefix="/v1")
router.include_router(chat.router, prefix="/v1")
router.include_router(rag.router, prefix="/v1")
