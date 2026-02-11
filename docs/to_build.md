# To Build

## Next

- Add an explicit ambiguity note on cluster detail pages (collisions are possible for same normalized name).
- Show lightweight disambiguation hints on cluster detail pages (article domains + HQ country/region mentions when present).
- Build the separate linking process to promote mention clusters into canonical entities when strong identifiers exist.
- Add a second LLM pass per top cluster to generate an evidence-backed brief: what happened, why it matters, what to watch.

## Done

- Parse SEC RSS feeds (press releases, litigation releases, administrative proceedings).
- Extract candidate website domains from `raw_html` and store as suggestions (not authoritative).
