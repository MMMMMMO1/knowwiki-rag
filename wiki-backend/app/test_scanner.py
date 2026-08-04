"""
Test script for scanner functionality.
Run with: uv run python -m app.test_scanner
"""

import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, init_db
from app.scanner import scan_directory
from app.models import File, Folder


async def main():
    print("=" * 50)
    print("Wiki Backend - Scanner Test")
    print("=" * 50)

    # 初始化数据库表，确保扫描器写入的 folders/files 表存在。
    print("\n[1/3] Initializing database tables...")
    await init_db()

    # 执行扫描同步，将对象存储中的目录和文件映射到数据库。
    print("\n[2/3] Running directory scanner...")
    async with AsyncSessionLocal() as db:
        stats = await scan_directory(db)
        print(f"\nScan Stats: {stats}")

    # 分别读取当前模型中的文件夹和文件，避免引用早期已移除的 Node 模型。
    print("\n[3/3] Verifying scanned folders and files...")
    async with AsyncSessionLocal() as db:
        folders_result = await db.execute(select(Folder).order_by(Folder.full_path))
        files_result = await db.execute(select(File).order_by(File.full_path))
        folders = folders_result.scalars().all()
        files = files_result.scalars().all()
        
        print(f"\nFound {len(folders)} folders and {len(files)} files in database:\n")
        for folder in folders:
            indent = "  " * folder.full_path.count("/")
            print(f"{indent}📁 {folder.title} ({folder.full_path})")

        for file_obj in files:
            indent = "  " * file_obj.full_path.count("/")
            print(f"{indent}📄 {file_obj.title} ({file_obj.full_path})")
            print(f"{indent}   └─ storage_key: {file_obj.storage_key}")

    print("\n" + "=" * 50)
    print("✅ Scanner test complete!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
