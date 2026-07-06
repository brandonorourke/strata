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

### Polling for a company watchlist

No contractor filter exists in the API — `award.awardee.ueiSAM` is response-only. Strategy:

```python
# Daily pull: all DoD award notices, filter client-side by UEI watchlist
params = {
    "api_key": SAM_API_KEY,
    "ptype": "a",
    "postedFrom": (today - 7).strftime("%m/%d/%Y"),
    "postedTo": today.strftime("%m/%d/%Y"),
    "limit": 1000,
}
# Filter: notice["award"]["awardee"]["ueiSAM"] in WATCHLIST_UEIS
```

~130 DoD award notices/day — fits in one page (limit=1000) most days. Catches new IDIQ vehicles and standalone awards within the 15-day active window.

---

## Bulk CSV Downloads

Available at SAM.gov → Data Services. Files are organized by fiscal year (Oct–Sep).

- `FY2025_archived_opportunities.csv` — contains IDIQ base awards, solicitations, J&As from Oct 2024–Sep 2025
- `FY2026_archived_opportunities.csv` — Oct 2025–present

CSV columns (positional, no header): notice ID, title, solicitation number, dept, dept code, subtier, subtier code, office, office code, posted date, type, base type, archive type, archive date, set-aside description, set-aside code, response deadline, NAICS, classification code, city, state, zip, country, active flag, **award number (PIID)**, **award date**, **award amount**, **awardee name+location**, POC fields, office address, SAM UI link, description.

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
