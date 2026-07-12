from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
)

from sqlalchemy.orm import sessionmaker

from app.core.config import settings

if not settings.DATABASE_URL:
    # Keep app startup healthy when SQL DB is not part of the active runtime path.
    # If any endpoint starts depending on get_db(), it fails with a clear action.
    engine = None
    AsyncSessionLocal = None
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=True,
    )

    AsyncSessionLocal = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db():
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set DATABASE_URL in .env before using SQL database features."
        )
    async with AsyncSessionLocal() as session:
        yield session
