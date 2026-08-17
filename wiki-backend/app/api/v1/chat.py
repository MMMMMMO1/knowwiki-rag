import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app import models

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatStreamRequest(BaseModel):
    message: str
    session_id: str
    prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    workspace_id: Optional[str] = None


def _resolve_chat_overrides(
    request: ChatStreamRequest,
    current_user: models.User,
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """仅 admin 可覆盖 prompt/model/temperature；普通用户返回 None（走服务端配置）。

    防止前端伪造参数绕过成本控制或安全策略。
    """
    if current_user.role == "admin":
        return request.prompt, request.model, request.temperature
    return None, None, None


def _resolve_workspace_id(
    request: ChatStreamRequest,
    current_user: models.User,
) -> str:
    """仅 admin 可指定 workspace_id；普通用户一律使用默认工作区。

    当前尚无用户-工作区绑定表，采用最小安全策略：非 admin 固定返回 "default"。
    """
    if current_user.role == "admin":
        return request.workspace_id or "default"
    return "default"


@router.post("/stream")
async def chat_stream(
    request: ChatStreamRequest,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    RAG 流式聊天 —— 向量检索 + LLM 流式回答。

    保留前端兼容的 SSE JSON 协议：
    - textResponseChunk: 增量 token
    - textResponse: 完成，附带 sources
    - abort: 错误
    """
    # 1. 查询同会话最近历史（先于写入当前消息，避免把当前问题算进历史）。
    #    保留历史会话上下文：同 session 取最近若干条消息传给 LLM，支持多轮追问。
    HISTORY_LIMIT = 10
    history_result = await db.execute(
        select(models.ChatLog)
        .where(models.ChatLog.user_id == current_user.id)
        .where(models.ChatLog.session_id == request.session_id)
        .order_by(models.ChatLog.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    recent_logs = list(history_result.scalars().all())
    recent_logs.reverse()  # 转回时间正序，再喂给 LLM
    chat_history = [
        {"role": log.role, "content": log.content}
        for log in recent_logs
    ]

    # 命名空间：仅 admin 可指定；普通用户一律使用默认工作区，防止越权访问其他知识域
    workspace_id = _resolve_workspace_id(request, current_user)

    # 权限：仅 admin 可覆盖 prompt/model/temperature；普通用户一律使用服务端配置，
    # 防止前端伪造参数绕过成本控制或安全策略。
    override_prompt, override_model, override_temperature = _resolve_chat_overrides(
        request, current_user
    )

    # 2. 记录用户消息
    user_msg = models.ChatLog(
        user_id=current_user.id,
        session_id=request.session_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)
    await db.commit()

    async def rag_event_stream():
        accumulated: list[str] = []

        try:
            from rag.chat_service import ChatService
            service = ChatService()

            async for token in service.ask_stream(
                request.message,
                db,
                prompt=override_prompt,
                model=override_model,
                temperature=override_temperature,
                chat_history=chat_history,
                workspace_id=workspace_id,
                user_id=current_user.id,
            ):
                accumulated.append(token)
                yield f"data: {json.dumps({'type': 'textResponseChunk', 'textResponse': token, 'sources': [], 'close': False})}\n\n"

            # 完成事件（附带 sources）
            full_text = "".join(accumulated)
            yield f"data: {json.dumps({'type': 'textResponse', 'textResponse': full_text, 'sources': service.last_sources, 'close': True})}\n\n"

            # 3. 记录助手回复
            if full_text.strip():
                assistant_msg = models.ChatLog(
                    user_id=current_user.id,
                    session_id=request.session_id,
                    role="assistant",
                    content=full_text,
                )
                db.add(assistant_msg)
                await db.commit()

                # 4. 异步提取长期记忆（后台 Celery，不阻塞响应）
                from app.core.config import settings
                if settings.MEMORY_ENABLED and settings.MEMORY_EXTRACT_ENABLED:
                    from rag.tasks import enqueue_memory_extraction
                    enqueue_memory_extraction(
                        user_id=current_user.id,
                        workspace_id=workspace_id,
                        session_id=request.session_id,
                        user_message=request.message,
                        assistant_message=full_text,
                    )

        except Exception as e:
            yield f"data: {json.dumps({'type': 'abort', 'textResponse': None, 'sources': [], 'close': True, 'error': str(e)})}\n\n"

    return StreamingResponse(
        rag_event_stream(),
        media_type="text/event-stream",
    )


@router.get("/history")
async def get_chat_history(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve user-specific chat history for a session from local database.
    """
    result = await db.execute(
        select(models.ChatLog)
        .filter(models.ChatLog.user_id == current_user.id)
        .filter(models.ChatLog.session_id == session_id)
        .order_by(models.ChatLog.created_at.asc())
    )
    logs = result.scalars().all()

    history = []
    for log in logs:
        history.append({
            "role": log.role,
            "content": log.content,
            "sentAt": int(log.created_at.timestamp())
        })

    return {"history": history}


@router.delete("/history")
async def reset_chat_session(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear chat history for a session from database."""
    await db.execute(
        delete(models.ChatLog)
        .filter(models.ChatLog.user_id == current_user.id)
        .filter(models.ChatLog.session_id == session_id)
    )
    await db.commit()

    return {"success": True}

    
