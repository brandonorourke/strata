# To Build

## Next

- **Primary-source pivot, ICFS first** (see `docs/decisions.md`, 2026-06-16): shift ingestion focus from news toward primary-source records. ICFS is the confirmed first build — a real customer wants it for his Viasat equity position, it's the most buildable, and no incumbent does FCC-for-investors monitoring.
  - Build order: empty deployed skeleton first (cross the deployment barrier while trivial) → ingest one name → produce a digest → point at the customer's actual watchlist.
  - Source: FCC ICFS (International Communications Filing System) — satellite earth stations, space stations, Section 214 authorizations, submarine cable landing licenses, etc. Customer manually checks this portal today and calls it "impossible to navigate."
  - Then: broader FCC RSS (dockets, rulemakings, commissioner statements) — displaces a law-firm subscription the same customer pays for today.
  - Architecture: one engine, two adapters (ingest → extract entities → resolve against a watchlist or create pending entities → LLM summary with citations → score/cluster/alert) — domain differences live only in the ingestion adapter, so this should generalize to UCC later without a rebuild.
- **UCC/credit — pending second module, not yet started.** Gated on the customer confirming the Altice signal (coordinated subsidiary liens) is actually tradeable, not just interesting. Build only on a strong trade-relevant yes. If/when it's a go: UCC lien filings (state-level, starting with NY/DE), mortgage/recording-office documents (county clerk records), court dockets & complaints (PACER/CourtListener-style sources), then lien-perfection analysis as its own lens.
- Add an explicit ambiguity note on cluster detail pages (collisions are possible for same normalized name).
- Show lightweight disambiguation hints on cluster detail pages (article domains + HQ country/region mentions when present).
- Build the separate linking process to promote mention clusters into canonical entities when strong identifiers exist.
- Add a second LLM pass per top cluster to generate an evidence-backed brief: what happened, why it matters, what to watch.
    - Proof of concept for: AI synthesis of “friction over time” to answer: “What does this all mean?”
- The first sellable MVP for the first wedge (litigation finance or special situations or private credit portfolio monitoring)

## Tabled

- FreightWaves ingestion — was the original v0 bootstrap source; not aligned with the primary-source/credit wedge for now.

## Done

- Parse SEC RSS feeds (press releases, litigation releases, administrative proceedings).
- Extract candidate website domains from `raw_html` and store as suggestions (not authoritative).
