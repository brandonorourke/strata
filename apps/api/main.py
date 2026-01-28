# apps/api/main.py

from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle, ExtractedEvent

app = FastAPI(title="Strata UI")
templates = Jinja2Templates(directory="apps/api/templates")


@app.get("/")
async def list_articles(request: Request, limit: int = 500):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(NewsArticle)
            .options(
                selectinload(NewsArticle.extracted_events).selectinload(
                    ExtractedEvent.entity
                )
            )
            .order_by(NewsArticle.published_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        articles = list(result.scalars().all())

    return templates.TemplateResponse(
        "articles.html",
        {"request": request, "articles": articles},
    )


@app.get("/articles/{article_id}")
async def article_detail(request: Request, article_id: int):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(NewsArticle)
            .options(
                selectinload(NewsArticle.extracted_events).selectinload(
                    ExtractedEvent.entity
                )
            )
            .where(NewsArticle.id == article_id)
        )
        result = await session.execute(stmt)
        article = result.scalar_one_or_none()

    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    return templates.TemplateResponse(
        "article_detail.html",
        {"request": request, "article": article},
    )
