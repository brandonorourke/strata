# SAM.gov — Reference for Contract Data

Validated 2026-07-06. API key required (free — register at SAM.gov, generate under Account Details).

---

## What SAM.gov Contains (vs Other Sources)

SAM.gov is now the unified federal acquisition system. FPDS has migrated into it — SAM is the upstream source; USASpending and the legacy FPDS Atom feed are downstream consumers.

| Source | What it covers | Timing |
|---|---|---|
| **SAM.gov award notices** | IDIQ base contracts, standalone awards, J&As | Same day as award |
| **DoW press releases** | Delivery orders / task orders against existing IDIQs | Same day as award |
| **USASpending** | All of the above, structured, queryable | Days to weeks lag |

**Key finding**: Delivery orders placed against existing IDIQs/BOAs do NOT get separate SAM.gov award notices — confirmed for both FY2025 and FY2026 delivery orders by grepping bulk CSVs. The DoW press release is the only same-day public record for them. The parent IDIQ/BOA IS in SAM.

**Same-day split**: On July 28, 2025, SAM published the D-type IDIQ base contracts (`FA880725DB002–DB006`, $4B ceiling) while the DoW press release announced the F-type Design & Demo delivery orders (`FA8807-25-F-B017–B021`, $37M combined) placed against those same vehicles. They cover different instruments. The $4B program ceiling is only visible via SAM — the press releases alone would make PTS-G look like a $37M then $437M program.

---

## Opportunities API

Endpoint: `https://api.sam.gov/opportunities/v2/search`

Covers: solicitations, award notices (`ptype=a`), J&As (`ptype=u`), pre-solicitations (`ptype=p`), sources sought (`ptype=r`).

**Mandatory parameters**: `api_key`, `postedFrom` (MM/dd/yyyy), `postedTo` (MM/dd/yyyy). Max date range: 1 year.

**Key limitation**: Returns only currently active notices. Award notices auto-archive 15 days after the contract award date. Historical data requires bulk CSV download (see below).

**Rate limits (important):**
- **Federal user key: 1,000 requests/day.**
- **Non-federal user key: 10 requests/day.** (Our key is non-federal.)
- Response is max 1,000 records/request. A 20-day all-agency award-notice window is ~3,500 records = 4 requests. So a **wide backfill pull is not viable on a non-federal key** (~2 pulls exhausts the daily 10). Poll narrow windows instead.

**Validated 2026-07-06 — the live API DOES carry fresh DoW awards.** Probing our extracted PIIDs against a 20-day live window returned 56 hits, **49 net-new vs the archived CSV** — including same-day multi-award IDIQ pools (ship-repair `N4523A26D100X`, disaster-response `W912HN26DA01X`, construction `W912PL26DA00X`, several posted that very day). This corrects the earlier "SAM is CSV-only/marginal" read: the **live API is the same-day source**; the CSV simply hasn't archived recent awards yet (see archival-lag note below). Delivery orders (F-types) still get no SAM notice.

### Award notice response fields (ptype=a)

```
award.number      → PIID (the contract number)
award.amount      → value (IDIQ ceiling for IDIQ base awards)
award.date        → award date
award.awardee.name
award.awardee.ueiSAM  → UEI for entity linkage
solicitationNumber    → notice ID
fullParentPathName    → agency hierarchy
```

### Polling design (constrained by the 10/day non-federal limit)

No contractor filter exists in the API — `award.awardee.ueiSAM` and `award.number` are response-only. So the pattern is: pull a narrow recent window, extract award numbers/UEIs, match client-side.

**Must poll narrowly to stay under 10 requests/day.** Pull only the trailing 1–2 days (one day of all-agency award notices ≈ ~180 records = **1 request**), not a wide window.

```python
# Forward daily poll: yesterday's award notices only → ~1 request/day
params = {
    "api_key": SAM_API_KEY,
    "ptype": "a",
    "postedFrom": (today - 1).strftime("%m/%d/%Y"),
    "postedTo": today.strftime("%m/%d/%Y"),
    "limit": 1000,
}
# Match notice["award"]["number"] against extracted PIIDs;
# capture award.amount (ceiling) + award.awardee.ueiSAM.
```

