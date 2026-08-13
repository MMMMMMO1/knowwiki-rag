"""
RAG API 路由 —— 暴露索引和查询两条链路。

索引: POST /api/v1/rag/ingest     → 异步入库
查询: POST /api/v1/chat/rag/stream → RAG 流式聊天
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, verify_admin_token
from rag.chat_service import ChatService
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


class RagChatRequest(BaseModel):
    message: str


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


# ── 查询路由 ──────────────────────────────────────────────

@router.post("/chat/rag/stream")
async def rag_chat_stream(
    body: RagChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """RAG 流式聊天 —— 检索知识库并用 LLM 生成回答。

    返回 SSE (Server-Sent Events) 流。
    """
    service = ChatService()

    async def event_stream():
        try:
            async for token in service.ask_stream(body.message, db):
                # SSE 格式: data: <内容>\n\n
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
