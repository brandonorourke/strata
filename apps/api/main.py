# apps/api/main.py

from datetime import datetime, timedelta, timezone, date

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from strata_core.db import AsyncSessionLocal
from strata_core.models import (
    NewsArticle,
    ExtractedEvent,
    CanonicalEntity,
    EntityLink,
    ArticleDomain,
    ExtractedEntity,
    IcfsFiling,
    IcfsPleadingAndComment,
    IcfsPublicNotice,
    IcfsCanonicalEntity,
)

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/admin")
async def admin_home(request: Request):
    return templates.TemplateResponse(
        "admin_home.html",
        {"request": request},
    )


@app.get("/admin/stats")
async def admin_stats(request: Request):
    now = datetime.now(timezone.utc)
    day_1 = now - timedelta(days=1)
    day_7 = now - timedelta(days=7)
    day_30 = now - timedelta(days=30)

    async with AsyncSessionLocal() as session:
        total_stmt = select(func.count()).select_from(NewsArticle)
        total = int((await session.execute(total_stmt)).scalar() or 0)

        last_24h = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.published_at >= day_1)
        )).scalar() or 0)

        last_7d = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.published_at >= day_7)
        )).scalar() or 0)

        last_30d = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.published_at >= day_30)
        )).scalar() or 0)

        with_raw_html = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.raw_html.is_not(None))
        )).scalar() or 0)

        with_clean_text = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.clean_text.is_not(None))
        )).scalar() or 0)

        with_llm_raw = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.llm_raw.is_not(None))
        )).scalar() or 0)

        with_entities = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.entities_extracted_at.is_not(None))
        )).scalar() or 0)

        with_domains = int((await session.execute(
            select(func.count()).select_from(NewsArticle).where(NewsArticle.domains_extracted_at.is_not(None))
        )).scalar() or 0)

    def pct(value: int) -> float:
        if total == 0:
            return 0.0
        return round((value / total) * 100, 1)

    stats = {
        "total": total,
        "last_24h": last_24h,
        "last_7d": last_7d,
        "last_30d": last_30d,
        "with_raw_html": with_raw_html,
        "pct_raw_html": pct(with_raw_html),
        "with_clean_text": with_clean_text,
        "pct_clean_text": pct(with_clean_text),
        "with_llm_raw": with_llm_raw,
        "pct_llm_raw": pct(with_llm_raw),
        "with_entities": with_entities,
        "pct_entities": pct(with_entities),
        "with_domains": with_domains,
        "pct_domains": pct(with_domains),
    }

    return templates.TemplateResponse(
        "admin_stats.html",
        {"request": request, "stats": stats},
    )


