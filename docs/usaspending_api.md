# USASpending API — Reverse-Engineered Reference

Validated 2026-07-05 against live API. All endpoints are public, no API key required.

Base URL: `https://api.usaspending.gov/api/v2/`

---

## Award Lookup by PIID

The core linkage: given a PIID from a DoW press release, fetch the contract record.

### PIID type determines the URL format

```
PIID structure: CCCCCC-YY-T-NNNN
                ^^^^^^  ^^ ^ ^^^^
                office  FY type seq
```

The type code (3rd dash-delimited segment) determines which endpoint to use:

| PIID Type | Instrument | Endpoint Prefix | Example |
|-----------|-----------|-----------------|---------|
| `C` | Definitive contract | `CONT_AWD_{piid}_9700_-NONE-_-NONE-` | `FA8807-18-C-0009` |
| `D` | IDIQ/IDV base | `CONT_IDV_{piid}_9700` | `W912DQ-14-D-4000` |
| `A` | BPA | `CONT_AWD_{piid}_9700_-NONE-_-NONE-` | `HQ0034-12-A-0003` |
| `G` | BOA | `CONT_AWD_{piid}_9700_-NONE-_-NONE-` | `N00019-11-G-0001` |
| `F` | Delivery order | Needs parent PIID — see below | `FA8807-19-F-0008` |

**All DoD contracts use agency code `9700`** regardless of service branch (Army, Navy, Air Force, DARPA, etc.).

### Definitive contract (C-type) lookup

```
GET /api/v2/awards/CONT_AWD_{PIID_NO_DASHES}_9700_-NONE-_-NONE-/
```

Example:
```
GET /api/v2/awards/CONT_AWD_FA880718C0009_9700_-NONE-_-NONE-/
```

### IDIQ / IDV base contract (D-type) lookup

The IDV format uses a 2-part key, not the 4-part CONT_AWD key:

```
GET /api/v2/awards/CONT_IDV_{PIID_NO_DASHES}_9700/
```

Example:
```
GET /api/v2/awards/CONT_IDV_W912DQ14D4000_9700/
```

### Delivery order (F-type) lookup

Requires the parent contract's PIID:

```
GET /api/v2/awards/CONT_AWD_{ORDER_PIID}_{AGENCY}_{PARENT_PIID}_{PARENT_AGENCY}/
```

Example (PTS-G Swarm 1, Viasat, May 2026 — delivery order under a FY2025 IDIQ):
```
GET /api/v2/awards/CONT_AWD_FA880726FB004_9700_FA880725DB002_9700/
```

**Getting the parent PIID**: Two sources:
1. **DoW press release text** — often states "order against previously issued basic ordering agreement (PARENT-PIID)" or similar. Reliable when present.
2. **SAM.gov award notice** — the IDIQ base award notice lists "Contract Award Number" = parent PIID. For PTS-G: `FA880725DB002` visible in FY2025 bulk CSV.

**FY2025 F-types resolve correctly** once you have the parent PIID. Validated examples:

| Order PIID | Parent PIID | Awardee | DoW Amount | USASpending | Match |
|---|---|---|---|---|---|
| `N0001925F0264` | `N0001924G0010` | Lockheed (F-35 DMSMS) | $22,662,794 | $22,662,794 | ✓ exact |
| `N0001925F0056` | `N0001920G0007` | Raytheon (MV-22 software) | $9,490,815 | $10,969,216 | higher — contract modified since award |
| `FA880725FB017` | `FA880725DB002` | Viasat (PTS-G D&D) | ~$7.4M | $7.5M | ✓ match |

**DoW press release = initial award amount. USASpending = current cumulative obligation** including all subsequent modifications. If USASpending shows more than the press release, the contract has been modified — that's useful signal, not a discrepancy.

**Fallback**: If the delivery order isn't indexed (FY2026 F-types absent as of July 2026), resolve the parent D/G-type instead to get program ceiling and description:
```
GET /api/v2/awards/CONT_IDV_FA880725DB002_9700/
```

