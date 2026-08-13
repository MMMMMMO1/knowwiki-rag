"""
RAG API 路由 —— 暴露索引链路。

索引: POST /api/v1/rag/ingest → 异步入库

查询链路走主接口 /api/v1/chat/stream（见 chat.py），
这里不再提供旁路 /chat/rag/stream，避免双协议维护。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_admin_token
from rag.ingest_service import IngestService

router = APIRouter(tags=["rag"])


# ── 请求模型 ──────────────────────────────────────────────

class IngestRequest(BaseModel):
    file_id: int


class IngestResponse(BaseModel):
    id: int
    file_id: int | None
    title: str
    status: str


# ── 索引路由 ──────────────────────────────────────────────

@router.post("/rag/ingest", response_model=IngestResponse)
async def rag_ingest(
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_admin_token),
):
    """提交 Wiki 文件到 RAG 异步入库队列。

    立即返回入库记录，实际处理由 TaskWorker 在后台完成。
    """
    try:
        service = IngestService(db)
        doc = await service.ingest(file_id=body.file_id)
        await db.commit()

        return IngestResponse(
            id=doc.id,
            file_id=doc.file_id,
            title=doc.title,
            status=doc.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
