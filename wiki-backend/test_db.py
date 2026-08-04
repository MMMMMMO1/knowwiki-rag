"""
Test script for database connection and scanner functionality.
Run with: uv run python -m app.test_db
"""

import asyncio
from app.core.database import check_and_create_database, verify_connection, init_db
from app.core.config import settings


async def main():
    print("=" * 50)
    print("Wiki Backend - Database Test")
    print("=" * 50)
    print(f"\nDatabase Settings:")
    print(f"  Host: {settings.DB_HOST}")
    print(f"  Port: {settings.DB_PORT}")
    print(f"  User: {settings.DB_USER}")
    print(f"  Database: {settings.DB_NAME}")
    print()

    # Step 1: Check and create database if not exists
    print("[1/3] Checking database existence...")
    if not check_and_create_database():
        print("❌ Failed to check/create database")
        return

    # Step 2: Verify connection
    print("\n[2/3] Verifying database connection...")
    if not await verify_connection():
        print("❌ Database connection failed")
        return

    # Step 3: Initialize tables
    print("\n[3/3] Initializing database tables...")
    await init_db()

    print("\n" + "=" * 50)
    print("✅ All database tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
