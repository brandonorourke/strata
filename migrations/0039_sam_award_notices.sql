-- SAM.gov award-notice capture. A daily (pre-market) pull of SAM award notices
-- (ptype=a) so we can measure, per PIID, whether SAM published an award BEFORE
-- DoW announced it — the real-time latency thesis. See docs/sam_api.md.
--
-- Two timestamps matter and come from two different SAM endpoints:
--   posted_date   — date-only, from the keyed search API (/opportunities/v2/search)
--   published_at  — precise UTC, from the UNKEYED detail endpoint
--                   (/api/prod/opps/v2/opportunities/{notice_id}, hal+json).
--                   This is the exact "SAM went public" instant (e.g. SMIT
--                   N0002426D4308 = 2026-07-06T13:13:06Z = 8:13 AM EST).
--   sam_created_at— detail 'createdDate' (notice authored; usually a bit earlier).
--   fetched_at    — when OUR job first saw it. Preserved on re-pull (first-seen),
--                   so an overlapping-window incremental pull is idempotent.

CREATE TABLE sam_award_notices (
    id            SERIAL PRIMARY KEY,
    notice_id     TEXT NOT NULL UNIQUE,   -- SAM noticeId (hex; also the uiLink slug)
    piid          TEXT,                   -- award.number (contract PIID)
    piid_key      TEXT,                   -- normalized join key (matches dow_awards)
    awardee_name  TEXT,
    awardee_uei   TEXT,                   -- award.awardee.ueiSAM
    amount        NUMERIC,                -- award.amount
    agency_path   TEXT,                   -- fullParentPathName
    title         TEXT,
    posted_date   DATE,                   -- search API postedDate (date-only)
    published_at  TIMESTAMPTZ,            -- detail endpoint postedDate (precise); NULL until enriched
    sam_created_at TIMESTAMPTZ,           -- detail endpoint createdDate (precise)
    sam_url        TEXT,                  -- uiLink
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- OUR first-seen instant
    raw            JSONB                  -- full search-API record
);

CREATE INDEX idx_sam_notices_piid_key ON sam_award_notices (piid_key);
CREATE INDEX idx_sam_notices_posted_date ON sam_award_notices (posted_date DESC);
CREATE INDEX idx_sam_notices_uei ON sam_award_notices (awardee_uei);
-- rows still needing precise-timing enrichment from the detail endpoint
CREATE INDEX idx_sam_notices_needs_detail ON sam_award_notices (id) WHERE published_at IS NULL;
