# apps/api/main.py

from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
import json
import re

ET = ZoneInfo("America/New_York")   # SAM/DoW timestamps display in true Eastern (EDT/EST)

import httpx

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, or_, cast, text, bindparam, String, Integer, Text
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
    IcfsFilingActionHistory,
    DowContractRelease,
    DowAward,
    SamAwardNotice,
    UsaspendingAward,
    IdiqRecipient,
    Company,
)

app = FastAPI(title="Strata UI")
templates = Jinja2Templates(directory="apps/api/templates")
def _pretty_json(v):
    if isinstance(v, dict):
        v = {k: (json.loads(val) if isinstance(val, str) and val.startswith(('{', '[')) else val)
             for k, val in v.items()}
    return json.dumps(v, indent=2, default=str)

templates.env.filters["pretty_json"] = _pretty_json

def _fmt_dollars(cents):
    if not cents:
        return "—"
    b = cents / 100
    if b >= 1_000_000_000:
        return f"${b/1e9:.1f}B"
    if b >= 1_000_000:
        return f"${b/1e6:.1f}M"
    if b >= 1_000:
        return f"${b/1e3:.0f}K"
    return f"${b:,.0f}"

templates.env.filters["fmt_dollars"] = _fmt_dollars

def _fmt_usd(d):
    # like _fmt_dollars but for values already in DOLLARS (not cents) — usaspending_awards
    if d is None:
        return "—"
    d = float(d)
    if abs(d) >= 1e9:
        return f"${d/1e9:.2f}B"
    if abs(d) >= 1e6:
        return f"${d/1e6:.1f}M"
    if abs(d) >= 1e3:
        return f"${d/1e3:.0f}K"
    return f"${d:,.0f}"

templates.env.filters["fmt_usd"] = _fmt_usd

# ticker → display name. Interim map until the companies table (0048) lands; the
# watchlist index + /company page both read this so names live in one place.
DISPLAY_NAMES = {
    "VSAT": "Viasat", "AVAV": "AeroVironment", "KTOS": "Kratos",
    "MRCY": "Mercury Systems", "CMTL": "Comtech", "DRS": "Leonardo DRS",
    "LUNR": "Intuitive Machines", "RKLB": "Rocket Lab", "RDW": "Redwire",
    "BKSY": "BlackSky",
}

# Eponymy check for the UEI directory: does a recipient's name share a distinctive brand
# token with its parent company? Generic industry words are dropped so unrelated firms don't
# false-match (a random "Advanced Defense Systems" must NOT read as eponymous with Kratos).
# Non-eponymous + high awards = divestiture-stale stray to review before confirming.
_EPO_STOP = {
    "inc", "llc", "corp", "corporation", "company", "holding", "holdings", "systems",
    "system", "technologies", "technology", "group", "international", "intl", "the", "and",
    "ltd", "llp", "services", "solutions", "communications", "telecommunications", "defense",
    "security", "federal", "national", "laboratories", "labs", "operations", "division", "pbc",
}


def _epo_tokens(s):
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower())
            if t not in _EPO_STOP and len(t) > 2}


def _epo_roots(name, aliases, ticker):
    """Distinctive brand tokens for a company: official name + aliases, plus the ticker
    itself if it's 4+ chars (acronym brands like SAIC/CACI; short tickers are too collision-prone)."""
    roots = _epo_tokens(name)
    for a in (aliases or []):
        roots |= _epo_tokens(a)
    if ticker and len(ticker) >= 4:
        roots.add(ticker.lower())
    return roots


def _is_eponymous(recipient_name, roots):
    if not roots:
        return None
    return bool(roots & _epo_tokens(recipient_name))


# A recipient is flagged for a manual ownership check ("review") only when it's a
# non-eponymous candidate that is BOTH recently active and material — the divestiture-
# stale profile (e.g. ASRC Federal, sold by SAIC in 2023 but still doing ~$466M/yr, which
# USASpending still hangs off SAIC). Dormant or tiny strays (a single old award, like the
# 2011 Idaho Treatment Group JV) don't distort the footprint, so they are NOT flagged.
_REVIEW_RECENT_SINCE = date(2023, 1, 1)
_REVIEW_MATERIAL_USD = 50_000_000


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


