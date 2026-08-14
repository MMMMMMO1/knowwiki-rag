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
    #    与 main 的 AnythingLLM thread 行为对齐：同 session 保留最近若干条上下文。
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
                prompt=request.prompt,
                model=request.model,
                temperature=request.temperature,
                chat_history=chat_history,
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

    
