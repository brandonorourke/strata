# Strata Canon (v0) — Vision, PoC, ICP, Outreach

Status: working canon / non-binding  
Owner: Brandon  
Last updated: 2026-06-23  
Naming (settled, not to be relitigated): product is "Strata Terminal," corporate entity is "Proofgraph, Inc."

---

## 1) Strata OS Vision (the broader arc)

### One sentence
Strata is an intelligence OS for private markets: it maintains a time-aware map of entities + relationships + events, then converts it into explainable ranked attention (what changed, what matters, what to do next) tuned to a firm’s strategy.

### What Strata is (and is not)
Strata is:
- A “state machine” for a private markets universe: what’s true, what changed, and what deserves attention.
- Evidence-backed and explainable: every claim should trace to sources.

Strata is not:
- A feed
- A CRM
- A workflow suite / deal room
- A PitchBook clone
- A raw scraping/data dump product

### Core capabilities (end state)
1) Canonical map (ontology)
- Companies, people, firms, instruments (later)
- Relationships (investor/advisor/lender/operator) (later)
- Event timeline (financing, liens, lawsuits, enforcement, restructurings, etc.)
- Confidence + sources

2) Firm memory (internal + external fused) (later)
- Internal activity: meetings, intros, notes, decisions
- External signals: filings, news, UCC, courts
- Answers: “what do we know?”, “who do we know?”, “what changed since last look?”

3) Attention ranking (the core product surface)
- Ranked screens (most changed / emerging stress / new opportunities in Theme X)
- Alerts (threshold triggers)
- Briefings as a format option, not the identity

4) Lenses (strategy-specific views)
- Opportunistic credit lens (stress proxies, capital structure breadcrumbs)
- Buyout/holdco lens (risks, add-on adjacency, people moves)
- Portfolio risk lens (counterparty stress, enforcement, litigation)

5) Minimal workflow only as sensor/delivery (optional later)
Workflow is permitted only when it improves:
- Data quality (sensor)
- Adoption (delivery)
But never becomes the main value prop.

### Wedge → OS progression (guiding arc)
- v0a (confirmed, building now): Direct government portal monitoring, starting with FCC's ICFS — entities + events → ranked screens + company timelines. Confirmed buyer, least competition, most buildable, no visible incumbent.
- v0b (pending, gated): UCC liens, court dockets/complaints, recording-office filings as a second module — built only once the customer confirms a live signal (Altice) is actually tradeable, not just interesting. Same engine, a second ingestion adapter.
- v1: Universe/watchlist ownership (user lists; Strata keeps them warm) — note: watchlist resolution is already part of the v0a architecture (resolve extracted entities against a watchlist or create pending entities), so this pulls forward partially rather than waiting for v1.
- v2: Lien-perfection analysis as a premium lens ("is this lien defective" — ties directly to recovery rates, not just monitoring that a lien exists)
- v3: Add internal sensors (calendar/inbox/notes) to fuse firm activity + market
- v4: Strategy tuning and (later) ML only once ontology + outcomes exist

(Updated 2026-06-16, documented 2026-06-23: news de-prioritized in favor of primary-source records — see `docs/decisions.md`, 2026-06-16. SEC/DOJ enforcement stays active; FreightWaves tabled. Architecture: one engine, two adapters — domain differences (ICFS vs. UCC) live only in ingestion. Moat is entity resolution + cross-source assembly, not the LLM.)

The compounding asset is the same throughout: the map + timeline + linking + evidence.

---

## 2) PoC (v0): Investor Intelligence Screen on a Thin Ontology Spine

### Goal
Build a minimal end-to-end Strata engine that converts a small set of public sources into:
1) a conservative entity + event timeline in a database, and
2) a ranked “screen” (Most Changed / Early Stress Proxies) and company pages (timelines).

This proves the spine:
raw article → cleaned text → extracted company + event → stored timeline → ranked screen.

### Product surface (v0)
- Screen: “Most Changed (7d)” (ranked list of events/companies)
- Company page: “timeline with evidence links”
- Optional: export the screen to markdown/PDF if helpful, but the product is the screen.

### Data sources (v0)

Active:
- SEC press releases / litigation releases / administrative proceedings (RSS)
    - https://www.sec.gov/about/rss-feeds
        - Press Releases: https://www.sec.gov/news/pressreleases.rss
        - Litigation Releases: https://www.sec.gov/enforcement-litigation/litigation-releases/rss
        - Administrative Proceedings: https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss (PDFs)
- DOJ press releases (RSS / Office of Public Affairs topics)

Tabled:
- FreightWaves — was the original v0 bootstrap source; not aligned with the primary-source/credit wedge (see `docs/decisions.md`, 2026-06-16).

