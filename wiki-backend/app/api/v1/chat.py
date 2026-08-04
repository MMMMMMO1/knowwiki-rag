import os
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db, AsyncSessionLocal
from app.core.security import get_current_user
from app.core.config import settings
from app import models
from app.schemas import ErrorResponse

router = APIRouter(prefix="/chat", tags=["chat"])

# 前端 session_id → AnythingLLM thread slug 的映射缓存。
# key 是前端生成的本地 UUID，value 是工作区 thread 的 slug。
_session_thread_map: dict[str, str] = {}


class ChatStreamRequest(BaseModel):
    message: str
    session_id: str
    prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None


async def _ensure_thread_slug(session_id: str) -> str:
    """保证前端 session_id 已绑定到 AnythingLLM 工作区 thread，返回 thread slug。"""
    if session_id in _session_thread_map:
        return _session_thread_map[session_id]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.ANYTHINGLLM_API_URL}/api/v1/workspace/{settings.ANYTHINGLLM_WORKSPACE_SLUG}/thread/new",
            headers={
                "Authorization": f"Bearer {settings.ANYTHINGLLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"name": session_id},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        thread_slug: str = data["thread"]["slug"]
        _session_thread_map[session_id] = thread_slug
        return thread_slug


async def stream_generator(
    user_id: int,
    session_id: str,
    message: str,
    embed_id: str,
    payload: dict
):
    # 1. Log user message to database
    async with AsyncSessionLocal() as db_session:
        try:
            user_msg = models.ChatLog(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=message
            )
            db_session.add(user_msg)
            await db_session.commit()
        except Exception as db_err:
            print(f"Failed to log user message: {db_err}")

    accumulated_response = []
    url = f"{settings.ANYTHINGLLM_API_URL}/api/embed/{embed_id}/stream-chat"

    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, json=payload, timeout=60.0) as response:
                if response.status_code != 200:
                    yield f"data: {json.dumps({'type': 'abort', 'error': f'AnythingLLM error: {response.status_code}'})}\n\n"
                    return

                # Read the streaming SSE response
                async for chunk in response.aiter_lines():
                    if chunk.startswith("data:"):
                        data_str = chunk[5:].strip()
                        if data_str == "[DONE]":
                            yield chunk + "\n\n"
                            continue
                        try:
                            data_json = json.loads(data_str)
                            # Accumulate text chunks to log assistant response later
                            if data_json.get("type") == "textResponseChunk":
                                text = data_json.get("textResponse", "")
                                if text:
                                    accumulated_response.append(text)
                            elif data_json.get("type") == "textResponse":
                                text = data_json.get("textResponse", "")
                                if text:
                                    accumulated_response.append(text)
                        except Exception:
                            pass

                    yield chunk + "\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'abort', 'error': f'Streaming connection failed: {str(e)}'})}\n\n"
            return

    # 2. Log assistant response to database
    assistant_text = "".join(accumulated_response).strip()
    if assistant_text:
        async with AsyncSessionLocal() as db_session:
            try:
                assistant_msg = models.ChatLog(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=assistant_text
                )
                db_session.add(assistant_msg)
                await db_session.commit()
            except Exception as db_err:
                print(f"Failed to log assistant message: {db_err}")


@router.post("/stream")
async def chat_stream(
    request: ChatStreamRequest,
    current_user: models.User = Depends(get_current_user),
):
    """
    Stream chat from AnythingLLM, authenticating the user and logging messages.
    """
    embed_id = os.getenv("NEXT_PUBLIC_CHATBOT_EMBED_ID", "").strip()
    if not embed_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chatbot embed ID is not configured on backend."
        )

    # 前端 session_id 是本地 UUID，需要先映射为 AnythingLLM 工作区 thread slug。
    try:
        thread_slug = await _ensure_thread_slug(request.session_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"无法创建 AnythingLLM 会话：{e}",
        )

    # Build payload to forward to AnythingLLM
    payload = {
        "message": request.message,
        "sessionId": thread_slug,
        "username": current_user.username,
        "prompt": request.prompt,
        "model": request.model,
        "temperature": request.temperature,
    }

    return StreamingResponse(
        stream_generator(
            user_id=current_user.id,
            session_id=request.session_id,
            message=request.message,
            embed_id=embed_id,
            payload=payload
        ),
        media_type="text/event-stream"
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
    """
    Clear chat history for a session from database and notify AnythingLLM.
    """
    # 1. Clear database logs
    await db.execute(
        delete(models.ChatLog)
        .filter(models.ChatLog.user_id == current_user.id)
        .filter(models.ChatLog.session_id == session_id)
    )
    await db.commit()

    # 2. Reset session in AnythingLLM
    embed_id = os.getenv("NEXT_PUBLIC_CHATBOT_EMBED_ID", "").strip()
    thread_slug = _session_thread_map.pop(session_id, None)
    if embed_id and thread_slug:
        url = f"{settings.ANYTHINGLLM_API_URL}/api/embed/{embed_id}/{thread_slug}"
        try:
            async with httpx.AsyncClient() as client:
                await client.delete(url, timeout=10.0)
        except Exception as e:
            print(f"Failed to reset AnythingLLM session: {e}")

    return {"success": True}

    
