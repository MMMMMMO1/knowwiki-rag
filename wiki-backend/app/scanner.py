"""
Directory scanner module for syncing S3 to database.

This module provides functionality to scan S3 bucket
and synchronize its structure with the database using File and Folder models.
"""

import os
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Folder, File

# Supported file extensions
ALLOWED_EXTENSIONS = {".md", ".html", ".docx", ".txt", ".pdf"}


def normalize_title(filename: str) -> str:
    """
    Convert filename to a human-readable title.
    """
    file_path = Path(filename)
    name = file_path.stem if file_path.suffix.lower() in ALLOWED_EXTENSIONS else filename
    name = re.sub(r'^\d+[_\-]?', '', name)
    name = name.replace('_', ' ').replace('-', ' ')
    return name.title().strip()


def normalize_slug(filename: str) -> str:
    """
    Convert filename to URL-friendly slug.
    """
    file_path = Path(filename)
    name = file_path.stem if file_path.suffix.lower() in ALLOWED_EXTENSIONS else filename
    name = re.sub(r'^\d+[_\-]?', '', name)
    name = name.replace('_', '-').replace(' ', '-')
    name = re.sub(r'[^\w\-]', '', name, flags=re.UNICODE)
    result = ''
    for char in name:
        if char.isascii():
            result += char.lower()
        else:
            result += char
    result = re.sub(r'-+', '-', result).strip('-')
    return result if result else 'untitled'


def extract_sort_order(filename: str) -> int:
    """
    Extract sort order from filename prefix.
    """
    match = re.match(r'^(\d+)[_\-]?', filename)
    return int(match.group(1)) if match else 0


async def scan_directory(db: AsyncSession, wiki_root: Optional[str] = None) -> dict:
    """
    Scan S3 bucket and sync to database files and folders.
    """
    from app.core.storage import list_files
    
    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
    
    s3_folder_paths: set[str] = set()
    s3_file_paths: set[str] = set()
    
    folder_cache: dict[str, Folder] = {}
    
    s3_objects = await list_files()
    
    folders_to_process = set()
    files_to_process = []
    
    for obj in s3_objects:
        key = obj['Key']
        if key.endswith('/'):
            continue
        parts = key.split('/')
        for i in range(1, len(parts)):
            folders_to_process.add('/'.join(parts[:i]))
        files_to_process.append(key)
        
    sorted_folders = sorted(list(folders_to_process), key=lambda x: len(x.split('/')))

    def build_full_path(key: str) -> str:
        parts = key.split('/')
        new_parts = []
        for part in parts:
            file_ext = Path(part).suffix.lower()
            if file_ext in ALLOWED_EXTENSIONS:
                new_parts.append(normalize_slug(part))
            else:
                new_parts.append(normalize_slug(part))
        return '/'.join(new_parts)

    async def get_or_create_folder(orig_key: str) -> Folder:
        full_path = build_full_path(orig_key)
        if full_path in folder_cache:
            return folder_cache[full_path]
            
        result = await db.execute(
            select(Folder).where(Folder.full_path == full_path)
        )
        existing = result.scalar_one_or_none()
        if existing:
            folder_cache[full_path] = existing
            return existing
            
        name = orig_key.split('/')[-1]
        parent_orig_key = '/'.join(orig_key.split('/')[:-1])
        parent_folder = None
        
        if parent_orig_key:
            parent_folder = await get_or_create_folder(parent_orig_key)
            
        folder = Folder(
            parent_id=parent_folder.id if parent_folder else None,
            title=normalize_title(name),
            slug=normalize_slug(name),
            full_path=full_path,
            sort_order=extract_sort_order(name),
        )
        db.add(folder)
        await db.flush()
        folder_cache[full_path] = folder
        stats["created"] += 1
        return folder

    # 1. Process Folders
    for orig_key in sorted_folders:
        full_path = build_full_path(orig_key)
        s3_folder_paths.add(full_path)
        await get_or_create_folder(orig_key)

    # 2. Process Files
    for orig_key in files_to_process:
        if not any(orig_key.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS):
            continue
            
        full_path = build_full_path(orig_key)
        s3_file_paths.add(full_path)
        
        result = await db.execute(
            select(File).where(File.full_path == full_path)
        )
        existing_file = result.scalar_one_or_none()
        
        # fallback based on old storage key if we want, but let's check basic
        if not existing_file:
            result = await db.execute(
                select(File).where(File.storage_key == orig_key)
            )
            existing_file = result.scalar_one_or_none()
            
        name = orig_key.split('/')[-1]
        parent_orig_key = '/'.join(orig_key.split('/')[:-1])
        parent_folder = None
        
        if parent_orig_key:
            parent_folder = await get_or_create_folder(parent_orig_key)
            
        if existing_file:
            updated = False
            if existing_file.storage_key != orig_key:
                existing_file.storage_key = orig_key
                updated = True
            if existing_file.full_path != full_path:
                existing_file.full_path = full_path
                existing_file.slug = normalize_slug(name)
                existing_file.title = normalize_title(name)
                existing_file.folder_id = parent_folder.id if parent_folder else None
                updated = True
                
            if updated:
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            file_obj = File(
                folder_id=parent_folder.id if parent_folder else None,
                title=normalize_title(name),
                slug=normalize_slug(name),
                full_path=full_path,
                storage_key=orig_key,
                sort_order=extract_sort_order(name),
            )
            db.add(file_obj)
            stats["created"] += 1

    # Delete missing folders and files
    files_result = await db.execute(select(File))
    all_files = files_result.scalars().all()
    for f in all_files:
        if f.full_path not in s3_file_paths:
            await db.delete(f)
            stats["deleted"] += 1
            
    folders_result = await db.execute(select(Folder))
    all_folders = folders_result.scalars().all()
    for f in all_folders:
        if f.full_path not in s3_folder_paths:
            await db.delete(f)
            stats["deleted"] += 1
            
    await db.commit()
    
    print(f"Scan complete: {stats['created']} created, {stats['updated']} updated, "
          f"{stats['deleted']} deleted, {stats['skipped']} unchanged")
          
    return stats
