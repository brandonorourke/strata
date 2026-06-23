# To Build

## Next

- Primary-source pivot (see `docs/decisions.md`, 2026-06-23): shift ingestion focus from news toward primary-source records — credit/special-sits buyers need lien-perfection and entity/subsidiary-movement signals, not another news feed.
  - First new source: FCC ICFS (International Communications Filing System) — satellite earth stations, space stations, Section 214 authorizations, submarine cable landing licenses, etc. Validated directly by a customer call: he manually checks this portal today and calls it "impossible to navigate."
  - Then: broader FCC RSS (dockets, rulemakings, commissioner statements) — displaces a law-firm subscription a real customer pays for today.
  - Then: UCC lien filings (state-level, starting with NY/DE), mortgage/recording-office documents (county clerk records), court dockets & complaints (PACER/CourtListener-style sources).
  - Eventually: lien-perfection analysis as its own lens ("is this lien defective" — ties directly to recovery rates, not just monitoring that a lien exists).
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
