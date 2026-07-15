# To Build

## IDIQ latent-capacity / live-competition watchlist (Brandon, 2026-07-11) — active workstream

The product (#4): analyst's tickers → the IDIQ vehicles those companies compete on →
competitive set + undrawn capacity (context) → live-monitor draws, resolved to who-won (signal).
Undrawn = "competition left to run on this vehicle," NOT a revenue forecast (see the Andromeda
phantom-ceiling trap below). Full design + the validated market-moving research: the plan doc
`~/.claude/plans/ticklish-noodling-penguin.md`.

**State as of 2026-07-11 (built):**
- `/coverage` grid (route `coverage_index`, `coverage.html`) — one row per confirmed company;
  exclusive latent (single-award active undrawn) · shared seats · recent draw; sortable + client
  filter; drills into `/company/{ticker}`. Nav section "Federal Contracts" (Coverage · DoW Releases).
- `/company/{ticker}` page — exclusive/shared split, draws, programs, definitive contracts.
- Data model in place: `usaspending_awards` (raw + enriched: ceiling/obligation/program/multi-award),
  `idiq_recipients` (UEI→ticker directory, human-curated via `mapping_status` candidate/confirmed/excluded).
- 10 tickers confirmed & 100% enriched: VSAT, AVAV, KTOS, MRCY, CMTL, DRS, LUNR, RKLB, RDW, BKSY
  (~11.6k awards). Pull: `apps/ingest/pull_usaspending.py --uei … --ticker XXX` (children-graph
  family expansion; `--discover-siblings` OFF — it's name-only/leaky, children catches the
  non-eponymous subs deterministically).
- Excluded the two divested-and-still-active stale-parent units (web-verified): **CAES Mission
  Systems** under KTOS (Kratos EPD → Ultra 2015 → CAES/Honeywell) and **Stellant PST** under CMTL
  (Comtech PST sold to Stellant Nov 2023). Standing guard: a `children` member that's non-eponymous
  + has awards since last year + is a known independent brand = divestiture-stale → verify/exclude.
- Finding: USASpending freshness is **agency-dependent** — civilian (NASA/FAA/FRA) is near-real-time
  (LUNR/RKLB show June draws); DoD hits the ~90-day wall (VSAT/KTOS/MRCY "recent draw" ~a quarter stale).

**Build order (tomorrow onward):**
1. **Company-table migration (`0048`)** — extend `canonical_entities` into the Strata-wide company
   table (`slug`, `ticker` nullable, `is_prime`, `is_public`, `kind`); add `idiq_recipients.company_id`
   FK; seed the 10 companies (fold `DISPLAY_NAMES` in `main.py` → rows); repoint `/coverage` + `/company`
   at `company_id`; regen snapshot. Kills the `DISPLAY_NAMES` hack; privates (Intelsat: `ticker=NULL`)
   and primes (`is_prime`, `kind='competitor'`) model cleanly. NOTE: `canonical_entities` (22 rows) is
   the *general/news* company table — NOT the ICFS backbone (that's `icfs_canonical_entities`, 1,545
   rows), so extending it is safe/additive. Do FIRST — everything downstream keys off a real company table.
2. **Retire the dead news pipeline.** Frozen since 2026-02-13. Park the 7 news scripts
   (`ingest_rss`→`fetch_html`→`clean_text`→`llm_raw`→`extract_domains`→`extract_entities`→`link_entities`),
   drop/retag the 1,611 `news_article` rows in `extracted_events` + 329 `news_articles` + 22 news
   `canonical_entities` rows, remove `articles`/`article_detail` templates + `NewsArticle` relationships.
   `link_entities.py` is the news writer INTO `canonical_entities` — retiring it leaves the table purely
   hand-curated companies. **Park-not-delete** where scripts import shared models (`link_entities`,
   `extract_icfs_entities`) or ICFS breaks. Do AFTER #1. (Distinct from build-order #5 below, which is
   the ICFS polymorphic-`extracted_events` refactor — different table, different consumer.)
