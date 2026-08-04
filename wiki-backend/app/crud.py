"""
CRUD operations for Folder and File models.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Folder, File
from app.core.config import settings
from app.core.storage import get_file_content as s3_get_content

async def get_folder_by_full_path(db: AsyncSession, full_path: str) -> Optional[Folder]:
    """Get a folder by its full_path."""
    result = await db.execute(
        select(Folder).where(Folder.full_path == full_path)
    )
    return result.scalar_one_or_none()


async def get_file_by_full_path(db: AsyncSession, full_path: str) -> Optional[File]:
    """Get a file by its full_path."""
    result = await db.execute(
        select(File).where(File.full_path == full_path)
    )
    return result.scalar_one_or_none()


async def get_folder_by_id(db: AsyncSession, folder_id: int) -> Optional[Folder]:
    """Get a folder by its ID."""
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id)
    )
    return result.scalar_one_or_none()


async def get_file_by_id(db: AsyncSession, file_id: int) -> Optional[File]:
    """Get a file by its ID."""
    result = await db.execute(
        select(File).where(File.id == file_id)
    )
    return result.scalar_one_or_none()


async def build_tree(db: AsyncSession) -> list[dict]:
    """
    Build a nested tree structure of all folders and files.
    Returns a list of root folders with nested children and files.
    """
    # Get all folders and files
    folders_result = await db.execute(select(Folder).order_by(Folder.sort_order, Folder.title))
    all_folders = list(folders_result.scalars().all())
    
    files_result = await db.execute(select(File).order_by(File.sort_order, File.title))
    all_files = list(files_result.scalars().all())
    
    # Create a mapping of folder id -> folder dict
    folder_map: dict[int, dict] = {}
    for folder in all_folders:
        folder_map[folder.id] = {
            "id": folder.id,
            "title": folder.title,
            "slug": folder.slug,
            "full_path": folder.full_path,
            "sort_order": folder.sort_order,
            "children": [],
            "files": [],
        }
        
    root_folders: list[dict] = []
    
    # Map folders to parents
    for folder in all_folders:
        folder_dict = folder_map[folder.id]
        if folder.parent_id is None:
            root_folders.append(folder_dict)
        elif folder.parent_id in folder_map:
            folder_map[folder.parent_id]["children"].append(folder_dict)
            
    # Attach files to folders
    root_files: list[dict] = []
    for file_obj in all_files:
        file_dict = {
            "id": file_obj.id,
            "title": file_obj.title,
            "slug": file_obj.slug,
            "full_path": file_obj.full_path,
            "sort_order": file_obj.sort_order,
            "storage_key": file_obj.storage_key,
        }
        if file_obj.folder_id is None:
            root_files.append(file_dict)
        elif file_obj.folder_id in folder_map:
            folder_map[file_obj.folder_id]["files"].append(file_dict)
            
    # We will return the sorted root folders and root files for the tree UI.
    root_items = root_folders + root_files
    root_items.sort(key=lambda x: x.get("sort_order", 0))
    return root_items


async def get_file_content_by_file(file_obj: File) -> tuple[Optional[str], Optional[str]]:
    """
    Read file content from S3 logic.
    """
    if not file_obj.storage_key:
        return None, None
        
    # Read from S3
    content_bytes = await s3_get_content(file_obj.storage_key)
    if content_bytes is None:
        return None, None
        
    import pathlib
    file_ext = pathlib.Path(file_obj.storage_key).suffix.lower()
    
    TEXT_EXTENSIONS = {".md", ".txt", ".html"}
    BINARY_EXTENSIONS = {".pdf", ".docx"}
        
    try:
        if file_ext in TEXT_EXTENSIONS:
            content = content_bytes.decode("utf-8")
            return content, "text"
        elif file_ext in BINARY_EXTENSIONS:
            import base64
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
            return content_b64, "base64"
        else:
            return None, None
    except Exception as e:
        print(f"Error processing S3 file content: {e}")
        return None, None


async def create_folder(
    db: AsyncSession,
    parent_id: Optional[int],
    title: str,
    slug: str,
    full_path: str,
    sort_order: int = 0,
) -> Folder:
    """Create a new folder."""
    folder = Folder(
        parent_id=parent_id,
        title=title,
        slug=slug,
        full_path=full_path,
        sort_order=sort_order,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


async def create_file(
    db: AsyncSession,
    folder_id: Optional[int],
    title: str,
    slug: str,
    full_path: str,
    storage_key: str,
    sort_order: int = 0,
) -> File:
    """Create a new file."""
    file_obj = File(
        folder_id=folder_id,
        title=title,
        slug=slug,
        full_path=full_path,
        storage_key=storage_key,
        sort_order=sort_order,
    )
    db.add(file_obj)
    await db.commit()
    await db.refresh(file_obj)
    return file_obj


async def delete_folder(db: AsyncSession, folder: Folder) -> bool:
    """Delete a folder and its children/files."""
    await db.delete(folder)
    await db.commit()
    return True


async def delete_file_record(db: AsyncSession, file_obj: File) -> bool:
    """Delete a file record."""
    await db.delete(file_obj)
    await db.commit()
    return True
