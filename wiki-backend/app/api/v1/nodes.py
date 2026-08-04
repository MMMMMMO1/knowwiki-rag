"""
Nodes API endpoints.

Endpoints:
- GET /api/v1/nodes/tree - Get nested directory tree
- GET /api/v1/nodes/resolve/{path:path} - Get node by full_path with content
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Union

from app.core.database import get_db
from app.core.security import get_current_user
from app.crud import get_folder_by_full_path, get_file_by_full_path, build_tree, get_file_content_by_file
from app import models
from app.schemas import FolderResponse, FileWithContent, ErrorResponse

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("/tree")
async def get_tree(
    _: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """
    Get the nested directory tree.
    
    Returns a hierarchical structure of all folders and files.
    """
    tree = await build_tree(db)
    return tree


@router.get(
    "/resolve/{path:path}",
    response_model=Union[FolderResponse, FileWithContent],
    responses={404: {"model": ErrorResponse}},
)
async def resolve_path(
    path: str,
    _: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Resolve a path and return the folder or file node.
    """
    normalized_path = path.strip("/")
    
    # Try resolving as a file
    file_node = await get_file_by_full_path(db, normalized_path)
    if file_node:
        content, content_type = await get_file_content_by_file(file_node)
        return FileWithContent(
            id=file_node.id,
            folder_id=file_node.folder_id,
            title=file_node.title,
            slug=file_node.slug,
            full_path=file_node.full_path,
            sort_order=file_node.sort_order,
            content=content,
            content_type=content_type,
        )
        
    # Try resolving as a folder
    folder_node = await get_folder_by_full_path(db, normalized_path)
    if folder_node:
        return FolderResponse(
            id=folder_node.id,
            parent_id=folder_node.parent_id,
            title=folder_node.title,
            slug=folder_node.slug,
            full_path=folder_node.full_path,
            sort_order=folder_node.sort_order,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Path not found: {normalized_path}",
    )