3. **Wire DoW real-time draws into the pages.** Join prod `dow_awards` → parent vehicle via the
   `piid_key` columns (already present) → surface fresh draws ahead of USASpending's ~90-day DoD wall.
   Fixes the correctness gap above (DoD "recent draw" is stale). This is what makes draws-are-the-signal
   real for the core DoD names. Overlaps build-order #4 (program fuzzy-match → parent).
4. **Competitive-field / vehicle view** — `/coverage/vehicle/{id}`: full co-awardee set (tickers +
   privates) + draws timeline — the unique "live competition" screen. Co-awardee method validated
   (description-keyword search); feed discovered co-awardee UEIs back as watchlist candidates.
5. **Universe expansion — systematic, USASpending-bottom-up** (see decisions.md 2026-07-12). Build
   `apps/ingest/build_anchor_universe.py`: USASpending FPDS → roll UEI families up to companies →
   filter by size (family contract $) + sector (NAICS/PSC or DoD/USSF/intel agency) → annotate
   ticker + market cap (thin equity join) → materiality (contract $ ÷ mktcap) → rank → **anchors**
   (tradeable × material, small/mid) + **context** (mega-primes, privates, foreign — labeled, never
   dropped). Competitive field auto-discovers from anchors' vehicles. Sizing: ~700 contractors >$100M,
   ~40–70 tradeable anchors, ~100–250 competitive-field entities (privates/foreign included). Interim
   hand-seed still works via `pull_usaspending.py --uei … --ticker XXX` (resolve parents via
   `/api/v2/recipient/`, feed ALL parents, confirm by flipping `mapping_status`, exclude divestiture-
   stale). **Demo starter list for Stas is ready now** (10 confirmed + ~25 more, see session notes).
6. **Draws monitor + alerts** — endgame: a new draw on a watched vehicle → `Alert` (reuse `Alert`/
   `AlertState`/`emit_alerts` pattern). This is the layer a trader actually pays for.
- Later: materiality lens (capacity ÷ mktcap/revenue — separates "big number" from "moves the stock");
  formal `idiq_vehicles`/`holdings`/`draws` tables only if deriving from `usaspending_awards` strains.

**DoW extractor QA — surface source paragraph in the UI (2026-07-12).** Show each `dow_awards`
row's **`source_excerpt`** (the paragraph it was extracted from) inline with its extracted
`awardees`/PIIDs on the `/admin/dow/contracts` card, so extraction drops (e.g. the multi-PIID-paren
bug — one paragraph → one row → PIIDs as `awardees[]` entries, one per PIID) are eyeball-obvious and
paragraphs can be copied straight into `tests/fixtures/dow/`. Turns the DoW screen into a
fixture-harvesting tool. Check first whether `source_excerpt` is the FULL paragraph or truncated — if
truncated, store the whole paragraph. Related: re-extract the ~55 releases with multi-PIID parens (run
the fixed regex over the corpus for the exact list) to recover dropped order/vehicle PIIDs — writes to
prod `dow_awards` (where the scheduler populates it), so confirm target first. Tests landed:
`tests/test_dow_extractor.py` (13, green) — grow from the fixture corpus.

**Commercialization (when it's paid).** The edge is proven but DISCRETIONARY (systematic version
tested dead; discretionary edge real + tail-managed — the Viasat/PTS-G May-22 case). The gate to
"paid" is a LIVE signal: today the data is ~90-day-stale for the DoD names that matter, so it's
research, not a sellable edge. Sequence:
- **Design partner (weeks)** — after #3–5 (real-time DoD draws + vehicle view + fuller universe): a
  genuine daily tool for one trader (Stas). Handshake/friend-price.
- **First paid seat (1–3 months)** — after #6 (alerts) + one live, attributable "surfaced → traded →
  paid" win. Partly calendar-gated (draws happen at some frequency), not just code-gated.
