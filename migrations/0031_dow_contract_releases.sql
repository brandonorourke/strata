CREATE TABLE dow_contract_releases (
    id             SERIAL PRIMARY KEY,
    article_id     TEXT NOT NULL UNIQUE,
    url            TEXT NOT NULL,
    title          TEXT,
    release_date   DATE,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched_at     TIMESTAMPTZ,
    raw_text       TEXT,
    content_hash   TEXT
);