Primary-source buildout (new focus — validated by the first customer conversation, see `docs/customer_conversations/`):

Confirmed, building now:
- FCC ICFS (International Communications Filing System) — satellite earth stations, satellite space stations, international Section 214 authorizations, submarine cable landing licenses, Section 310(b) petitions, signaling point codes, foreign carrier affiliation notifications, and related SB/OIA-regulated filings. First target: a real customer manually checks this portal today and calls it "impossible to navigate."
- FCC RSS (dockets, rulemakings, commissioner statements) — displaces a law-firm subscription a real customer pays for today.

Pending, gated on customer confirmation (second module, not yet started):
- UCC lien filings (state-level, starting with NY/DE Secretary of State)
- Mortgage / recording-office documents (county clerk records)
- Court dockets & complaints (PACER/CourtListener-style sources)

Rationale: news framed as the primary signal was the wrong wedge. Credit/special-sits buyers care about lien perfection, coordinated subsidiary asset movement, and government-portal monitoring that's currently manual and painful — news is secondary context, not the product. See `docs/decisions.md` (2026-06-16) for the full rationale.

### Core data model (4 tables)
Note: v0.1 adds a conservative canonicalization layer: `canonical_entities` + `entity_links`.

#### `news_articles`
- id (uuid, PK)
- source_name (text) — e.g. 'sec', 'doj', 'freightwaves'
- external_id (text, nullable) — e.g. release number or hash(url+title)
- url (text)
- published_at (timestamptz)
- title (text)
- raw_html (text)
- clean_text (text)
- created_at (timestamptz)

Indexes:
- unique(source_name, external_id) when external_id exists; else unique(url)

#### `extracted_entities` (companies only in v0)
- id (uuid, PK)
- extracted_name (text)
- entity_type (text, nullable)
- jurisdiction (text, nullable)
- legal_name_normalized (text, UNIQUE)
  - lowercased, punctuation stripped, spaces normalized
  - keep suffixes like inc/llc/corp here
- loose_name_normalized (text)
  - same but drop corp suffixes; search only (NOT uniqueness)
- created_from (text) — 'news'
- first_seen_at (timestamptz)
- last_seen_at (timestamptz)

Policy:
- Conservative linking: strict match on legal_name_normalized only (v0).

#### `extracted_events`
(one row per article/entity pair)
- id (uuid, PK)
- article_id (uuid, FK → news_articles.id)
- entity_id (uuid, FK → extracted_entities.id)
- extracted_name (text) — as extracted
- is_primary_entity (boolean)
- event_type (text)
  - examples: enforcement, legal_action, restructuring, shutdown, mna_transaction, financing
- transaction_role (text, nullable) — buyer | seller | target | advisor | null
- event_date (date, nullable)
- event_description (text)
- confidence (numeric 0–1)
- created_at (timestamptz)

Indexes:
- (entity_id, created_at)
- (article_id)

#### `entity_identifiers` (optional, future-proof)
- id (uuid, PK)
- entity_id (uuid, FK → extracted_entities.id)
- id_type (text) — sec_cik, website_domain, etc.
- id_value (text)
- created_at (timestamptz)

### Pipelines (v0)

#### A) Ingestion
Input: RSS items → (url, title, published_at)
Steps:
1) Fetch HTML via HTTP.
2) Extract clean text via HTML-to-text extractor.
3) Insert into news_articles (dedupe by external_id/url).

#### B) Extraction (LLM → JSON → DB)
For each unprocessed news_articles row:
1) Prompt LLM to return JSON:

```json
{
  "entities": [
    {
      "entity_name": "...",
      "raw_mentions": ["...", "..."],
      "is_primary_entity": true,
      "event_type": "...",
      "transaction_role": null,
      "event_description": "...",
      "event_date": "YYYY-MM-DD or null",
      "confidence": 0.0
    }
  ]
}
```

For each extracted entity:

- compute legal_name_normalized and loose_name_normalized

- upsert extracted_entities by legal_name_normalized (strict)

- insert extracted_events

#### C) Canonicalization (conservative linking)
For each extracted_entity:
- Link to a canonical_entity using strict legal_name_normalized + jurisdiction when present.
- If jurisdiction is missing, link on legal_name_normalized with lower confidence.
- If ambiguous, create a new canonical_entity.
- Store link in entity_links with confidence + method.

Gating:

- Only insert extracted_events if confidence >= threshold (default 0.6).

Everything must be source-backed (url, date, title stored).

#### D) Screen + company timeline queries

“Most Changed (7d)” ranked list:

- rank by event_type weights + recency
- optional: multi-source confirmation boosts score

Company page:

- list events in reverse chronological order with source links

### Definition of done (PoC)

PoC is done when:

- Ingestion pulls ~50–200 items into news_articles (clean_text populated).
- Extraction populates entities + extracted_events with acceptable cleanliness.
- Screen query produces a ranked list for last 7 days.
- Company timeline query works for any entity.

### Quality bars

- Prefer false negatives over false positives.
- Conservative entity merging: strict match only.
- Outputs must be evidence-backed (links + dates).
- No claims beyond retrieved sources.

---

## 3) Customer Profile (v1 ICP) — Investor Intelligence OS

### Primary ICP

Primary ICP: opportunistic credit teams (small pods) that need ranked attention + evidence-backed company timelines to monitor themes/watchlists and surface emerging situations.

Secondary ICP: distressed/special sits funds and special situations PE, as a heavier “process/courts/UCC” lens later.

### Not primary (for this identity)

ABL lenders / factors / MCA operators as the primary ICP

They care deeply about UCC, but often pull product toward ops/workflow needs.

### Job-to-be-done (what they buy)

“Keep my universe warm: show me what changed, what matters, and why, with evidence and a clean timeline per company.”

### What “win” looks like

- They check Strata to orient quickly (daily/weekly).
- They surface a small number of names worth a second look faster than before.
- They reduce misses (early warnings) and reduce time-to-triage.

---

## 4) Outreach Script (discovery-first, low-commitment)

### Target titles

- Portfolio Manager, Credit / Opportunistic Credit
- Head of Credit
- Special Situations PM / Distressed PM
- Director / Head of Credit Research (good discovery; may not be budget owner)
- At FOs: credit PM (preferred), sometimes CIO as gatekeeper

### Core message (PM / investor)

Subject: Early signal screen for watchlists / themes

Body:
I’m building a small intelligence tool for opportunistic credit/special sits. It watches a universe (watchlist or theme) and surfaces the most important changes using public signals (enforcement/legal/news now; UCC later), with evidence links and a clean event timeline per company. I’m trying to sanity-check which signals actually matter and what a “no false positives” bar looks like in practice. Open to a quick 20-minute call?

### Advisor variant (distribution intel)

Subject: Situation radar (signals → ranked screen)

Body:
I’m building a lightweight “situation radar” tool: it monitors a universe and surfaces emerging stress proxies with source links and a company timeline (enforcement/legal/news now; UCC later). I’d love 20 minutes to learn which signals you trust and how you currently spot situations early.

### What to ask on the call (minimum set)

- How do you currently source / triage new situations?
- Which public signals do you trust most (and least)?
- What false-positive rate is unusable vs acceptable for an “early proxy” screen?
- What is the smallest output that would create weekly value?
- ranked list, alerts, company timelines, exports, etc.
- What tools are you currently paying for (Reorg/Debtwire/9fin/UniCourt/etc.) and what’s missing?

## 5) Adjacent Ideas (Captured, Not Driving v0)

Strata’s v0 wedge remains: public signals → entity/event spine → ranked screens + company timelines (credit/special sits ICP).

The following are explicitly captured as later-stage options, so they do not derail v0 execution:

### A) VC / Startup Ontology Lens (Stage 4+)
Idea: a startup/company + people + relationship ontology that helps VCs discover who to meet and what is emerging.

Why it’s on-path:
- It uses the same ontology spine (entities, events, relationships, time).
- It becomes compelling once Strata has proven ranking + explainable narratives and can personalize via internal sensors.

Why it is not a v0 wedge:
- Risks drifting into “PitchBook-lite” and long sales cycles / high noise interest.
- Requires either uniquely comprehensive coverage or personalization to a firm’s activity to be defensible.

When to revisit:
- After v1/v2 proves a paid ICP and a reliable ranking surface.
- As a lens (“Opportunity Discovery”) sold on top of the same spine.

### B) Text-Based Scheduling / Calendar Assistant (Stage 3 sensor, not identity)
Idea: a lightweight scheduling tool (text → calendar invite) for investors.

Role in Strata:
- A sensor to ingest meeting metadata (who met whom, when, topic) to improve relationship memory and attention ranking.
- Not a standalone product identity.

Why it is not a v0 wedge:
- Pulls the company toward workflow/utility.
- Can become its own company; high risk of distraction.

When to revisit:
- Once the ontology spine exists and Strata needs internal data to personalize ranking and memory.

### Sequencing rule (anti-drift)
If an idea does not strengthen the ontology spine or improve ranked attention + evidence for the current ICP, it is captured as a “later-stage lens/sensor” and does not enter v0 scope.
