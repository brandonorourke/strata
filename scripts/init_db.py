import asyncio

from strata_core.db import engine, Base
from strata_core import models  # noqa: F401  <-- ensure models are imported


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(init_db())