@app.get("/proxy/pdf")
async def proxy_pdf(url: str):
    """Fetch a PDF from an external URL and serve it inline so it renders in-browser."""
    allowed_hosts = {"api-prod.fcc.gov", "docs.fcc.gov", "www.fcc.gov"}
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host not in allowed_hosts:
        raise HTTPException(status_code=400, detail="URL not allowed")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch PDF")

    return StreamingResponse(
        iter([resp.content]),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


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
    return templates.TemplateResponse("icfs_home.html", {"request": request, "title": "Strata - ICFS Home"})


@app.get("/admin/dow")
async def dow_home(request: Request):
    return RedirectResponse(url="/admin/dow/contracts", status_code=302)


@app.get("/admin/dow/contracts")
async def dow_contracts(request: Request, page: int = 1, page_size: int = 50):
    if page < 1:
        page = 1
    offset = (page - 1) * page_size
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count()).select_from(DowContractRelease))).scalar_one()
        releases = (await session.execute(
            select(DowContractRelease)
            .options(selectinload(DowContractRelease.awards))
            .order_by(DowContractRelease.release_date.desc().nullslast(), DowContractRelease.first_seen_at.desc())
            .offset(offset)
            .limit(page_size)
        )).scalars().all()
    total_pages = (total + page_size - 1) // page_size
    return templates.TemplateResponse("dow_contracts.html", {
        "request": request,
        "title": "Strata - DoW Contracts",
        "releases": releases,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    })