@app.get("/admin/articles")
async def list_articles(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > 200:
        page_size = 200

    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(NewsArticle)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        stmt = (
            select(NewsArticle)
            .options(
                selectinload(NewsArticle.extracted_events).selectinload(
                    ExtractedEvent.entity
                )
            )
            .order_by(NewsArticle.published_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        articles = list(result.scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "articles.html",
        {
            "request": request,
            "articles": articles,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/admin/articles/{article_id}")
async def article_detail(request: Request, article_id: int):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(NewsArticle)
            .options(
                selectinload(NewsArticle.extracted_events).selectinload(
                    ExtractedEvent.entity
                ),
                selectinload(NewsArticle.article_domains),
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


@app.get("/admin/articles/{article_id}/raw", response_class=HTMLResponse)
async def article_raw_html(article_id: int):
    async with AsyncSessionLocal() as session:
        stmt = select(NewsArticle).where(NewsArticle.id == article_id)
        result = await session.execute(stmt)
        article = result.scalar_one_or_none()

    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if not article.raw_html:
        raise HTTPException(status_code=404, detail="No raw_html stored")

    return HTMLResponse(content=article.raw_html)


_ICFS_BASE_URL = "https://fccprod.servicenowservices.com"


def _icfs_filing_citation_url(filing: IcfsFiling) -> str | None:
    if not filing.file_number:
        return None
    return f"{_ICFS_BASE_URL}/icfs?id=ibfs_application_summary&number={filing.file_number}"


def _icfs_pleading_citation_url(pleading: IcfsPleadingAndComment) -> str:
    return f"{_ICFS_BASE_URL}/icfs?id=ibfs_pc_summary&sys_id={pleading.source_sys_id}"


@app.get("/admin/icfs")
async def icfs_home(request: Request):
    return templates.TemplateResponse("icfs_home.html", {"request": request})


@app.get("/admin/icfs/canonicals")
async def list_icfs_canonicals(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > 200:
        page_size = 200

    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(IcfsCanonicalEntity)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        mention_count = func.count(ExtractedEntity.id).label("mention_count")
        stmt = (
            select(IcfsCanonicalEntity, mention_count)
            .outerjoin(ExtractedEntity, ExtractedEntity.icfs_canonical_entity_id == IcfsCanonicalEntity.id)
            .group_by(IcfsCanonicalEntity.id)
            .order_by(IcfsCanonicalEntity.last_seen_at.desc().nullslast())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        canonicals = list(result.all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "icfs_canonicals.html",
        {
            "request": request,
            "canonicals": canonicals,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/admin/icfs/filings")
async def list_icfs_filings(request: Request, page: int = 1, page_size: int = 50, q: str = ""):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > 200:
        page_size = 200

    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        filters = []
        if q:
            filters.append(IcfsFiling.applicant_name.ilike(f"%{q}%"))

        count_stmt = select(func.count()).select_from(IcfsFiling).where(*filters)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        stmt = (
            select(IcfsFiling)
            .options(selectinload(IcfsFiling.extracted_events))
            .where(*filters)
            .order_by(IcfsFiling.submission_date.desc().nullslast(), IcfsFiling.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        filings = list(result.scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "icfs_filings.html",
        {
            "request": request,
            "filings": filings,
            "citation_url": _icfs_filing_citation_url,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "q": q,
        },
    )


@app.get("/admin/icfs/pleadings")
async def list_icfs_pleadings(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > 200:
        page_size = 200

    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(IcfsPleadingAndComment)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        stmt = (
            select(IcfsPleadingAndComment)
            .options(selectinload(IcfsPleadingAndComment.extracted_events))
            .order_by(IcfsPleadingAndComment.sys_created_on.desc().nullslast(), IcfsPleadingAndComment.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        pleadings = list(result.scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "icfs_pleadings.html",
        {
            "request": request,
            "pleadings": pleadings,
            "citation_url": _icfs_pleading_citation_url,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/admin/icfs/notices")
async def list_icfs_notices(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > 200:
        page_size = 200

    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(IcfsPublicNotice)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        stmt = (
            select(IcfsPublicNotice)
            .order_by(IcfsPublicNotice.public_notice_release_date.desc().nullslast(), IcfsPublicNotice.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        notices = list(result.scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "icfs_notices.html",
        {
            "request": request,
            "notices": notices,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/admin/icfs/notices/{notice_id}")
async def icfs_notice_detail(request: Request, notice_id: int):
    async with AsyncSessionLocal() as session:
        notice = await session.get(IcfsPublicNotice, notice_id)
        if notice is None:
            raise HTTPException(status_code=404, detail="Notice not found")

        stmt = (
            select(ExtractedEvent, ExtractedEntity)
            .join(ExtractedEntity, ExtractedEvent.entity_id == ExtractedEntity.id)
            .where(ExtractedEvent.source_type == "icfs_notice")
            .where(ExtractedEvent.source_id == notice_id)
            .order_by(ExtractedEntity.extracted_name)
        )
        rows = list((await session.execute(stmt)).all())
        entities = [{"entity": e, "event": ev} for ev, e in rows]

    return templates.TemplateResponse(
        "icfs_notice_detail.html",
        {"request": request, "notice": notice, "entities": entities},
    )


@app.get("/admin/icfs/signals")
async def icfs_signals(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        count_stmt = (
            select(func.count())
            .select_from(ExtractedEvent)
            .where(ExtractedEvent.source_type == "icfs_notice")
            .where(ExtractedEvent.signal_tier == "signal")
        )
        total = int((await session.execute(count_stmt)).scalar() or 0)

        stmt = (
            select(ExtractedEvent, ExtractedEntity, IcfsPublicNotice)
            .join(ExtractedEntity, ExtractedEvent.entity_id == ExtractedEntity.id)
            .join(
                IcfsPublicNotice,
                and_(
                    ExtractedEvent.source_type == "icfs_notice",
                    ExtractedEvent.source_id == IcfsPublicNotice.id,
                ),
            )
            .where(ExtractedEvent.source_type == "icfs_notice")
            .where(ExtractedEvent.signal_tier == "signal")
            .order_by(IcfsPublicNotice.public_notice_release_date.desc().nullslast())
            .offset(offset)
            .limit(page_size)
        )
        rows = list((await session.execute(stmt)).all())
        events = [{"event": ev, "entity": e, "notice": n} for ev, e, n in rows]

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "icfs_signals.html",
        {
            "request": request,
            "events": events,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/admin/icfs/entity/{canonical_id}")
async def icfs_entity_timeline(request: Request, canonical_id: int):
    async with AsyncSessionLocal() as session:
        canonical = await session.get(IcfsCanonicalEntity, canonical_id)
        if canonical is None:
            raise HTTPException(status_code=404, detail="Entity not found")

        # All extracted_entities for this canonical, across all source types
        entity_stmt = (
            select(ExtractedEntity)
            .where(ExtractedEntity.icfs_canonical_entity_id == canonical_id)
        )
        extracted = list((await session.execute(entity_stmt)).scalars().all())
        entity_ids = [e.id for e in extracted]

        if not entity_ids:
            return templates.TemplateResponse(
                "icfs_entity_timeline.html",
                {"request": request, "canonical": canonical, "timeline": []},
            )

        # All events for those entities, with notice + filing joins for label/action data
        event_stmt = (
            select(ExtractedEvent, ExtractedEntity, IcfsPublicNotice, IcfsFiling)
            .join(ExtractedEntity, ExtractedEvent.entity_id == ExtractedEntity.id)
            .outerjoin(
                IcfsPublicNotice,
                and_(
                    ExtractedEvent.source_type == "icfs_notice",
                    ExtractedEvent.source_id == IcfsPublicNotice.id,
                ),
            )
            .outerjoin(
                IcfsFiling,
                and_(
                    ExtractedEvent.source_type == "icfs_filing",
                    ExtractedEvent.source_id == IcfsFiling.id,
                ),
            )
            .where(ExtractedEvent.entity_id.in_(entity_ids))
            .order_by(ExtractedEvent.event_date.desc().nullslast(), ExtractedEvent.id.desc())
        )
        rows = list((await session.execute(event_stmt)).all())

        timeline = []
        for ev, e, notice, filing in rows:
            if ev.source_type == "icfs_filing":
                card_type = "action" if (filing and filing.action) else "filing"
                action_label = filing.action if filing else None
            elif ev.source_type == "icfs_notice":
                card_type = "notice"
                action_label = None
            else:
                card_type = "pleading"
                action_label = None
            timeline.append({
                "event": ev,
                "entity": e,
                "notice": notice,
                "filing": filing,
                "card_type": card_type,
                "action_label": action_label,
            })

        counts = {
            "notice": sum(1 for r in timeline if r["card_type"] == "notice"),
            "action": sum(1 for r in timeline if r["card_type"] == "action"),
            "filing": sum(1 for r in timeline if r["card_type"] == "filing"),
            "pleading": sum(1 for r in timeline if r["card_type"] == "pleading"),
            "signal": sum(1 for r in timeline if r["event"].signal_tier == "signal"),
        }

    return templates.TemplateResponse(
        "icfs_entity_timeline.html",
        {
            "request": request,
            "canonical": canonical,
            "timeline": timeline,
            "counts": counts,
        },
    )


def _week_ending_sunday(d: date) -> date:
    # Python weekday(): Monday=0 ... Sunday=6
    return d + timedelta(days=(6 - d.weekday()))


@app.get("/screen/weekly")
async def most_changed_weekly(request: Request, months: int = 6, limit: int = 20):
    if months < 1:
        months = 1
    if months > 24:
        months = 24

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=months * 30)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(ExtractedEntity, ExtractedEvent, NewsArticle)
            .join(ExtractedEvent, ExtractedEvent.entity_id == ExtractedEntity.id)
            .join(
                NewsArticle,
                and_(ExtractedEvent.source_type == "news_article", NewsArticle.id == ExtractedEvent.source_id),
            )
            .where(NewsArticle.published_at >= window_start)
            .where(ExtractedEntity.entity_type.in_(["operating_company", "financial_sponsor", "lender"]))
        )
        result = await session.execute(stmt)
        rows = result.all()

    weekly = {}
    for entity, event, article in rows:
        if not entity.legal_name_normalized or not entity.entity_type:
            continue
        if article.published_at is None:
            continue

        week_end = _week_ending_sunday(article.published_at.date())
        week_bucket = weekly.setdefault(week_end, {})

        cluster_key = f"{entity.legal_name_normalized}::{entity.entity_type}"
        bucket = week_bucket.setdefault(
            cluster_key,
            {
                "cluster_key": cluster_key,
                "legal_name": entity.legal_name_normalized,
                "entity_type": entity.entity_type,
                "display_name": entity.extracted_name,
                "events": [],
            },
        )

        if bucket["display_name"] is None:
            bucket["display_name"] = entity.extracted_name

        days_since = (week_end - article.published_at.date()).days
        if days_since < 0:
            days_since = 0
        if days_since > 7:
            days_since = 7

        recency_weight = 1.0 - (0.75 / 7.0) * days_since
        if recency_weight < 0.25:
            recency_weight = 0.25

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

    weekly_rows = []
    for week_end, clusters in weekly.items():
        ranked = []
        for bucket in clusters.values():
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
            source_ids = {item["article"].source for item in kept_events if item.get("article")}

            ranked.append(
                {
                    "cluster_key": bucket["cluster_key"],
                    "legal_name": bucket["legal_name"],
                    "entity_type": bucket["entity_type"],
                    "display_name": bucket["display_name"],
                    "score": entity_score,
                    "events": kept_events[:3],
                    "claims_count": len(kept_events),
                    "sources_count": len(source_ids),
                }
            )

        ranked.sort(key=lambda x: x["score"], reverse=True)
        weekly_rows.append(
            {
                "week_end": week_end,
                "rows": ranked[:limit],
            }
        )

    weekly_rows.sort(key=lambda x: x["week_end"], reverse=True)

    return templates.TemplateResponse(
        "screen_weekly.html",
        {
            "request": request,
            "weeks": weekly_rows,
            "months": months,
        },
    )


@app.get("/screen/cluster")
async def cluster_evidence(
    request: Request,
    legal_name: str,
    entity_type: str,
    days: int = 30,
    all_time: int = 0,
    week_end: str | None = None,
):
    now = datetime.now(timezone.utc)
    scoring_anchor = now
    scoring_week_end = None
    if week_end:
        try:
            scoring_week_end = datetime.strptime(week_end, "%Y-%m-%d").date()
        except ValueError:
            scoring_week_end = None
    window_start = now - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(ExtractedEvent, NewsArticle, ExtractedEntity)
            .join(ExtractedEntity, ExtractedEntity.id == ExtractedEvent.entity_id)
            .join(
                NewsArticle,
                and_(ExtractedEvent.source_type == "news_article", NewsArticle.id == ExtractedEvent.source_id),
            )
            .where(ExtractedEntity.legal_name_normalized == legal_name)
            .where(ExtractedEntity.entity_type == entity_type)
            .order_by(NewsArticle.published_at.desc())
        )
        if not all_time:
            stmt = stmt.where(NewsArticle.published_at >= window_start)

        result = await session.execute(stmt)
        rows = list(result.all())

    evidence_rows = []
    for event, article, entity in rows:
        published_at = article.published_at
        days_since = None
        in_score_window = False
        recency_weight = None
        if published_at is not None:
            if scoring_week_end:
                days_since = (scoring_week_end - published_at.date()).days
            else:
                days_since = int((scoring_anchor - published_at).total_seconds() // 86400)
            if days_since is not None and days_since < 0:
                days_since = 0
            if days_since is not None and days_since <= 7:
                in_score_window = True
                recency_weight = 1.0 - (0.75 / 7.0) * days_since
                if recency_weight < 0.25:
                    recency_weight = 0.25
                if recency_weight > 1.0:
                    recency_weight = 1.0

        event_type = event.event_type or "other"
        type_weight = _EVENT_TYPE_WEIGHTS.get(event_type, 1)

        confidence = event.confidence if event.confidence is not None else 1.0
        if confidence < 0.0:
            confidence = 0.0
        if confidence > 1.0:
            confidence = 1.0

        if in_score_window and recency_weight is not None:
            event_score = type_weight * recency_weight * confidence
        else:
            event_score = 0.0

        evidence_rows.append(
            {
                "event": event,
                "article": article,
                "entity": entity,
                "event_type": event_type,
                "type_weight": type_weight,
                "days_since": days_since,
                "recency_weight": recency_weight,
                "confidence": confidence,
                "event_score": event_score,
                "in_score_window": in_score_window,
            }
        )

    return templates.TemplateResponse(
        "cluster_evidence.html",
        {
            "request": request,
            "legal_name": legal_name,
            "entity_type": entity_type,
            "rows": evidence_rows,
            "days": days,
            "all_time": all_time,
            "week_end": scoring_week_end,
        },
    )


@app.get("/admin/canonicals")
async def list_canonicals(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    if page_size > 200:
        page_size = 200

    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(CanonicalEntity)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        stmt = (
            select(CanonicalEntity)
            .options(
                selectinload(CanonicalEntity.entity_links).selectinload(
                    EntityLink.extracted_entity
                )
            )
            .order_by(CanonicalEntity.id.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        canonicals = list(result.scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "canonicals.html",
        {
            "request": request,
            "canonicals": canonicals,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/admin/canonicals/{canonical_id}")
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

        domains_stmt = (
            select(ArticleDomain.domain, func.count(ArticleDomain.domain))
            .join(
                ExtractedEntity,
                and_(
                    ExtractedEntity.source_type == "news_article",
                    ExtractedEntity.source_id == ArticleDomain.article_id,
                ),
            )
            .join(EntityLink, EntityLink.extracted_entity_id == ExtractedEntity.id)
            .where(EntityLink.canonical_entity_id == canonical_id)
            .group_by(ArticleDomain.domain)
            .order_by(func.count(ArticleDomain.domain).desc())
        )
        domains_result = await session.execute(domains_stmt)
        candidate_domains = list(domains_result.all())

        events_stmt = (
            select(ExtractedEvent, NewsArticle)
            .join(EntityLink, EntityLink.extracted_entity_id == ExtractedEvent.entity_id)
            .join(
                NewsArticle,
                and_(ExtractedEvent.source_type == "news_article", NewsArticle.id == ExtractedEvent.source_id),
            )
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
            "candidate_domains": candidate_domains,
        },
    )


@app.post("/admin/canonicals/{canonical_id}/confirm-domain")
async def confirm_canonical_domain(request: Request, canonical_id: int, domain: str = Form(...)):
    domain = domain.strip().lower()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain is required")

    async with AsyncSessionLocal() as session:
        stmt = select(CanonicalEntity).where(CanonicalEntity.id == canonical_id)
        result = await session.execute(stmt)
        canonical = result.scalar_one_or_none()
        if canonical is None:
            raise HTTPException(status_code=404, detail="Canonical not found")

        canonical.confirmed_domain = domain
        try:
            await session.commit()
            await session.refresh(canonical)
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    return templates.TemplateResponse(
        "canonical_confirmed.html",
        {"request": request, "canonical": canonical},
    )
