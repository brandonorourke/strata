from dotenv import load_dotenv
load_dotenv()

import os

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in the environment or .env")  # Crash fast if missing

if DATABASE_URL.startswith("postgresql://"):
    # Hosted Postgres add-ons (Railway, Heroku, etc.) inject plain postgresql:// URLs,
    # but the async engine needs the asyncpg driver suffix.
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ENV = os.getenv("ENV")
