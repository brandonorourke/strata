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

**Getting the parent PIID**: The DoW press release does not include it. Best sources:
1. **SAM.gov award notice** — the notice for the original IDIQ award lists "Contract Award Number" which is the parent PIID. For PTS-G: notice ID `_PA` / related `FA880725X000X-PTSG-RFP` shows parent `FA880725DB002`.
2. **USASpending recipient search** — search the company name and filter to IDIQ awards from the same office/year.

**Fallback**: If the delivery order isn't indexed (F-type lag can exceed 6 weeks — PTS-G delivery order from May 22, 2026 was still absent on July 6, 2026), resolve the parent D-type IDIQ instead:
```
GET /api/v2/awards/CONT_IDV_FA880725DB002_9700/
```
This returns the $4B program ceiling and description even when no delivery orders are indexed yet. Check `child_award_count` to see how many orders are indexed.

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

Tested against our 679-PIID DB (30 releases, Jul 2014 and Jun-Jul 2026):

| Vintage | Resolution |
|---------|-----------|
| Pre-FY2026 | ~100% for non-F types |
| FY2026 | ~5% within 1 week (data lag observed: at least 7 calendar days) |
| F-type (any year) | ~0% without parent PIID |

**Observed lag**: Contracts announced June 29-30 and July 1-2, 2026 (tested July 5) were not yet indexed — 4-5 business days with a July 4 holiday in between. F-type delivery orders can lag significantly longer: PTS-G Swarm 1 (May 22, 2026 award) had zero child awards indexed under its parent IDIQ as of July 6, 2026 — 6+ weeks. USASpending enrichment must be treated as async/deferred.

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

SAM.gov requires an API key for automated access (TOS prohibits bots without a key). However, SAM.gov **award notices** are the best source for:
- Parent PIIDs for F-type delivery orders (listed as "Contract Award Number" on the IDIQ award notice)
- Program-level IDIQ ceilings (listed as "Base and All Options Value")
- 5-awardee / multi-award IDIQ structure

Example: PTS-G IDIQ award notice on SAM.gov listed `FA880725DB002` as Viasat's IDIQ base contract with a $4B ceiling — this is what defense analysts use to report program value. The $437M DoW press release was just the first delivery order (Swarm 1) against that vehicle.

USASpending is the right open data source for transaction-level contract enrichment. The `recipient_uei` from USASpending can be used to link back to SAM.gov entity registration if an API key is available.
