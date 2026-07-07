# findings.md — Domain knowledge from reading real data

Empirical findings about how the sources actually behave. Each entry: the
finding, the evidence, the implication. Add entries when reality surprises us.

## FCC / ICFS

**DA-number gates fetchability, not signal.**
DA-numbered notices are fetchable via docs.fcc.gov/public/attachments/DA-{n}A1.txt;
non-DA notices sit behind Akamai on fcc.gov. But both DA and non-DA *satellite*
notices contain real dispositions (grants, surrenders, transfers) — verified by
document comparison (SES-02821 non-DA contained a 7-license Viacom fleet
surrender). Signal must be classified by **action type** (surrender, assignment,
transfer of control, granted-with-conditions), never by DA presence. For
ITC/international notices the DA/non-DA split *happens* to track signal
(non-DA ≈ queue receipts), but action-type is still the causal filter.
DA = "delegated authority" (bureau-level action), not "Declaratory Action."

**Notice families need family-aware parsing.**
At least four: ITC/international (ownership %, nationality, CFIUS/Executive
Branch referrals, PE ownership chains — the richest narrative), SAT/SES
satellite (technical grants + action-type events), TEL (214 authorizations,
discontinuances), SCL (submarine cable — prose extraction not yet implemented;
SCL notices are marked `signal_tier='unparseable'` and skipped rather than
retried, but no content is extracted). One extraction logic does not fit all.

