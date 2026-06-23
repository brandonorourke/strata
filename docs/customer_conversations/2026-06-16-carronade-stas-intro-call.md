# Carronade — Stas (intro call)

Date: on or before 2026-06-16 (exact call date not recorded; referral via Nina)

## Context

Outreach: Warm intro via Nina, pitched as "tracking entities, liens, and dockets across public records" — discovery framing, not a sales pitch. Follow-up after the call surfaced an Altice finding worth sending him.

## What he does

- Public credit (not private) + equities at Carronade. Syndicated/trades — e.g. $1M of a $1B loan.
- ~12 positions long-term, looking at 10-20 prospects (contrast: Citadel runs ~50 positions at a time).
- Uses Reorg Research and CreditSights. Has a Lexis subscription. Also aware of AlphaSense (acquired Sentieo).
- None of his tools do UCC monitoring.

## Key findings from the call

- **Lien perfection is the sharp, dollar-linked ask**: "Knowing if liens were perfected would be huge — it changes rates and recoveries." General unsecured claim vs. first lien is the distinction he cares about.
- **Talen Energy case study** (he's sending the deck): bought unsecured bonds on a credit where the lien wasn't perfected. Section 547(b) preference claim mechanics — a transfer of a security interest within 90 days of bankruptcy (1 year for insiders) can be clawed back, *unless* it falls under the Section 547(c)(3)(B) 30-day safe harbor for new financings. On Dec 14, 2021, Talen closed an $848M first-lien "Accordion Facility"; the mortgage on Susquehanna wasn't filed until Feb 8, 2022 — 56 days later, outside the 30-day safe harbor, a potential preference. Source: Open-End Mortgage Assignment of Rents Security Agreement and Fixture Filing, Luzerne County Clerk of Records.
- **Altice**: he pulled NY UCC data and found several subsidiaries (Altice Real Estate Corporation, Samson Cablevision, A-R Cable Services, and others) all granted all-asset liens to JPMorgan on the same day (Nov 25, 2025), then all got debtor-change amendments on Feb 12, 2026. The real-estate entity's lien was filed as a transmitting utility, suggesting network infrastructure. He has a credit position in Altice and it's on the cusp of bankruptcy with asset movement — but he hasn't done this kind of manual lien analysis in a decade, because it's outside his core skill set (legal, not fundamental analysis).
- **Government/regulatory monitoring is a second, separately-validated want**: he manually logs into the FCC docket and types "Viasat" (he holds an equity position there) to check for rulings. He called the FCC's other portal, ICFS (for space companies), "impossible to navigate" and a huge time sink. He wants FCC commissioner statements/rulings and DoD/DoW daily contract-award lists, especially for companies with pending RFPs (e.g. Viasat). He currently **pays a law firm** for FCC-commissioner/government intelligence — proven willingness to pay.
- Cited a recent example of regulatory-news alpha: an FCC ruling disallowing foreign-owned drone parts caused US drone makers' stock to jump ~20%; he's now looking at routers for the "next" version of that pattern.
- His framing of the core problem, unprompted: **"Information flow is overwhelming."**
- "Most credit analysts are fundamental, not legal" — he doesn't have strong legal/UCC instincts himself and thinks most of his peers don't either; said help on the legal/structural layer would be valuable to the broader market, not just him.
- Reorg's coverage, per him: has dockets, dials in for court hearings, has corporate structures/subsidiaries for covered companies, but doesn't do UCC/lien-perfection monitoring. Half the time hearing dial-ins aren't even sent out, and nobody distributes transcripts (Reorg sends a human reporter for big cases only).
- Sometimes goes directly to CourtListener himself when Reorg doesn't cover something.

## Open follow-ups (unanswered as of this call)

- Who buys at his firm, and budget — better on phone/in person.
- Exactly where/how he'd do credit analysis on a name like Altice himself (e.g. does he search Delaware filings specifically) — partially addressed by the follow-up email.
- How he actually finds out about asset-movement signals like the Altice one today.
- Whether a coordinated subsidiary move like the Altice one would normally hit his radar quickly through Reorg/another service, or take a while to surface, and whether it's "already widely known and not tradeable" — unresolved; this is the open question gating the UCC/credit module (see `docs/decisions.md`, 2026-06-16).
- Whether 9fin covers the registry/lien-perfection layer specifically, or just credit docs/covenants — unverified.

## Reference lists he prompted (not endorsements, just his stack/competitor awareness)

- UCC data tools: Baselayer, Middesk, Ondato, CSC, Wolters Kluwer (iLien)
- Dockets/courts: UniCourt, Docket Alarm, LexisNexis CourtLink, Trellis
- Competitors in his existing stack: Reorg, 9fin, CreditSights

## Referral

- Alap Shah (Citrini) — founded Sentieo (financial-research search), sold it to AlphaSense. Potentially advisor-grade given direct experience in an adjacent space and insight into where incumbent coverage stops.

## Signal assessment (ranked, most to least alpha)

1. Validated the core thesis unprompted — named "information flow is overwhelming" as his own framing, and confirmed none of his existing paid tools (Reorg, CreditSights, AlphaSense) do UCC monitoring.
2. Revealed behavior beats stated wants: he has a live position (Altice) where he knows he should do the lien analysis and isn't, because it's outside his skill set — not because it's unimportant. Observed, not claimed.
3. The wedge sharpened from generic "UCC monitoring" to lien-perfection specifically — tied directly to dollars via the Talen Energy trade.
4. The moat thesis, handed to him unprompted: most credit analysts are fundamental, not legal — that skill gap is the defensibility, not the data itself.
5. Proven willingness to pay: he already pays a law firm for FCC/government intelligence today. Displacing real spend beats hypothetical interest.
6. A second, more buildable wedge surfaced: FCC/government-portal monitoring (event-driven retrieval, not legal judgment) — became the candidate first build (see `docs/decisions.md`, 2026-06-16).
7. Free competitive map: Reorg / CreditSights / AlphaSense / CourtListener and the seams between them — especially the docket-transcript long tail nobody covers.
8. Warm referral: Alap Shah (Citrini / ex-Sentieo founder).
9. Market-sizing texture: his fund runs ~12 positions / 10-20 prospects vs. Citadel's ~50 — small-N, high-value-per-seat, long sales cycle shape.
10. ICP correction: he's public credit + equities, not private — broadens the buyer map to public credit traders, not just private originators.

**Caveats**: this is n=1 (one unusually broad, sophisticated buyer) — the recurrence test (via Citrini and others) is what converts this into a market signal. Pain was confirmed thoroughly; price was barely discussed — commercial mechanics (would he pay, how much, who holds budget) are the gap to close next.
