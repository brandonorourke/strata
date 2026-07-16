-- Auth & accounts core (v1). See docs/auth.md for the full model + rationale.
-- Invite-only B2B: marketing → access_requests → operator invites → user.
-- organizations = tenant/firm; users belong to one org; sessions are server-side
-- (opaque cookie → row here, revocable); invitations convert a requester into a user.
-- All additive: 4 new tables + 2 columns on access_requests. Safe to deploy code before/after.
--
-- Requires migration 0050 (access_requests) first — invitations FKs to it. Written
-- idempotently (IF NOT EXISTS) so it's safe to re-run after a partial/aborted apply.

-- ---------- organizations: the firm / tenant boundary ----------
CREATE TABLE IF NOT EXISTS organizations (
    id         SERIAL PRIMARY KEY,
    slug       TEXT NOT NULL UNIQUE,                    -- url-safe firm handle
    name       TEXT NOT NULL,                           -- firm name
    status     TEXT NOT NULL DEFAULT 'active',          -- active | suspended
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------- users: a person + their credential ----------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    org_id        INTEGER NOT NULL REFERENCES organizations (id),
    email         TEXT NOT NULL,                         -- unique case-insensitively (index below)
    name          TEXT,                                  -- set at invite acceptance
    password_hash TEXT,                                  -- NULL until the invite is accepted
    org_role      TEXT NOT NULL DEFAULT 'member',        -- owner | member
    is_staff      BOOLEAN NOT NULL DEFAULT FALSE,        -- TRUE = Strata operator (sees /admin)
    status        TEXT NOT NULL DEFAULT 'active',        -- active | disabled
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- case-insensitive uniqueness without the citext extension
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users (lower(email));
CREATE INDEX IF NOT EXISTS idx_users_org ON users (org_id);

-- ---------- sessions: server-side, revocable ----------
-- id = sha256 hex of the raw session token; the raw token lives only in the cookie.
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ NOT NULL,                   -- min(now+14d, created_at+90d), bumped on use
    user_agent   TEXT,
    ip           TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

-- ---------- invitations: convert a requester (or colleague) into a user ----------
-- token_hash = sha256 hex of the raw invite token; the raw token lives only in the invite URL.
CREATE TABLE IF NOT EXISTS invitations (
    id                SERIAL PRIMARY KEY,
    org_id            INTEGER NOT NULL REFERENCES organizations (id),
    email             TEXT NOT NULL,
    org_role          TEXT NOT NULL DEFAULT 'member',    -- owner | member
    token_hash        TEXT NOT NULL UNIQUE,
    invited_by        INTEGER REFERENCES users (id),     -- the operator, nullable
    access_request_id INTEGER REFERENCES access_requests (id),  -- funnel linkage, nullable
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at        TIMESTAMPTZ NOT NULL,              -- e.g. +14d
    accepted_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations (lower(email));

-- ---------- access_requests: promote from inbox to funnel head ----------
ALTER TABLE access_requests
    ADD COLUMN IF NOT EXISTS status     TEXT NOT NULL DEFAULT 'new',   -- new | invited | active | rejected
    ADD COLUMN IF NOT EXISTS handled_at TIMESTAMPTZ;
