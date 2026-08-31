from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select

from app.core.database import get_db
from app.core.security import verify_password, create_access_token, get_current_user
from app import models
from app.schemas import LoginRequest, LoginResponse, UserResponse, ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={401: {"model": ErrorResponse}},
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Log in with username and password to get a JWT access token.
    """
    result = await db.execute(
        select(models.User).filter(models.User.username == request.username)
    )
    user = result.scalars().first()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该账户已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token = create_access_token(
        data={"sub": user.username, "uid": user.id, "role": user.role}
    )

    return LoginResponse(
        access_token=access_token,
        username=user.username,
        role=user.role,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    responses={401: {"model": ErrorResponse}},
)
async def get_me(
    current_user: models.User = Depends(get_current_user),
) -> UserResponse:
    """
    Get current logged in user profile.
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        is_active=current_user.is_active,
    )


@router.get("/memories")
async def list_my_memories(
    workspace_id: str = "default",
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户自己的长期记忆，不允许跨用户读取。"""
    result = await db.execute(
        select(models.Memory)
        .where(models.Memory.user_id == current_user.id)
        .where(models.Memory.workspace_id == workspace_id)
        .order_by(models.Memory.importance.desc(), models.Memory.updated_at.desc())
        .limit(200)
    )
    return {
        "memories": [
            {
                "id": item.id,
                "content": item.content,
                "importance": item.importance,
                "workspace_id": item.workspace_id,
                "source_session_id": item.source_session_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in result.scalars().all()
        ]
    }


@router.delete("/memories/{memory_id}")
async def delete_my_memory(
    memory_id: int,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除当前用户的一条长期记忆。"""
    result = await db.execute(
        delete(models.Memory)
        .where(models.Memory.id == memory_id)
        .where(models.Memory.user_id == current_user.id)
    )
    await db.commit()
    if not (result.rowcount or 0):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"success": True}


@router.delete("/memories")
async def clear_my_memories(
    workspace_id: str = "default",
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """清空当前用户在指定工作区的长期记忆。"""
    result = await db.execute(
        delete(models.Memory)
        .where(models.Memory.user_id == current_user.id)
        .where(models.Memory.workspace_id == workspace_id)
    )
    await db.commit()
    return {"success": True, "deleted": result.rowcount or 0}
