# apps/api/main.py

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from strata_core.db import AsyncSessionLocal
from strata_core.models import NewsArticle, ExtractedEvent, CanonicalEntity, EntityLink

app = FastAPI(title="Strata UI")
templates = Jinja2Templates(directory="apps/api/templates")

_EVENT_TYPE_WEIGHTS = {
    "bankruptcy": 6,
    "legal_action": 5,
    "regulatory": 5,
    "layoffs": 4,
    "leadership_change": 3,
    "disposition": 3,
    "financing": 2,
    "acquisition": 2,
    "mna_transaction": 2,
    "performance_update": 1,
    "other": 1,
}


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


@app.get("/screen")
async def most_changed(request: Request, days: int = 60, limit: int = 50):
    print(f"Generating most changed screen for last {days} days")
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(CanonicalEntity, ExtractedEvent, NewsArticle)
            .join(EntityLink, EntityLink.canonical_entity_id == CanonicalEntity.id)
            .join(ExtractedEvent, ExtractedEvent.entity_id == EntityLink.extracted_entity_id)
            .join(NewsArticle, NewsArticle.id == ExtractedEvent.article_id)
            .where(NewsArticle.published_at >= window_start)
        )
        result = await session.execute(stmt)
        rows = result.all()

    canonicals = {}
    for canonical, event, article in rows:
        bucket = canonicals.setdefault(
            canonical.id,
            {
                "canonical": canonical,
                "events": [],
            },
        )

        published_at = article.published_at
        if published_at is None:
            continue

        days_since = int((now - published_at).total_seconds() // 86400)
        if days_since < 0:
            days_since = 0

        recency_weight = 1.0 - (0.75 / 30.0) * days_since
        if recency_weight < 0.25:
            recency_weight = 0.25
        if recency_weight > 1.0:
            recency_weight = 1.0

        recency_weight = 1

        event_type = event.event_type or "other"
        type_weight = _EVENT_TYPE_WEIGHTS.get(event_type, 1)

        confidence = event.confidence if event.confidence is not None else 1.0
        if confidence < 0.0:
            confidence = 0.0
        if confidence > 1.0:
            confidence = 1.0

        event_score = type_weight * recency_weight * confidence

        bucket["events"].append(
            {
                "event": event,
                "article": article,
                "event_type": event_type,
                "event_score": event_score,
            }
        )

    ranked = []
    for bucket in canonicals.values():
        canonical = bucket["canonical"]
        events = bucket["events"]

        per_type = {}
        for item in events:
            per_type.setdefault(item["event_type"], []).append(item)

        kept_events = []
        for items in per_type.values():
            items.sort(key=lambda x: x["event_score"], reverse=True)
            kept_events.extend(items[:2])

        kept_events.sort(key=lambda x: x["event_score"], reverse=True)

        entity_score = sum(item["event_score"] for item in kept_events)
        if canonical.status == "provisional":
            entity_score *= 0.8

        source_ids = {item["article"].id for item in kept_events if item.get("article")}

        ranked.append(
            {
                "canonical": canonical,
                "score": entity_score,
                "events": kept_events[:3],
                "claims_count": len(kept_events),
                "sources_count": len(source_ids),
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return templates.TemplateResponse(
        "screen.html",
        {
            "request": request,
            "rows": ranked[:limit],
            "days": days,
        },
    )


@app.get("/canonicals")
async def list_canonicals(request: Request, limit: int = 100):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(CanonicalEntity)
            .options(
                selectinload(CanonicalEntity.entity_links).selectinload(
                    EntityLink.extracted_entity
                )
            )
            .order_by(CanonicalEntity.id.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        canonicals = list(result.scalars().all())

    return templates.TemplateResponse(
        "canonicals.html",
        {"request": request, "canonicals": canonicals},
    )


@app.get("/canonicals/{canonical_id}")
async def canonical_detail(request: Request, canonical_id: int, limit: int = 200):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(CanonicalEntity)
            .options(
                selectinload(CanonicalEntity.entity_links).selectinload(
                    EntityLink.extracted_entity
                )
            )
            .where(CanonicalEntity.id == canonical_id)
        )
        result = await session.execute(stmt)
        canonical = result.scalar_one_or_none()

        if canonical is None:
            raise HTTPException(status_code=404, detail="Canonical not found")

        events_stmt = (
            select(ExtractedEvent, NewsArticle)
            .join(EntityLink, EntityLink.extracted_entity_id == ExtractedEvent.entity_id)
            .join(NewsArticle, NewsArticle.id == ExtractedEvent.article_id)
            .where(EntityLink.canonical_entity_id == canonical_id)
            .order_by(NewsArticle.published_at.desc())
            .limit(limit)
        )
        events_result = await session.execute(events_stmt)
        events = list(events_result.all())

    return templates.TemplateResponse(
        "canonical_detail.html",
        {
            "request": request,
            "canonical": canonical,
            "events": events,
        },
    )
