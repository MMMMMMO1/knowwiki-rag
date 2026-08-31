"""
RAG API 路由 —— 暴露索引链路。

索引: POST /api/v1/rag/ingest → 异步入库

查询链路走主接口 /api/v1/chat/stream（见 chat.py），
这里不再提供旁路 /chat/rag/stream，避免双协议维护。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.database import get_db
from app.core.security import require_roles, verify_admin_token
from rag.ingest_service import IngestService

router = APIRouter(tags=["rag"])


# ── 请求模型 ──────────────────────────────────────────────

class IngestRequest(BaseModel):
    file_id: int
    workspace_id: str = "default"


class IngestResponse(BaseModel):
    id: int
    file_id: int | None
    title: str
    status: str


class DebugRequest(BaseModel):
    question: str
    session_id: str
    workspace_id: Optional[str] = None
    chat_history: Optional[list[dict[str, str]]] = None


# ── 索引路由 ──────────────────────────────────────────────

@router.post("/rag/ingest", response_model=IngestResponse)
async def rag_ingest(
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(verify_admin_token),
):
    """提交 Wiki 文件到 RAG 入库队列。

    创建或重置 RagDocument 记录，然后投递 Celery 任务，立即返回。
    实际处理由 rag-worker 在后台完成。
    """
    workspace_id = body.workspace_id.strip() or "default"
    if workspace_id != "default" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以选择非默认工作区")
    try:
        service = IngestService(db)
        doc = await service.ingest(file_id=body.file_id, workspace_id=workspace_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 投递 Celery 任务
    from rag.tasks import enqueue_rag_document_task
    enqueue_required = doc.status == "pending"
    queued = enqueue_rag_document_task(doc.id) if enqueue_required else True
    if enqueue_required and not queued:
        from rag.task_worker import mark_rag_document_failed
        await mark_rag_document_failed(doc.id, "Celery 任务投递失败（Redis 不可用）")

    return IngestResponse(
        id=doc.id,
        file_id=doc.file_id,
        title=doc.title,
        status="failed" if not queued else doc.status,
    )


@router.post("/rag/debug")
async def rag_debug(
    body: DebugRequest,
    current_user: models.User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """RAG 检索链路 debug：返回各阶段中间结果，仅 admin 可用。"""
    from rag.chat_service import ChatService

    # 未显式传历史时，从 ChatLog 取同会话最近历史
    chat_history = body.chat_history
    if chat_history is None:
        history_result = await db.execute(
            select(models.ChatLog)
            .where(models.ChatLog.session_id == body.session_id)
            .order_by(models.ChatLog.created_at.desc())
            .limit(10)
        )
        logs = list(history_result.scalars().all())
        logs.reverse()
        chat_history = [{"role": log.role, "content": log.content} for log in logs]

    workspace_id = body.workspace_id or "default"
    service = ChatService()
    return await service.debug(
        question=body.question,
        db=db,
        chat_history=chat_history,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


@router.get("/rag/config-status")
async def rag_config_status():
    """轻量 RAG 配置可用性检查 —— 只返回 boolean 与缺失项名称，不输出任何密钥值。

    供前端聊天面板在用户发送消息前提示「知识库未配置完整」，
    避免用户发出消息后才看到底层错误。
    """
    from app.core.config import settings

    llm_ok = bool((settings.LLM_API_KEY or "").strip())
    embedding_ok = bool((settings.EMBEDDING_API_KEY or "").strip())
    queue_ok = bool((settings.CELERY_BROKER_URL or "").strip())

    missing: list[str] = []
    if not llm_ok:
        missing.append("LLM_API_KEY")
    if not embedding_ok:
        missing.append("EMBEDDING_API_KEY")
    if not queue_ok:
        missing.append("CELERY_BROKER_URL")

    return {
        "success": True,
        "ready": not missing,
        "missing": missing,
        "llm_configured": llm_ok,
        "embedding_configured": embedding_ok,
        "queue_configured": queue_ok,
    }
