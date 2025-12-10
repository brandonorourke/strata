# strata_core/db.py
import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from strata_core.settings import DATABASE_URL


engine = create_async_engine(
    DATABASE_URL,
    echo=False,            # can set True for debugging
    future=True,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

Base = declarative_base()


async def get_db() -> AsyncSession:
    """
    FastAPI-style dependency / generic helper for getting a session.
    Use in APIs or CLI tools.
    """
    async with AsyncSessionLocal() as session:
        yield session