@app.get("/admin/sam")
async def list_sam_notices(request: Request, page: int = 1, page_size: int = 50, q: str = ""):
    """Raw SAM award-notice table (paged, awardee search). See ingest_sam_awards.py."""
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
            filters.append(or_(
                SamAwardNotice.awardee_name.ilike(f"%{q}%"),
                SamAwardNotice.piid.ilike(f"%{q}%"),
                SamAwardNotice.awardee_uei.ilike(f"%{q}%"),
            ))

        total = int((await session.execute(
            select(func.count()).select_from(SamAwardNotice).where(*filters)
        )).scalar() or 0)

        notices = list((await session.execute(
            select(SamAwardNotice)
            .where(*filters)
            .order_by(SamAwardNotice.posted_date.desc().nullslast(), SamAwardNotice.id.desc())
            .offset(offset)
            .limit(page_size)
        )).scalars().all())

    total_pages = max(1, (total + page_size - 1) // page_size)
    return templates.TemplateResponse("sam_notices.html", {
        "request": request,
        "title": "Strata - SAM Award Notices",
        "notices": notices,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "q": q,
        "et": ET,
    })


@app.get("/usaspending")
async def list_usaspending_awards(request: Request, page: int = 1, page_size: int = 100,
                                  q: str = "", uei: str = "", kind: str = ""):
    """Raw USASpending awards (manual pull-by-UEI). See apps/ingest/pull_usaspending.py.
    kind ∈ {idv, orders, standalone} filters vehicles / draws / standalone contracts."""
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 100
    if page_size > 500:
        page_size = 500
    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as session:
        filters = []
        if q:
            filters.append(or_(
                UsaspendingAward.recipient_name.ilike(f"%{q}%"),
                UsaspendingAward.award_id.ilike(f"%{q}%"),
                UsaspendingAward.recipient_uei.ilike(f"%{q}%"),
                UsaspendingAward.parent_award_id.ilike(f"%{q}%"),
                UsaspendingAward.description.ilike(f"%{q}%"),
            ))
        if uei:
            filters.append(UsaspendingAward.recipient_uei == uei)
        if kind == "idv":
            filters.append(UsaspendingAward.is_idv.is_(True))
        elif kind == "orders":
            filters.append(and_(UsaspendingAward.is_idv.is_(False),
                                UsaspendingAward.parent_award_id.isnot(None)))
        elif kind == "standalone":
            filters.append(and_(UsaspendingAward.is_idv.is_(False),
                                UsaspendingAward.parent_award_id.is_(None)))

        total = int((await session.execute(
            select(func.count()).select_from(UsaspendingAward).where(*filters)
        )).scalar() or 0)

        # money roll-up over the filtered set (undrawn = ceiling − obligated, floored at 0)
        oblig = func.coalesce(UsaspendingAward.total_obligation, UsaspendingAward.amount)
        sum_ceiling, sum_obligated, sum_undrawn, n_enriched = (await session.execute(
            select(
                func.coalesce(func.sum(UsaspendingAward.ceiling), 0),
                func.coalesce(func.sum(oblig), 0),
                func.coalesce(func.sum(func.greatest(UsaspendingAward.ceiling - oblig, 0)), 0),
                func.count().filter(UsaspendingAward.enriched_at.isnot(None)),
            ).where(*filters)
        )).one()

        awards = list((await session.execute(
            select(UsaspendingAward)
            .where(*filters)
            .order_by(UsaspendingAward.amount.desc().nullslast(), UsaspendingAward.id.desc())
            .offset(offset)
            .limit(page_size)
        )).scalars().all())

        # UEI family present in the table, for the filter dropdown
        ueis = list((await session.execute(
            select(UsaspendingAward.recipient_uei, UsaspendingAward.recipient_name,
                   func.count().label("n"))
            .group_by(UsaspendingAward.recipient_uei, UsaspendingAward.recipient_name)
            .order_by(func.count().desc())
        )).all())

    total_pages = max(1, (total + page_size - 1) // page_size)
    return templates.TemplateResponse("usaspending_awards.html", {
        "request": request,
        "title": "Strata - USASpending Awards",
        "awards": awards,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "q": q,
        "uei": uei,
        "kind": kind,
        "ueis": ueis,
        "sum_ceiling": sum_ceiling,
        "sum_obligated": sum_obligated,
        "sum_undrawn": sum_undrawn,
        "n_enriched": n_enriched,
    })


@app.get("/coverage")
async def coverage_index(request: Request, sort: str = "undrawn"):
    """Coverage grid — one row per confirmed watchlist company, each drilling into
    /company/{ticker}. Per-company summary reuses the /company computation (exclusive
    latent = single-award active undrawn; shared seats = active multi-award vehicles).
    Data-driven off idiq_recipients confirmed UEIs, so adding a company needs no nav edit."""
    today = date.today()
    async with AsyncSessionLocal() as session:
        pairs = (await session.execute(
            select(IdiqRecipient.uei, IdiqRecipient.ticker)
            .where(IdiqRecipient.mapping_status == "confirmed")
        )).all()
        uei_ticker = {u: t for u, t in pairs}
        ueis = list(uei_ticker.keys())
        rows = list((await session.execute(
            select(UsaspendingAward).where(UsaspendingAward.recipient_uei.in_(ueis))
        )).scalars().all()) if ueis else []

    def f(x):
        return float(x) if x is not None else 0.0

    by_ticker = {}
    for r in rows:
        t = uei_ticker.get(r.recipient_uei)
        if t:
            by_ticker.setdefault(t, []).append(r)

    companies = []
    for ticker in sorted(set(uei_ticker.values())):
        crows = by_ticker.get(ticker, [])
        vehicles = [r for r in crows if r.is_idv]
        orders   = [r for r in crows if (not r.is_idv) and r.parent_generated_id]

        drawn = {}
        for o in orders:
            slot = drawn.setdefault(o.parent_generated_id, {"amt": 0.0})
            slot["amt"] += f(o.amount)

        excl_latent = 0.0
        n_excl = n_shared = 0
        for v in vehicles:
            ceiling = f(v.ceiling)
            expiry  = v.last_order_date or v.end_date
            active  = (expiry is None) or (expiry >= today)
            if not active or ceiling <= 0:
                continue
            if v.is_multi_award:
                n_shared += 1
            else:
                n_excl += 1
                vd = drawn.get(v.generated_internal_id, {"amt": 0.0})["amt"]
                excl_latent += max(ceiling - vd, 0.0)

        last_draw = None
        n_draws_90 = 0
        for o in orders:
            od = o.date_signed or o.start_date
            if od:
                if last_draw is None or od > last_draw:
                    last_draw = od
                if (today - od).days <= 90:
                    n_draws_90 += 1

        companies.append({
            "ticker": ticker, "name": DISPLAY_NAMES.get(ticker, ticker),
            "exclusive_latent": excl_latent, "n_exclusive": n_excl, "n_shared": n_shared,
            "last_draw": last_draw, "n_draws_90": n_draws_90,
            "total_drawn": sum(d["amt"] for d in drawn.values()),
            "n_vehicles": len(vehicles), "n_awards": len(crows),
        })

    keyfns = {
        "undrawn": (lambda c: c["exclusive_latent"], True),
        "recent":  (lambda c: c["last_draw"] or date.min, True),
        "drawn":   (lambda c: c["total_drawn"], True),
        "name":    (lambda c: c["name"], False),
    }
    keyfn, rev = keyfns.get(sort, keyfns["undrawn"])
    companies.sort(key=keyfn, reverse=rev)

    totals = {
        "n_companies": len(companies),
        "excl_latent": sum(c["exclusive_latent"] for c in companies),
        "n_draws_90": sum(c["n_draws_90"] for c in companies),
    }
    return templates.TemplateResponse("coverage.html", {
        "request": request, "title": "Coverage — Federal Contracts",
        "companies": companies, "totals": totals, "sort": sort, "today": today,
    })


@app.get("/admin/idiq/recipients")
async def idiq_recipients_admin(request: Request):
    """Read-only view of the idiq_recipients UEI→ticker directory + mapping_status.
    This app has no auth, so it's VIEW-ONLY — curation still happens via SQL. Shows
    per-UEI award counts so divestiture-stale strays (wrong name + high awards) are spottable."""
    async with AsyncSessionLocal() as session:
        recs = list((await session.execute(
            select(IdiqRecipient).order_by(IdiqRecipient.ticker, IdiqRecipient.mapping_status)
        )).scalars().all())
        counts, recent_obl = {}, {}
        ueis = [r.uei for r in recs]
        if ueis:
            for u, c, ro in (await session.execute(
                select(UsaspendingAward.recipient_uei, func.count(),
                       func.sum(UsaspendingAward.total_obligation).filter(
                           UsaspendingAward.base_obligation_date >= _REVIEW_RECENT_SINCE))
                .where(UsaspendingAward.recipient_uei.in_(ueis))
                .group_by(UsaspendingAward.recipient_uei)
            )).all():
                counts[u] = c
                recent_obl[u] = float(ro or 0)
        # brand roots per ticker, from the canonical companies table (0048)
        roots_by_ticker = {
            c.ticker: _epo_roots(c.name, c.aliases, c.ticker)
            for c in (await session.execute(select(Company))).scalars().all()
            if c.ticker
        }

    recipients = []
    for r in recs:
        epo = _is_eponymous(r.recipient_name, roots_by_ticker.get(r.ticker, set()))
        ro = recent_obl.get(r.uei, 0.0)
        # the ownership-check flag: non-eponymous + candidate + recently active + material
        review = (r.mapping_status == "candidate" and epo is False
                  and ro >= _REVIEW_MATERIAL_USD)
        recipients.append({
            "ticker": r.ticker, "uei": r.uei, "name": r.recipient_name,
            "status": r.mapping_status, "seed_uei": r.seed_uei,
            "first_seen": r.first_seen_at, "awards": counts.get(r.uei, 0),
            "eponymous": epo, "recent_obl": ro, "review": review,
            "ov_verdict": r.ownership_verdict, "ov_source": r.ownership_source,
            "ov_rationale": r.ownership_rationale, "ov_as_of": r.ownership_as_of,
        })
    # flagged rows first, then by ticker/status/awards
    recipients.sort(key=lambda x: (not x["review"], x["ticker"] or "~", x["status"], -x["awards"]))

    summary = {
        "total": len(recipients),
        "tickers": len({x["ticker"] for x in recipients if x["ticker"]}),
        "confirmed": sum(1 for x in recipients if x["status"] == "confirmed"),
        "candidate": sum(1 for x in recipients if x["status"] == "candidate"),
        "excluded": sum(1 for x in recipients if x["status"] == "excluded"),
        # the review queue: non-eponymous candidates that are recently active + material
        "review": sum(1 for x in recipients if x["review"]),
    }
    return templates.TemplateResponse("idiq_recipients.html", {
        "request": request, "title": "IDIQ Recipients — UEI directory",
        "recipients": recipients, "summary": summary,
    })


@app.get("/company/{ticker}")
async def company_page(request: Request, ticker: str = "VSAT", show_expired: bool = False):
    """Clean, customer-facing single-company view (v1: Viasat). Position & capacity
    from usaspending_awards (USASpending, ~90-day lagged). Hero = exclusive undrawn
    (single-award, active vehicles); shared multi-award shown separately as seats."""
    ticker = (ticker or "VSAT").upper()
    today = date.today()
    display_name = DISPLAY_NAMES.get(ticker, ticker)

    async with AsyncSessionLocal() as session:
        # resolve the ticker's CONFIRMED UEIs from the directory, then filter awards by UEI
        ueis = list((await session.execute(
            select(IdiqRecipient.uei).where(
                IdiqRecipient.ticker == ticker,
                IdiqRecipient.mapping_status == "confirmed",
            )
        )).scalars().all())
        rows = list((await session.execute(
            select(UsaspendingAward).where(UsaspendingAward.recipient_uei.in_(ueis))
        )).scalars().all()) if ueis else []

    def f(x):
        return float(x) if x is not None else 0.0

    vehicles = [r for r in rows if r.is_idv]
    orders   = [r for r in rows if (not r.is_idv) and r.parent_generated_id]

    # drawn per vehicle = Σ of its child orders' amounts (search gives this; no enrich needed)
    drawn = {}
    for o in orders:
        slot = drawn.setdefault(o.parent_generated_id, {"amt": 0.0, "n": 0, "last": None})
        slot["amt"] += f(o.amount)
        slot["n"]   += 1
        od = o.date_signed or o.start_date
        if od and (slot["last"] is None or od > slot["last"]):
            slot["last"] = od

    veh = []
    for v in vehicles:
        d = drawn.get(v.generated_internal_id, {"amt": 0.0, "n": 0, "last": None})
        ceiling = f(v.ceiling)
        vdrawn  = d["amt"]
        undrawn = max(ceiling - vdrawn, 0.0)
        expiry  = v.last_order_date or v.end_date
        veh.append({
            "gid": v.generated_internal_id, "award_id": v.award_id,
            "program": v.program_acronym, "desc": v.description,
            "ceiling": ceiling, "drawn": vdrawn, "undrawn": undrawn,
            "pct": (vdrawn / ceiling) if ceiling > 0 else None,
            "expiry": expiry, "active": (expiry is None) or (expiry >= today),
            "is_multi": bool(v.is_multi_award), "n_orders": d["n"], "last_draw": d["last"],
            "funding": v.funding_sub_agency, "agency": v.awarding_sub_agency,
            "enriched": v.enriched_at is not None,
        })

    exclusive_veh = sorted([x for x in veh if not x["is_multi"]],
                           key=lambda x: (x["active"], x["undrawn"]), reverse=True)
    shared_veh    = sorted([x for x in veh if x["is_multi"]],
                           key=lambda x: (x["active"], x["ceiling"]), reverse=True)

    # hero
    exclusive_latent = sum(x["undrawn"] for x in exclusive_veh if x["active"] and x["ceiling"] > 0)
    n_active = sum(1 for x in veh if x["active"] and x["ceiling"] > 0)
    total_drawn = sum(d["amt"] for d in drawn.values())
    n_enriched = sum(1 for r in rows if r.enriched_at is not None)

    # recent draws (the signal) — newest first, paired with the parent's remaining undrawn
    veh_by_gid = {x["gid"]: x for x in veh}
    dated = [o for o in orders if (o.date_signed or o.start_date)]
    dated.sort(key=lambda o: (o.date_signed or o.start_date), reverse=True)
    draws = []
    for o in dated[:25]:
        pv = veh_by_gid.get(o.parent_generated_id)
        draws.append({
            "date": o.date_signed or o.start_date, "order": o.award_id,
            "program": pv["program"] if pv else None, "amount": f(o.amount),
            "parent": o.parent_award_id, "parent_undrawn": pv["undrawn"] if pv else None,
            "customer": o.funding_sub_agency or o.awarding_sub_agency,
            "desc": o.description, "gid": o.generated_internal_id, "parent_gid": o.parent_generated_id,
        })

    # by program
    prog = {}
    for x in veh:
        if not x["program"]:
            continue
        p = prog.setdefault(x["program"], {"ceiling": 0.0, "drawn": 0.0, "n": 0, "multi": x["is_multi"]})
        p["ceiling"] += x["ceiling"]; p["drawn"] += x["drawn"]; p["n"] += 1; p["multi"] = p["multi"] or x["is_multi"]
    programs = sorted([{"name": k, **v} for k, v in prog.items()], key=lambda x: x["ceiling"], reverse=True)

    # standalone definitive contracts (not a vehicle, no parent) — undrawn = unexercised options
    definitive = []
    for r in rows:
        if r.is_idv or r.parent_generated_id:
            continue
        if (r.award_type or "").upper() != "DEFINITIVE CONTRACT":
            continue  # this section = only true definitive contracts (FPDS type D)
        ceiling   = f(r.ceiling)
        obligated = f(r.total_obligation if r.total_obligation is not None else r.amount)
        expiry    = r.end_date
        definitive.append({
            "award_id": r.award_id, "program": r.program_acronym, "desc": r.description,
            "ceiling": ceiling, "obligated": obligated, "undrawn": max(ceiling - obligated, 0.0),
            "pct": (obligated / ceiling) if ceiling > 0 else None,
            "expiry": expiry, "active": (expiry is None) or (expiry >= today),
            "funding": r.funding_sub_agency, "agency": r.awarding_sub_agency,
            "gid": r.generated_internal_id,
        })
    definitive.sort(key=lambda x: (x["active"], x["ceiling"]), reverse=True)
    n_definitive = len(definitive)
    def_options_total = sum(x["undrawn"] for x in definitive if x["active"] and x["ceiling"] > 0)
    definitive = definitive[:60]  # cap for display; big/active first

    return templates.TemplateResponse("company.html", {
        "request": request, "ticker": ticker, "name": display_name,
        "title": f"{display_name} ({ticker}) — Position",
        "exclusive_latent": exclusive_latent, "n_active": n_active,
        "total_drawn": total_drawn, "n_rows": len(rows), "n_enriched": n_enriched,
        "n_vehicles": len(veh), "exclusive_veh": exclusive_veh, "shared_veh": shared_veh,
        "show_expired": show_expired, "draws": draws, "programs": programs, "today": today,
        "definitive": definitive, "n_definitive": n_definitive, "def_options_total": def_options_total,
    })


@app.get("/dow")
async def dow_awards_screen(
    request: Request,
    page:       int = 1,       # paginates by RELEASE DAY, not by award
    page_size:  int = 15,
    from_date:  str | None = None,
    to_date:    str | None = None,
    q:          str | None = None,
    action:     str | None = None,
):
    def _parse_date(s):
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    fd = _parse_date(from_date)
    td = _parse_date(to_date)
    if page < 1:
        page = 1

    async with AsyncSessionLocal() as session:
        # Shared filter conditions (award + date + search)
        conds = []
        if fd:
            conds.append(DowContractRelease.release_date >= fd)
        if td:
            conds.append(DowContractRelease.release_date <= td)
        if action:
            conds.append(DowAward.action_type == action)
        if q:
            # Match the awardee NAME only — not city/state/PIID/status. Casting the
            # whole awardees JSONB to text matched any field (e.g. "rand" hit the
            # city "Grand Rapids"); scope to name_raw via an EXISTS over the array.
            conds.append(text(
                "EXISTS (SELECT 1 FROM jsonb_array_elements(dow_awards.awardees) e "
                "WHERE e->>'name_raw' ILIKE :awardee_q)"
            ).bindparams(awardee_q=f"%{q}%"))

        # Distinct release DAYS that have matching awards, newest first
        days_stmt = (
            select(DowContractRelease.id, DowContractRelease.release_date)
            .join(DowAward, DowAward.release_id == DowContractRelease.id)
            .where(*conds)
            .distinct()
            .order_by(DowContractRelease.release_date.desc().nullslast(),
                      DowContractRelease.id.desc())
        )
        all_days = (await session.execute(days_stmt)).all()
        total_days = len(all_days)

        # Total matching awards (for the header line)
        total_awards = (await session.execute(
            select(func.count())
            .select_from(DowAward)
            .join(DowContractRelease, DowAward.release_id == DowContractRelease.id)
            .where(*conds)
        )).scalar_one()

        # Page the days, then fetch their awards
        offset = (page - 1) * page_size
        page_day_ids = [d.id for d in all_days[offset:offset + page_size]]

        days = []  # list of (release, [awards]) in date order
        if page_day_ids:
            awards_stmt = (
                select(DowAward)
                .options(selectinload(DowAward.release))
                .join(DowContractRelease, DowAward.release_id == DowContractRelease.id)
                .where(DowAward.release_id.in_(page_day_ids), *conds)
                .order_by(DowContractRelease.release_date.desc().nullslast(),
                          DowAward.award_index.asc())
            )
            awards = (await session.execute(awards_stmt)).scalars().unique().all()

            # Per-award displayable awardees: drop parent-reference (regex_only)
            # entries, and — when searching — keep only awardees whose NAME matches,
            # so a search hit in a large multi-award pool doesn't surface every
            # co-awardee. Attached as a runtime attr for the template.
            ql = q.lower() if q else None
            for a in awards:
                shown = []
                for aw in (a.awardees or []):
                    if aw.get("pairing_confidence") == "regex_only":
                        continue
                    if ql and ql not in (aw.get("name_raw") or "").lower():
                        continue
                    shown.append(aw)
                a.shown_awardees = shown

            by_release = {}
            for a in awards:
                if a.shown_awardees:
                    by_release.setdefault(a.release_id, []).append(a)
            for rid in page_day_ids:
                rel_awards = by_release.get(rid)
                if rel_awards:
                    days.append((rel_awards[0].release, rel_awards))

    total_pages = max(1, (total_days + page_size - 1) // page_size)

    return templates.TemplateResponse("dow_awards.html", {
        "request":       request,
        "title":         "Strata — DoW Contract Awards",
        "days":          days,
        "total_days":    total_days,
        "total_awards":  total_awards,
        "page":          page,
        "page_size":     page_size,
        "total_pages":   total_pages,
        "from_date":     from_date or "",
        "to_date":       to_date or "",
        "q":             q or "",
        "action_filter": action or "",
    })


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
            .order_by(mention_count.desc())
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
            "title": "Strata - FCC Entities",
        },
    )


@app.get("/admin/icfs/filings/by-number/{file_number:path}")
async def icfs_filing_by_number(file_number: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(IcfsFiling.id).where(IcfsFiling.file_number == file_number).limit(1)
        )
        filing_id = result.scalar_one_or_none()
    if filing_id is None:
        raise HTTPException(status_code=404, detail=f"Filing {file_number} not found")
    return RedirectResponse(url=f"/admin/icfs/filings/{filing_id}")


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
        from sqlalchemy import or_
        filters = []
        if q:
            filters.append(or_(
                IcfsFiling.applicant_name.ilike(f"%{q}%"),
                IcfsFiling.file_number.ilike(f"%{q}%"),
            ))

        count_stmt = select(func.count()).select_from(IcfsFiling).where(*filters)
        count_result = await session.execute(count_stmt)
        total = int(count_result.scalar() or 0)

        stmt = (
            select(IcfsFiling)
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


@app.get("/admin/icfs/filings/{filing_id}")
async def icfs_filing_detail(request: Request, filing_id: int):
    async with AsyncSessionLocal() as session:
        filing = await session.get(IcfsFiling, filing_id)
        if filing is None:
            raise HTTPException(status_code=404, detail="Filing not found")

        pleadings = []
        if filing.file_number:
            p_result = await session.execute(
                select(IcfsPleadingAndComment)
                .where(IcfsPleadingAndComment.file_number.ilike(f"%{filing.file_number}%"))
                .order_by(IcfsPleadingAndComment.sys_created_on.desc().nullslast())
            )
            pleadings = list(p_result.scalars().all())

        ah_result = await session.execute(
            select(IcfsFilingActionHistory)
            .where(IcfsFilingActionHistory.filing_id == filing_id)
            .order_by(IcfsFilingActionHistory.detected_at.desc())
        )
        action_history = list(ah_result.scalars().all())

        attachments = sorted(
            filing.attachments or [],
            key=lambda a: a.get("date") or "",
            reverse=True,
        )

    return templates.TemplateResponse(
        "icfs_filing_detail.html",
        {
            "request": request,
            "filing": filing,
            "attachments": attachments,
            "pleadings": pleadings,
            "action_history": action_history,
            "citation_url": _icfs_filing_citation_url,
            "citation_url_pleading": _icfs_pleading_citation_url,
            "title": f"Strata - {filing.file_number or 'Filing'}",
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


@app.get("/admin/icfs/pleadings/{pleading_id}")
async def icfs_pleading_detail(request: Request, pleading_id: int):
    async with AsyncSessionLocal() as session:
        pleading = await session.get(
            IcfsPleadingAndComment, pleading_id,
            options=[selectinload(IcfsPleadingAndComment.extracted_events)],
        )
        if pleading is None:
            raise HTTPException(status_code=404, detail="Pleading not found")

    return templates.TemplateResponse(
        "icfs_pleading_detail.html",
        {
            "request": request,
            "pleading": pleading,
            "citation_url": _icfs_pleading_citation_url,
            "title": f"Strata - {pleading.pleading_type or 'Pleading'} {pleading.file_number or ''}".strip(),
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
            .options(selectinload(IcfsPublicNotice.extracted_events))
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
        {"request": request, "notice": notice, "entities": entities, "title": f"Strata - Notice {notice.number}"},
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
            "title": "Strata - Signal Notices",
        },
    )


@app.get("/admin/icfs/contested")
async def icfs_contested(request: Request, applicant: str = "", min_pleadings: int = 3):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT
                    f.id,
                    f.file_number,
                    f.applicant_name,
                    f.submission_date,
                    COUNT(p.id) AS pleading_count,
                    ROUND(EXTRACT(EPOCH FROM (NOW() - f.submission_date)) / 86400 / 365.25, 1)::float AS years_pending,
                    STRING_AGG(DISTINCT p.filer_name, ' · ' ORDER BY p.filer_name)
                        FILTER (WHERE p.filer_name IS NOT NULL AND p.filer_name != f.applicant_name)
                        AS contestants
                FROM icfs_filings f
                LEFT JOIN icfs_pleadings_and_comments p
                    ON p.file_number ILIKE '%' || f.file_number || '%'
                WHERE f.action IS NULL
                    AND f.file_number IS NOT NULL
                    AND (:applicant_pattern IS NULL OR f.applicant_name ILIKE :applicant_pattern)
                GROUP BY f.id, f.file_number, f.applicant_name, f.submission_date
                HAVING COUNT(p.id) >= :min_pleadings
                ORDER BY pleading_count DESC, f.submission_date ASC
                LIMIT 100
            """).bindparams(
                bindparam("applicant_pattern", type_=String),
                bindparam("min_pleadings", type_=Integer),
            ),
            {
                "applicant_pattern": f"%{applicant}%" if applicant else None,
                "min_pleadings": min_pleadings,
            },
        )
        rows = result.mappings().all()

    return templates.TemplateResponse(
        "icfs_contested.html",
        {
            "request": request,
            "rows": rows,
            "applicant": applicant,
            "min_pleadings": min_pleadings,
            "title": "Strata - Contested Filings",
        },
    )


@app.get("/admin/icfs/entity/{canonical_id}")
async def icfs_entity_timeline(request: Request, canonical_id: int, tab: str = "timeline"):
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
                {"request": request, "canonical": canonical, "timeline": [], "counts": {}, "tab": tab, "contested_rows": []},
            )

        # All events for those entities, with notice + filing + pleading joins
        event_stmt = (
            select(ExtractedEvent, ExtractedEntity, IcfsPublicNotice, IcfsFiling, IcfsPleadingAndComment)
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
            .outerjoin(
                IcfsPleadingAndComment,
                and_(
                    ExtractedEvent.source_type == "icfs_pleading",
                    ExtractedEvent.source_id == IcfsPleadingAndComment.id,
                ),
            )
            .where(ExtractedEvent.entity_id.in_(entity_ids))
            .order_by(ExtractedEvent.event_date.desc().nullslast(), ExtractedEvent.id.desc())
        )
        rows = list((await session.execute(event_stmt)).all())

        def _as_date(d):
            return d.date() if isinstance(d, datetime) else d   # timestamptz→date; date stays

        timeline = []
        for ev, e, notice, filing, pleading in rows:
            if ev.source_type == "icfs_filing":
                card_type = "action" if (filing and filing.action) else "filing"
                action_label = filing.action if filing else None
            elif ev.source_type == "icfs_notice":
                card_type = "notice"
                action_label = None
            else:
                card_type = "pleading"
                action_label = None
            doc_url = None
            if filing:
                doc_url = _icfs_filing_citation_url(filing)
            elif pleading:
                doc_url = _icfs_pleading_citation_url(pleading)

            # Date filings by their LIVE dates (most-recent-action first), not the
            # copied-once event_date which goes stale when a grant/action lands later.
            # Immutable sources (notices/pleadings) keep using event_date.
            if ev.source_type == "icfs_filing" and filing is not None:
                live = filing.action_taken_date or filing.grant_date or filing.submission_date
                display_date = _as_date(live) if live else ev.event_date
            else:
                display_date = ev.event_date

            timeline.append({
                "event": ev,
                "entity": e,
                "notice": notice,
                "filing": filing,
                "pleading": pleading,
                "card_type": card_type,
                "action_label": action_label,
                "doc_url": doc_url,
                "display_date": display_date,
            })

        # Sort by the live display_date (desc), undated rows last.
        timeline.sort(key=lambda r: r["display_date"] or date.min, reverse=True)

        counts = {
            "notice": sum(1 for r in timeline if r["card_type"] == "notice"),
            "action": sum(1 for r in timeline if r["card_type"] == "action"),
            "filing": sum(1 for r in timeline if r["card_type"] == "filing"),
            "pleading": sum(1 for r in timeline if r["card_type"] == "pleading"),
            "signal": sum(1 for r in timeline if r["event"].signal_tier == "signal"),
        }

        contested_rows = []
        if tab == "contested":
            cr = await session.execute(
                text("""
                    SELECT
                        f.id,
                        f.file_number,
                        f.applicant_name,
                        f.submission_date,
                        COUNT(p.id) AS pleading_count,
                        ROUND(EXTRACT(EPOCH FROM (NOW() - f.submission_date)) / 86400 / 365.25, 1)::float AS years_pending,
                        STRING_AGG(DISTINCT p.filer_name, ' · ' ORDER BY p.filer_name)
                            FILTER (WHERE p.filer_name IS NOT NULL AND p.filer_name != f.applicant_name)
                            AS contestants
                    FROM icfs_filings f
                    LEFT JOIN icfs_pleadings_and_comments p
                        ON p.file_number ILIKE '%' || f.file_number || '%'
                    WHERE f.action IS NULL
                        AND f.file_number IS NOT NULL
                        AND f.applicant_name ILIKE :applicant_pattern
                    GROUP BY f.id, f.file_number, f.applicant_name, f.submission_date
                    HAVING COUNT(p.id) >= 1
                    ORDER BY pleading_count DESC, f.submission_date ASC
                """).bindparams(bindparam("applicant_pattern", type_=String)),
                {"applicant_pattern": f"%{canonical.canonical_name}%"},
            )
            contested_rows = cr.mappings().all()

    return templates.TemplateResponse(
        "icfs_entity_timeline.html",
        {
            "request": request,
            "canonical": canonical,
            "timeline": timeline,
            "counts": counts,
            "tab": tab,
            "contested_rows": contested_rows,
            "title": f"Strata - {canonical.canonical_name}",
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
