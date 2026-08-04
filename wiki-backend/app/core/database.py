from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings

# Create async engine for normal operations
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency for getting database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def check_and_create_database() -> bool:
    """
    Check if the database exists, create it if not.
    Returns True if database exists or was created successfully.
    """
    from sqlalchemy_utils import database_exists, create_database

    sync_url = settings.DATABASE_URL_SYNC

    try:
        if not database_exists(sync_url):
            print(f"Database '{settings.DB_NAME}' does not exist. Creating...")
            create_database(sync_url)
            print(f"Database '{settings.DB_NAME}' created successfully.")
            return True
        else:
            print(f"Database '{settings.DB_NAME}' already exists.")
            return True
    except Exception as e:
        print(f"Error checking/creating database: {e}")
        # Try alternative method using raw SQL
        try:
            admin_engine = create_engine(settings.DATABASE_URL_ADMIN, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                # Check if database exists
                result = conn.execute(
                    text(f"SELECT 1 FROM pg_database WHERE datname = '{settings.DB_NAME}'")
                )
                if not result.fetchone():
                    conn.execute(text(f'CREATE DATABASE "{settings.DB_NAME}"'))
                    print(f"Database '{settings.DB_NAME}' created successfully.")
                else:
                    print(f"Database '{settings.DB_NAME}' already exists.")
            admin_engine.dispose()
            return True
        except Exception as e2:
            print(f"Failed to create database: {e2}")
            return False


async def verify_connection() -> bool:
    """Verify database connection is working."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            print("Database connection verified successfully.")
            return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


async def init_db():
    """Initialize database tables."""
    # Import models to register them with Base
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables initialized.")

    # Seed default admin user if no users exist
    from sqlalchemy import select
    from app.core.security import get_password_hash
    import os

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(models.User).limit(1))
            user = result.scalars().first()
            if not user:
                print("No users found. Seeding default administrator...")
                admin_username = os.getenv("ADMIN_USERNAME", "admin")
                admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

                hashed_pw = get_password_hash(admin_password)
                default_admin = models.User(
                    username=admin_username,
                    hashed_password=hashed_pw,
                    role="admin",
                    is_active=True
                )
                session.add(default_admin)
                await session.commit()
                print(f"Default admin user '{admin_username}' seeded successfully.")
            else:
                print("Database already contains users. Seeding skipped.")
        except Exception as e:
            print(f"Failed to seed default admin: {e}")
            await session.rollback()