**Filings are entity-indexed; notices are relationship-bearing.**
Querying filings by applicant name misses third-party relationships entirely.
Example: Intelsat operates TT&C earth stations for Viasat satellites — visible
only in notice narrative, never in a "applicant = Viasat" query. The notices'
real payload is entity-relationship edges (who operates for whom, who opposes
whom). LLM extraction isn't summarization — it's the only source of the
relationship graph. This powers the cross-entity signal use case ("event at A
matters to B").

**Surrenders can carry financial consequences (bonds).**
FCC space-station licenses carry escalating surety bonds ($1M+) payable on
default or surrender — so a surrender may be a money event, not just
regulatory housekeeping. CAUTION: bond regime applies to space-station
milestone enforcement, not all license types (earth stations generally
exempt). Verify per-instance before claiming.

**Contested proceedings are a structural signal.**
Detectable without LLM from pleadings data alone: distinct-filer count,
competitor-presence (filers who are applicants elsewhere — SpaceX/Kuiper
opposing Viasat), ex parte density, age-without-resolution. Batch-withdrawal
pattern also real: Viasat filed ~15 applications Dec 2021, withdrew 12 next
day — the survivors are the core contested asks.

**Withdrawal is ambiguous without context.**
Withdraw-and-refile = routine. Withdraw-with-no-refile, or long-pending-then-
quiet-withdrawal (SES-MOD-20220425-00400: 3.5 yrs pending, withdrawn Jan 2026)
= possible informal FCC pushback or dropped capability. Check for subsequent
refiling before classifying.

**ECFS/EDOCS APIs are the sanctioned programmatic path.**
Free api.data.gov key. EDOCS API (api2.fcc.gov) returns document indexes by
report number — likely closes the ~122-notice non-DA fetch gap without
fighting Akamai. NOT yet verified for full ICFS/satellite coverage — confirm
before building on it. ECFS also has RSS (Stas uses it).

## DoW contracts (war.gov)

**Daily award announcements back to July 2014; 2,957 releases ingested.**
Viasat appears in 25 (from $998M MIDS JTRS 2020 to $437M PTSG May 2026).
Date formats drift across eras (abbreviated vs. full month names) — tests pin
the variants. Raw HTML preserved for re-parsing.

**Award ceiling ≠ real value.**
IDIQ announcements headline the ceiling ($437.7M combined) but the obligated-
at-award amount ($150M) is the real near-term number, stated in the prose.
Extracting obligated-vs-ceiling is a core product differentiator (per Stas:
"you would have known the contract was smaller than the ceiling").

**Worse for multi-award IDIQs: one ceiling is shared across ALL awardees.**
The Andromeda IDIQ (Space Domain Awareness, awarded April 7 2026) lists **14**
companies — `FA8819-26-DB-001..014` (Anduril, Astranis, BAE, General Atomics,
Intuitive Machines, L3Harris, Lockheed, Millennium, Northrop, Quantum, Redwire,
Sierra Space, True Anomaly, Turion) — sharing ONE **$1,843,000,000** ceiling, with
only **$1,400,000 obligated at award** (total, ~$100K each). Our extractor stamps
the full $1.843B on every awardee line, overstating per-company value by ~4 orders
of magnitude (BUG — see `docs/to_build.md`). Detect via: multiple awardees +
sequential PIIDs in one announcement, "were awarded a **ceiling** $X", "**$Y
obligated at time of award**", "N offers received". Store obligated as the amount,
flag "1 of M · shared ceiling". This is precisely why the apparent "$1.8B Intuitive
Machines award" was a non-event for LUNR — it wasn't a real $1.8B win.

**Disclosure latency is real and documented.**
Viasat PTSG award: public on war.gov May 22, disclosed at earnings June 10
(~19 days). Fast intermediaries (Seeking Alpha → Bloomberg) caught it same-day
with unclear lag from source. Speed-to-primary-source is a tradeable edge.

## SAM.gov (opportunities)

**SAM's differentiated signal is the solicitation PIPELINE, not awards.**
For the Andromeda IDIQ, SAM carries the full pre-award trail under solicitation
`FA8819-26-RB-001` — Draft RFP (Oct 21–23 2025, "define, design, build… Space
Domain Awareness"), formal Solicitation (Jan 13 2026), Amendment 1 (Jan 27) — but
**no award notice at all**. The 14 awards (`…-DB-001..014`) appear only in DoW.
So the program was visible in SAM ~6 months before award, then SAM went silent for
the award itself. Implication: build screens on SAM's **forward pipeline**
(who's soliciting what, months ahead) — that's earlier and more differentiated than
award notices, which SAM often lacks and which are stale/misvalued when present.
Division of labor: **SAM = pipeline/solicitations; DoW (DoD daily digest) = awards.**

**PIID structure encodes the lifecycle: R = solicitation, D = IDIQ award.**
`FA8819-26-**R**B-001` (solicitation) → `FA8819-26-**D**B-0xx` (the awards). Same
office + FY (`FA8819`, 26); only the 9th type-code char flips R→D. Lets you link a
solicitation to its resulting awards by shared PIID base — the join key between
SAM's pipeline side and DoW's award side.

**Bidders are never disclosed — only winners, and sometimes a count.**
No bidder/offeror/vendor field exists in SAM data. Offeror identities are
source-selection confidential by rule; the public learns only who *won* (the
awardee, and for multi-award IDIQs the full winner list — Andromeda's 14 = the
field SF picked for SDA) and occasionally *how many* bid (offer count, present in
~0.1% of SAM award notices as free text; more reliable in the DoW digest — "32
offers received" for Andromeda). SAM's opt-in "Interested Vendors List" is a live
per-page feature, not in the bulk CSVs, usually empty — unreliable. Implication:
competitive intelligence = **winner history + pipeline** (derived from outcomes),
never a bidder roster; infer the likely competitive field from who historically
wins similar NAICS/programs.

**Bulk-CSV `PostedDate` is a full timestamp; the live-API `postedDate` is date-only.**
The FY20xx archived-opportunities CSVs carry precise posted timestamps
(`2026-07-02 22:30:52-04`); the Opportunities *search* API returns date only — the
precise instant is only on the notice page / unkeyed detail endpoint
(`/api/prod/opps/v2/opportunities/{id}`, hal+json). Matters for any timing analysis.
Reusable asset: `~/Downloads/sam_awards_FY20-26.parquet` — 485k award notices
(FY2020–2026) extracted from the bulk CSVs, DuckDB-queryable in seconds.

## Entity resolution

**Within-source collapse is safe; cross-source merge is human-gated.**
Single sources provide consistent entity strings (exact-name collapse works:
74 companies from 191+ ICFS mentions). Cross-source ("Viasat Inc, Carlsbad" in
DoW = ICFS Viasat?) is where false-merge risk concentrates, and false merges
corrupt the core product. Machines collapse within-source; a human gates
cross-source promotion. Staged, not permanent: LLM-proposes-with-confidence →
human-adjudicates-the-tail is the specced scale-up design.