### Condensed (no-dash) PIID format

Some contracts use a condensed format without dashes (e.g. `HQ003426DE016`, `N6852026D1010`). Strip non-alphanumeric characters the same way — the type detection falls back to checking the character pattern.

---

## Response Fields

### Definitive contract (CONT_AWD) response

```json
{
  "id": 307303768,
  "generated_unique_award_id": "CONT_AWD_HR001114C0079_9700_-NONE-_-NONE-",
  "piid": "HR001114C0079",
  "category": "contract",
  "type": "D",
  "type_description": "DEFINITIVE CONTRACT",
  "description": "LONG RANGE ANTI-SHIP MISSILE (LRASM) ACCELERATED ACQUISITION",
  "total_obligation": 381815206.61,
  "base_exercised_options": 387462092.61,
  "base_and_all_options": 387462092.61,
  "date_signed": "2014-07-02",
  "parent_award": null,
  "recipient": {
    "recipient_name": "LOCKHEED MARTIN CORPORATION",
    "recipient_uei": "H7PNSVNN5827",
    "location": {
      "state_code": "FL",
      "city_name": "ORLANDO"
    }
  },
  "period_of_performance": {
    "start_date": "2014-07-02",
    "end_date": "2022-01-21",
    "potential_end_date": "2022-01-21"
  },
  "awarding_agency": { ... },
  "place_of_performance": { ... },
  "psc_hierarchy": { ... },
  "naics_hierarchy": { ... }
}
```

### IDIQ base contract (CONT_IDV) response

```json
{
  "generated_unique_award_id": "CONT_IDV_W912DQ14D4000_9700",
  "piid": "W912DQ14D4000",
  "category": "idv",
  "type": "IDV_B_B",
  "type_description": "INDEFINITE DELIVERY / INDEFINITE QUANTITY",
  "description": "IDIQ MEDCOM SOUTHERN REGION REPAIR AND CONSTRUCTION MATOC",
  "total_obligation": 0.0,
  "base_and_all_options": 49000000.0,   ← this is the ceiling
  "recipient": {
    "recipient_name": "ROYCE CONSTRUCTION SERVICES, LLC",
    "recipient_uei": "..."
  },
  "period_of_performance": {
    "start_date": "2014-07-03",
    "end_date": "2017-07-02"
  }
}
```

**Key distinction**: `total_obligation` is always `0` for IDIQ base contracts. Actual spend flows through delivery orders placed against the vehicle. The DoW-announced ceiling corresponds to `base_and_all_options`.

### IDV type codes

| `type` | Meaning |
|--------|---------|
| `IDV_B_B` | IDIQ (Indefinite Delivery / Indefinite Quantity) |
| `IDV_B_A` | Requirements contract |
| `IDV_B_C` | Indefinite Delivery / Definite Quantity |
| `IDV_A` | BPA (Blanket Purchase Agreement) |
| `IDV_C` | FSS (Federal Supply Schedule) |
| `IDV_D` | GWACs / MACs |

---

## Web URL

To link to the USASpending contract page:

```
https://www.usaspending.gov/award/{generated_unique_award_id}/
```

Examples:
- `https://www.usaspending.gov/award/CONT_AWD_FA880718C0009_9700_-NONE-_-NONE-/`
- `https://www.usaspending.gov/award/CONT_IDV_W912DQ14D4000_9700/`

---

## Recipient / Entity Search

Look up a company by name to get its UEI and total award amounts:

```
POST /api/v2/recipient/
{
  "keyword": "AeroVironment",
  "limit": 5
}
```

Response:
```json
{
  "results": [
    {
      "id": "MWKWXVSSC518-C",
      "uei": "MWKWXVSSC518",
      "name": "AEROVIRONMENT, INC",
      "recipient_level": "C",
      "amount": 593000000.0
    }
  ]
}
```

`recipient_level`: `P` = parent entity, `C` = child/subsidiary.

## Awards by Recipient

