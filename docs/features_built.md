# Features Built

## 2026-01-28 — Most Changed (7d) screen (v0)
Summary: A credit-focused “Most Changed” screen that ranks canonical entities by recent, high-signal events.

Scoring definition:
- Window: `news_articles.published_at >= now() - interval '7 days'` (published_at only for inclusion).
- Event score:
  - `days_since = floor(extract(epoch from (now() - published_at)) / 86400)`
  - `recency_weight = 1.0 at day 0 → 0.25 at day 7` (linear, clamped to [0.25, 1.0]).
  - `base = type_weight * recency_weight`
  - `event_score = base * confidence_clamped` (confidence default 1.0, clamped to [0,1]).
- Duplicate suppression: per (canonical_entity, event_type), keep top N=2 events in the window.
- Entity score: sum of event_scores.
- Provisional penalty: `entity_score *= 0.8` if status = `provisional`.

Weights (credit-biased):
- bankruptcy: 6
- legal_action: 5
- regulatory: 5
- layoffs: 4
- leadership_change: 3
- disposition: 3
- financing: 2
- acquisition: 2
- mna_transaction: 2
- performance_update: 1
- other: 1

UI:
- `/screen` view shows name, status, score, claims count, source count, and top events.
- Canonical detail page shows timeline of linked events.