- **Small SaaS (several months)** — multi-user + self-serve coverage config + reliability + materiality.
- Pricing = research/data subscription (NOT auto-signal — edge is discretionary), niche event-driven /
  special-sits defense small-cap desks, low-thousands/seat. Selling point: 100% public data → no MNPI.
  Moat = the resolution pipeline (F→D parent, UEI-family + stale-parent handling, real-time DoW) +
  curated competitive graph. Real gate isn't a feature — it's accumulating live proof points.

## Build order (Brandon, 2026-07-07) — current priority

1. **Alerts for Stas: Viasat + Intelsat on new ICFS filings + DoW awards.**
   Mostly BUILT — `apps/ingest/emit_alerts.py` already has `WATCHLIST=["Viasat","Intelsat"]`,
   `detect_dow` (watchlist DoW awards) and `detect_icfs` (watchlist ICFS filings), Resend
   delivery, freshness guard, and `alert_state` watermarks. Remaining work:
   (a) flip `ALERT_ALL = True` → `False` (it's in end-to-end test mode, alerting on everything);
   (b) add Stas to `ALERT_TO` (currently just bcorourke@gmail.com — need his email);
   (c) verify end-to-end on a real watchlist hit.
2. **Fix DoW obligated-vs-ceiling extraction.** THE data-quality fix (see the ceiling
   mis-attribution bug below). Extract the obligated amount from the DoW prose
   ("$X are being obligated at time of award") instead of stamping the ceiling; flag
   shared multi-award IDIQs ("1 of M"). **Method: classify amount TYPE with the LLM**
   (obligated / ceiling / other — e.g. not-to-exceed, cumulative, "if all options
   exercised"), regex as cross-check — not regex-signal alone. DoD prose varies too much
   for regex to reliably separate the figures; fold amount-type classification into the
   v2 extractor's existing per-release LLM call, keep regex authoritative on the numerals.
   Fixtures: Andromeda ($1.843B ceiling / $1.4M
   obligated / 14 awardees) and PTS-G ($437.7M / $150M / Viasat+Intelsat). Delivers the
   obligated-vs-ceiling differentiator in real time — no USASpending needed (the number is
   in the announcement text). USASpending deferred: it's the deterministic-but-lagged
   backfill/confirmation layer, not a near-term build (progressive lag: ~15–20% at
   award-day → ~71% over months; the real-time obligated $ comes from DoW prose).
3. **Confirm alerts cover ACTIONS, not just filings.** GAP: `detect_icfs` currently fires
   only on new `icfs_filings` rows. A new *action* on an existing watchlist filing
   (modification / `action_taken_date` change in `icfs_filing_action_history`, or a new
   pleading) would NOT alert. Add detection over action history + pleadings for watchlist
   entities. (Same subsystem as #1 — bundle them.)
4. **Program fuzzy-match for DoW contracts → possible parent program.** Heuristic linkage
   of a bare delivery order to its parent vehicle/program, real-time. Candidate generation:
   office (PIID[:6]) + type=D (IDIQ vehicles only — the real reducer) + awardee name;
   disambiguate multi-vehicle primes with program-title + NAICS/PSC + timing (NOT amount —
   amount doesn't identify the parent). Frame as **"possible parent program"** with a
   confidence tier (confirmed/likely/possible/unresolved) + the matching basis; gate the
   ambiguous tail (big primes, e.g. Lockheed 8 vehicles in one office). Deterministic cases
   handled separately and already partly done: modifications (strip `-P00xxx` suffix, already
   in `_piid_key`) and slash-pairs (`parent/order`). USASpending confirms the heuristic later.
5. **Retire `extracted_events`/`extracted_entities` for ICFS? — scope first, do LAST.** The
   **polymorphism** is the vestige: built as an any-source layer (news first), but news is dead and DoW
   uses its own `dow_awards` tables, so **ICFS is the only consumer left**. NOT a clean delete, though —
   those tables also (a) hold the LLM enrichment (`signal_tier`, `summary`, `signal_reason`,
   `source_excerpt` on notice events — not in source tables), (b) power the entity timeline
   (`/admin/icfs/entity`) + signals feed (`/admin/icfs/signals`), (c) carry entity resolution
   (`extracted_entities` → `icfs_canonical_entities`). Removing = relocate the enrichment (→ source tables
   or a dedicated `icfs_notice_analysis` table) + rewrite timeline/signals to read source tables directly
   (dated by live columns — migration 0040/0041 direction) + keep canonical-entity resolution. Multi-day
   refactor; map every consumer first. Motivating symptom (`event_date` stale copy) is already worked
   around by reading live dates, so nothing's on fire. Slot after #2/#4/email.

## Next (immediate, in order)

1. **Apply pending migrations to prod** (0031–0035 not yet on Railway; 0030 and below already applied):
   ```
   psql $RAILWAY_URL -f migrations/0031_dow_contract_releases.sql
   psql $RAILWAY_URL -f migrations/0032_dow_raw_html.sql
   psql $RAILWAY_URL -f migrations/0033_dow_awards.sql
   psql $RAILWAY_URL -f migrations/0034_dow_award_purpose.sql
   psql $RAILWAY_URL -f migrations/0035_dow_awards_v2.sql
   ```
   After applying, sync DoW data: `pg_dump strata --no-owner --no-acl --data-only -t dow_contract_releases -t dow_awards | psql $RAILWAY_URL`

2. ~~**Fix `ingest_icfs.py` incremental to add second pass by `action_taken_date`**~~ — **DONE.**

3. ~~**Set up Railway crons**~~ — **DONE.** `scheduler.py` deployed as a Railway worker: full ICFS pipeline at 03:00 UTC daily + DoW window poller (90s cadence 4:55–5:20 PM ET, 7 min 5:20–6:30 PM ET, evening sweep at 8 PM ET).

4. **Alerting for SAT-PPL-20211207-00172** — Stas asked for this specifically. Watch for new filings/actions/pleadings where `file_number = 'SAT-PPL-20211207-00172'` and send an email when something new appears. Needs: a `watched_file_numbers` table or config, a check script that runs after each ingest, and an email send (sendgrid or SMTP).

## DoW extraction (redesigned v2 — regex-primary + LLM semantic; full corpus run needed)

Extractor: `apps/ingest/extract_dow_awards_v2.py`. Regex owns the award list (PIIDs,
city/state, amounts, completion date, contracting activity); one LLM call per release
supplies semantic fields (company name, purpose, program_hint, action_type) and an
independent PIID enumeration. Merge is regex-authoritative, joined on a normalized PIID
key; `awardees[*].pairing_confidence` = `agreed` | `regex_only`. `llm_only` PIIDs are
logged/stored in `llm_raw_response.llm_only_piids` as a regex-brittleness research signal.
Spec: `docs/specs/dow_extraction.md` (rewritten for v2). Enrichment design (next major
build): `docs/dow_enrichment.md` — 3-lane PIID enrichment (SAM live / SAM CSV / USASpending),
71% backfill vs ~15–20% real-time coverage (progressive-enrichment model), F-type parent ladder.

Schema: PIID is embedded per awardee (`awardees[*].piid`); the standalone `piids` column was
dropped in migration 0036. Unused 15-field-era columns remain but v2 never writes them
(`funding_at_award`, `instrument_type`, `pricing_type_raw`, `purpose_excerpt`, `flags`) —
candidates for a drop migration.

- **Run full corpus**: `python apps/ingest/extract_dow_awards_v2.py` — ~2,945 releases remaining (~$3, gpt-4o-mini). Apply migration 0036 to prod first.
- `--reprocess` re-runs regex + LLM for already-extracted releases (incurs LLM cost — not free like the old validator re-parse)
- After full run: SAM/USASpending enrichment keyed on PIID, then `dow_canonical_entities`
- **DoW UI next**: award-level table — columns: Date, Awardee (raw), PIID, Amount, Purpose, Activity, Confidence

**PLANNED — move semantic extraction to per-paragraph LLM calls (2026-07-14).** Replace the
single full-body LLM call per release with **one small LLM call per regex-parsed award**, fed
that award's own paragraph. Regex stays authoritative for the award *list* (unchanged); only
the semantic fields (purpose, program_hint, action_type, company_name) move to per-paragraph.
- **Why:** asking the LLM to enumerate a whole release doesn't scale to long ones. Evidence
  from the corpus (all `finish_reason=stop`, modest output tokens — **not** truncation): release
  155 has 86 regex awards but the LLM enumerated only **48** (it satisfices and stops listing);
  release 59's LLM enumerated all 22 but **13 didn't PIID-match** the regex awards, so their
  purpose never merged. Net ~4.5% of awards (124/2,779) lack purpose, heavily concentrated in
  the long releases.
- **Two failure modes, both fixed by per-paragraph:** (a) under-enumeration on long lists →
  gone, since one paragraph = one call; (b) fragile PIID-match merge → gone, since purpose
  attaches **by paragraph position**, not by matching PIIDs. Release 155 goes 42-missing → 0.
- Keep the independent full-body enumeration ONLY as an optional QA gap-flag (`llm_only` PIID
  detection), or drop it.
- Cost: N small calls per release instead of 1 big — more calls, each tiny (gpt-4o-mini).
- **Prereq:** the per-paragraph call must be fed the FULL paragraph, so the `source_excerpt`
  `para[:600]` cap must be lifted first (else we'd feed the LLM truncated text — the exact bug
  the full-body path avoided). See the source-excerpt cap note above.

## DoW multi-award IDIQ ceiling mis-attribution (BUG — investor-facing, priority)

The extractor stamps a **shared program ceiling** onto each awardee individually, massively
overstating award value on the `/dow` screen. When one DoD announcement lists multiple
awardees sharing a single IDIQ ceiling, that ceiling is NOT per-awardee — the real value is
the small **obligated-at-award** figure. `docs/findings.md` already notes "ceiling ≠
obligated," but the extractor doesn't act on it. Same trap exists in SAM data (e.g. NSNS
$4.8B shared across 5+ awardees).

**Fixture — the Andromeda award (announced April 7, 2026):** 14 companies (Anduril
`FA881926DB0011`, Astranis `DB013`, BAE `DB006`, General Atomics `DB008`, Intuitive Machines
`DB014`, L3Harris `DB003`, Lockheed `DB004`, Millennium `DB005`, Northrop `DB001`, Quantum
`DB002`, Redwire `DB012`, Sierra Space `DB007`, True Anomaly `DB009`, Turion `DB010`) share
ONE `ceiling $1,843,000,000` FFP IDIQ; only **$1,400,000 obligated at award** — total, across
all 14 (~$100K each). Strata's DoW screen showed `Intuitive Machines · FA881926DB014 ·
$1,843,000,000 · award` — overstating IM's real obligation by ~4 orders of magnitude, which
is exactly why the stock didn't move (it wasn't a $1.8B win). This mis-attribution is what
derailed a whole tradability analysis — the "material award" was a phantom ceiling.

**Fix:** detect multi-awardee shared-ceiling announcements. Signals in the DoD text: multiple
awardees + sequential PIIDs in one announcement, "were awarded a **ceiling** $X," "**$Y are
being obligated at time of award**," "N offers were received." Capture the obligated amount as
the awardee's amount; keep the ceiling separately; flag the row "1 of M · shared $X IDIQ
ceiling." This is a credibility fix for the screen investors actually see.

## Next (priority order)

- **Pleadings document text + LLM summary.** Pleadings show on entity timeline with type + file_number only; no content fetched or summarized yet. Need a `fetch_icfs_pleading_documents.py` + LLM pass analogous to the notice pipeline.
- **STA Grant PDF extraction.** `grant_doc_url` is now populated per Viasat filing (after `fetch_icfs_filing_details.py` runs). Fetch + extract text from those PDFs to summarize grant terms/conditions on the timeline.
- ~~**Remove Viasat hardcoding from `fetch_icfs_filing_details.py`.**~~ Already done — query runs for all filings with `detail_fetched_at IS NULL`.
- **Complete extraction pipeline after backfill.** Filings extraction done (13k rows). Pleadings backfill still running (~page 1105/5526 as of 2026-07-01). When done, run: `extract_icfs_pleadings.py`, `extract_icfs_notice_entities.py`, `extract_icfs_notice_summaries.py`. All scripts are incremental and safe to run at any time.
- **Non-DA notice documents (985 notices).** All 512 DA notices fetched and LLM-processed. The 985 non-DA SES/SAT notices were blocked on `www.fcc.gov` but the fix is confirmed: query `api2.fcc.gov/api/exp/v1.0.0/edocspublic/documents?reportNumber={number}` to get a record ID, then fetch `docs.fcc.gov/public/attachments/DOC-{id}A1.txt`. Tested against SES-02821 — works end to end. Needs a second fetch path in `fetch_icfs_notice_documents.py` for notices where `da_number IS NULL`.
- **Show Stas the signal events feed and entity timeline.** `/admin/icfs/signals` and `/admin/icfs/entity/{id}` are built. The signals page already surfaces CFIUS referrals, DIP context, transfers of control, and coordinated surrenders from just 5 months of data. Entity timeline will be most compelling once Viasat's historical SAT activity is in the DB (needs full backfill).
- **Tier 2 cross-source entity linking** (`icfs_canonical_entities` → global `canonical_entities`): deliberately deferred, human-gated, not built. See the semi-decision in `docs/decisions.md` (2026-06-23) for the design direction already agreed.
- **FRN as a stronger filer identity** than name-matching — mentioned early, never followed up. Worth revisiting once cross-source linking (Tier 2) actually needs a stronger identifier than exact name match.
- Minor cosmetic: `event_description` double-period when a company name already ends in one (e.g. "S.a.r.l..") in `extract_icfs_entities.py`/`extract_icfs_pleadings.py`/`extract_icfs_notice_entities.py`.
- **UCC/credit — pending second module, not yet started.** Gated on the customer confirming the Altice signal (coordinated subsidiary liens) is actually tradeable, not just interesting. Build only on a strong trade-relevant yes. If/when it's a go: UCC lien filings (state-level, starting with NY/DE), mortgage/recording-office documents (county clerk records), court dockets & complaints (PACER/CourtListener-style sources), then lien-perfection analysis as its own lens.
- Add an explicit ambiguity note on cluster detail pages (collisions are possible for same normalized name).
- Show lightweight disambiguation hints on cluster detail pages (article domains + HQ country/region mentions when present).
- Add a second LLM pass per top cluster to generate an evidence-backed brief: what happened, why it matters, what to watch.
    - Proof of concept for: AI synthesis of “friction over time” to answer: “What does this all mean?”
- The first sellable MVP for the first wedge (litigation finance or special situations or private credit portfolio monitoring)

## Marketing site — deploy to strataterminal.com (apex, no www)

Serve the marketing site on the **bare apex** `strataterminal.com` (no `www`) from **Railway**.
Blocker: Railway custom domains are **CNAME-only** (it hands you a CNAME + a TXT, no apex IP —
apex static IPs are an open Railway feature request), and **GoDaddy's DNS can't flatten a CNAME
at the apex**. So the apex can't point at Railway on GoDaddy DNS.

**Fix — move DNS (not the domain) to Cloudflare (free); keep GoDaddy as registrar:**
1. Railway → service Settings → Networking → add custom domain `strataterminal.com`; note the
   **CNAME target** + **TXT** it shows (TXT is required — missing it = 404).
2. Cloudflare → add `strataterminal.com` (auto-imports current records) → get 2 nameservers.
3. GoDaddy → change nameservers `ns43/44.domaincontrol.com` → the Cloudflare pair. (Registrar and
   renewal stay at GoDaddy; only DNS delegation moves.)
4. Cloudflare DNS → **CNAME at apex** → Railway's target (Cloudflare flattens it) + the **TXT** from
   Railway. **DNS-only (grey cloud)** so Railway terminates TLS. No `www` record.
- ⚠️ Before flipping nameservers, confirm any **email/MX records** carry into Cloudflare (moving NS
  moves all DNS) or mail breaks.
- Current apex is a GoDaddy Website Builder placeholder (A → 13.248.243.5 / 76.223.105.230) — replaced
  by the above.

## Pending cleanup

- **Run `apps/ingest/backfill_dow_raw_html.py` then delete it.** After the HTML backfill completes and all rows have `raw_html`, delete the script — `ingest_dow_contracts.py` stores `raw_html` on all new records going forward.

## Tabled

- FreightWaves ingestion — was the original v0 bootstrap source; not aligned with the primary-source/credit wedge for now.

## Done

- Parse SEC RSS feeds (press releases, litigation releases, administrative proceedings).
- Extract candidate website domains from `raw_html` and store as suggestions (not authoritative).
- ICFS v0: dedicated `icfs_filings`/`icfs_pleadings_and_comments`/`icfs_public_notices` tables, reverse-engineered live ingestion, polymorphic `extracted_entities`/`extracted_events` (any source, not just news), within-source canonical collapse (`icfs_canonical_entities`), and a working `/admin/icfs` UI — proven end-to-end on a small real-data slice, full backfill still running.
- ICFS notice intelligence pipeline: `fetch_icfs_notice_documents.py` (DA notices via `docs.fcc.gov`) → `extract_icfs_notice_entities.py` (file_number → company lookup, no LLM) → `extract_icfs_notice_summaries.py` (per-company prose slice + LLM structured output: `summary`, `signal_tier`, `signal_reason`, `source_excerpt`). First 149 events processed; 13/149 (~9%) classified signal. CFIUS referrals, DIP context, and transfers of control surfaced automatically.
- Signal events global feed (`/admin/icfs/signals`): all signal-tier notice events across all entities, most recent first, with LLM-generated reason badge. Entity timeline (`/admin/icfs/entity/{id}`): chronological feed of all FCC activity for one canonical entity — filings, pleadings, notice appearances with summaries. Notice detail page (`/admin/icfs/notices/{id}`): per-notice company list with summaries and collapsible source excerpts for hallucination verification.
- Site redesign (Stripe/Carta-inspired) and a real marketing landing page at `/`.
- **DoW contracts ingestion**: `ingest_dow_contracts.py` + `fetch_dow_html.py`, `dow_contract_releases` table with `raw_html` and `raw_text`, `/admin/dow` UI (release list + detail).
- **DoW window poller + daily scheduler**: `scheduler.py` — ICFS pipeline at 03:00 UTC + DoW window polling (90s/7min cadence 4:55–6:30 PM ET, evening sweep 8 PM ET), logged to `ingest_runs`.
- **DoW award extraction**: `extract_dow_awards_v2.py` — regex-primary (award list, PIIDs, city/state, amounts, dates, activity) + one LLM call per release for semantic fields (name, purpose, program_hint, action_type) and independent PIID enumeration. Regex-authoritative merge on normalized PIID key; per-awardee `pairing_confidence`. Superseded the LLM-only 15-field extractor (`extract_dow_awards.py`, deleted). PIID embedded per awardee; `piids` column dropped in 0036.
- **DoW UI**: `/admin/dow/contracts` — release list with per-award cards showing purpose, amounts, PIIDs, activity; collapsible raw text + LLM JSON.