```
POST /api/v2/search/spending_by_award/
{
  "filters": {
    "award_type_codes": ["A","B","C","D"],
    "recipient_search_text": ["AeroVironment"],
    "agencies": [{"type":"awarding","tier":"toptier","name":"Department of Defense"}]
  },
  "fields": ["Award ID","Recipient Name","Award Amount","Description"],
  "page": 1,
  "limit": 25,
  "sort": "Award Amount",
  "order": "desc"
}
```

`Award ID` in the response is the no-dash PIID. Use it to reconstruct the lookup URL.

---

## Resolution Rates (DoW data)

Tested against our DB (30+ releases, FY2014–FY2026). Key finding: **resolution depends on the PIID's fiscal year, not the press release date.**

| PIID Vintage | Resolution | Notes |
|---------|-----------|-------|
| Pre-FY2026 (C/D types) | ~100% | Resolves even when appearing in recent mods |
| FY2026 (C/D types) | 0% | Entire FY still unindexed as of July 6, 2026 |
| F-type (any year) | ~0% without parent PIID | Need parent from SAM.gov |

**The lag is fiscal-year-wide, not per-contract.** FY2026 started October 2025 — as of July 6, 2026 (9 months in), no FY2026 base contracts resolve on USASpending. Pre-FY2026 contracts resolve immediately, including recent modifications. The year digits in the PIID (e.g. `26` in `N0002426C4415`) determine resolution, not the press release date.

**Practical implication**: ~30% of DoW press release PIIDs will be FY2026 originations that can't be enriched yet. The other ~70% are modifications to pre-FY2026 contracts that resolve immediately and often reveal much larger underlying contract values (see examples below).

**Resolved contract examples** (appeared in Jun-Jul 2026 press releases as modifications):

| PIID | Awardee | Signed | Obligated | Description |
|---|---|---|---|---|
| `N0001914C0037` | General Atomics | 2014-05-08 | $1.7B | CVN 79 EMALS long lead time material |
| `N0001919C0010` | Lockheed Martin | 2018-11-15 | $4.3B | Dual capable aircraft UCA |
| `N0001924C0032` | Raytheon | 2024-09-27 | $2.0B | LOT 24-26 production FMS |
| `W912CH-25-C-0055` | General Dynamics | 2025-06-30 | $465M | Abrams engineering program |
| `N0001925C0009` | Lockheed Martin | 2025-09-30 | $233M | IRST sensor new contract |
| `N0001923D0011` | Sikorsky | 2022-11-29 | $0 (IDIQ) | VH sustainment support, $315M ceiling |

The modification amount in the press release is typically small; USASpending reveals the full contract size.

PIID type distribution in DoW press releases: D=69%, C=22%, F=6%, other=3%.

---

## Python Snippet

```python
import re, httpx

def usaspending_url(piid: str) -> str | None:
    clean = re.sub(r'[^A-Z0-9]', '', piid.upper())
    parts = piid.split('-')
    type_code = parts[2] if len(parts) >= 3 else ''
    if type_code == 'D':
        uid = f"CONT_IDV_{clean}_9700"
    elif type_code == 'F':
        return None  # need parent PIID
    else:
        uid = f"CONT_AWD_{clean}_9700_-NONE-_-NONE-"
    return f"https://api.usaspending.gov/api/v2/awards/{uid}/"

async def fetch_award(piid: str) -> dict | None:
    url = usaspending_url(piid)
    if not url:
        return None
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=10)
        d = r.json()
        return d if 'total_obligation' in d else None
```

---

## SAM.gov

See `docs/sam_api.md` for full SAM.gov reference including the Opportunities API, bulk CSV downloads, FPDS migration, and the PTS-G case study.

Short version: SAM.gov award notices cover IDIQ base contracts (same day as award, includes $4B ceiling and all awardee PIIDs). Delivery orders do NOT get SAM notices — DoW press release is their only same-day record. The `recipient_uei` from USASpending links to SAM entity registration.
