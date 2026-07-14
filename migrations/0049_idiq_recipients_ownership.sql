-- 0049_idiq_recipients_ownership.sql
-- Persist the ownership-verify result on each recipient row so the UEI directory can show
-- a verdict inline and we don't re-run the web-search LLM every time. Written by
-- apps/ingest/scan_stale_parents.py (on-demand, over the review queue). `ownership_raw`
-- keeps the full LLM output for audit; the parsed fields drive the UI. All nullable /
-- appended — additive, backwards-compatible.

ALTER TABLE idiq_recipients
    ADD COLUMN ownership_verdict     text,         -- owned|divested|independent|jv|unknown
    ADD COLUMN ownership_confidence  text,         -- high|med|low
    ADD COLUMN ownership_as_of       text,         -- YYYY-MM (deal date)
    ADD COLUMN ownership_source      text,         -- citation URL
    ADD COLUMN ownership_rationale   text,         -- one-line reason
    ADD COLUMN ownership_raw         text,         -- full LLM message content
    ADD COLUMN ownership_model       text,         -- model used
    ADD COLUMN ownership_checked_at  timestamptz;  -- when verified