This catches new IDIQ bases and standalone awards same-day, within the 15-day active window, at ~1–2 requests/day. **Cache results locally** — do not re-pull the same window (re-runs burn the daily quota; that's what caused a 429 during testing). For anything older than the active window, use the bulk CSV, never the live API.

---

## Bulk CSV Downloads

Available at SAM.gov → Data Services. Files are organized by fiscal year (Oct–Sep).

- `FY2025_archived_opportunities.csv` — contains IDIQ base awards, solicitations, J&As from Oct 2024–Sep 2025
- `FY2026_archived_opportunities.csv` — Oct 2025–present

The CSV has a **header row**. Award number is column `AwardNumber` (index 25), `Award$` (27), `Awardee` (28), `Type` (10 — filter `Award Notice`).

**Archival-lag — the CSV is a snapshot that trails real-time by ~3–6 weeks (validated 2026-07-06).** It contains only *archived* opportunities; award notices archive ~15 days after award, solicitations after their deadline. Measured on the FY2026 file (downloaded Jul 6): award notices by month were full through ~mid-May (May: 7,183), partial in June (4,407), and **essentially empty in July (1)** — even though the file's latest PostedDate was Jul 2. **Consequence: the CSV can never enrich a this-week release** — that's why fresh multi-award pools (`FA8109-26-D-B###`, `FA8903-26-D-####`) are absent from it while present in the live API. It also does not auto-update; re-download to advance the window. **Use the CSV only for backfill of releases older than ~6 weeks; use the live API for fresh ones.**

### PTS-G case study (from FY2025 bulk CSV)

5 award notices posted simultaneously July 28, 2025, one per awardee:

| PIID | Awardee | Amount |
|---|---|---|
| `FA880725DB002` | VIASAT INC, Carlsbad CA | $4,000,000,000 |
| `FA880725DB003` | NORTHROP GRUMMAN SYSTEMS CORPORATION, Dulles VA | $4,000,000,000 |
| `FA880725DB004` | ASTRANIS SPACE TECHNOLOGIES CORP, San Francisco CA | $4,000,000,000 |
| `FA880725DB005` | INTELSAT GENERAL COMMUNICATIONS LLC, McLean VA | $4,000,000,000 |
| `FA880725DB006` | THE BOEING COMPANY, El Segundo CA | $4,000,000,000 |

The $4B is the shared program ceiling shown on each awardee's notice — standard multi-award IDIQ practice. Delivery orders placed against these vehicles appear in DoW press releases, not SAM.

Solicitation lifecycle also visible in the CSV: pre-solicitation Oct 2024 → RFP Nov 2024 → amendments → 5 awards Jul 2025.

---

## IDIQ Contract Hierarchy

```
SAM award notice (Jul 28 2025)
  FA880725DB002  ← D-type IDIQ base, Viasat, $4B ceiling, 2025–2040
      └── FA880726FB004  ← F-type delivery order, Viasat Swarm 1
                            $218M (Viasat share of $437M combined)
                            Announced: DoW press release May 22 2026
                            NOT in SAM, NOT in USASpending (6+ weeks later)
                            Likely: classified reporting delay

  FA880725DB005  ← D-type IDIQ base, Intelsat, $4B ceiling
      └── FA880726FB005  ← F-type delivery order, Intelsat Swarm 1
```

To resolve a delivery order on USASpending, you need the parent PIID:
```
CONT_AWD_FA880726FB004_9700_FA880725DB002_9700
```
Source for parent PIID: SAM.gov award notice for the base IDIQ (bulk CSV or live API within 15-day window).

---

## FPDS Migration

FPDS has permanently migrated public contract award searching to SAM.gov. The legacy FPDS Atom feed (`fpds.gov/ezsearch/FEEDS/ATOM`) is being retired. SAM Contract Data API is the replacement. USASpending ingests from SAM/FPDS and lags by days to weeks.

Confirmed: FPDS Atom feed search for `FA880726FB004` returned empty — not a data lag issue, the feed is effectively dead for new records.

---

## Daily award-notice capture (`ingest_sam_awards.py`) — latency research

Built to test the thesis: **does SAM publish an award before DoW announces it?**
Two endpoints, two rate profiles:

| Endpoint | Auth | Rate | Gives |
|---|---|---|---|
| `/opportunities/v2/search?ptype=a` | **api_key** | **10 req/DAY** (non-federal) | daily list; `postedDate` **date-only** |
| `/api/prod/opps/v2/opportunities/{noticeId}` (`Accept: application/hal+json`) | **none** | unkeyed (throttle anyway) | **precise** `postedDate`/`createdDate` timestamps — the same data the sam.gov web page shows |

The precise timestamp is what the website displays (e.g. SMIT `N0002426D4308` →
`postedDate: 2026-07-06T13:13:06Z` = 8:13 AM EST). Use the detail endpoint (not HTML
scraping) for research-grade timing. Because it's unkeyed, `--detail` is throttled
(1s) and capped (`--detail-limit`, biggest-dollar first) so we stay polite.

**Incremental model — overlapping window + idempotent upsert (no watermark):**
Each run requests `postedFrom = today − --days`, `postedTo = today`, and upserts
`ON CONFLICT (notice_id) DO NOTHING`. `fetched_at` (our first-seen) is therefore
preserved across re-pulls, so:
- re-running is safe/idempotent (no cursor to corrupt);
- a small overlap (default `--days 2`) catches notices posted *late* on a prior day
  (postedDate is date-only, notices post throughout the day) that weren't up when the
  previous run fired — dedup makes the overlap free.
One search request/day covers it (a day rarely exceeds 1000 award notices; paginate
only if so, bounded by `--max-pages`). Raw search responses are saved to
`data/sam_raw/` (gitignored) for audit/replay.

**Comparison (`compare_sam_dow.py`):** joins `sam_award_notices.piid_key` to the
normalized PIID inside `dow_awards.awardees`, buckets each notice
(`sam_earlier` / `same_day` / `dow_earlier` / `sam_only`), and — because DoW is
**DoD-only** — splits `sam_only` into DoD (real discovery candidates) vs non-DoD
(structurally out of DoW scope: GSA/VA/DOI/DHS/LoC). Run against **prod** DoW for a
true read (local stops at its latest release_date; recent DoD `sam_only` is usually
just the local/prod gap).
