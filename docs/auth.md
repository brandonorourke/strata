# Authentication & accounts — data model (v1)

Status: **login + sessions + default-deny BUILT** (migration 0051 applied; `POST /login`/
`/logout`, session cookie, and the gating middleware are live). The whole product requires
login; public allowlist = `/`, `/login`, `/signup`, `/logout`, `/marketing`, `/health`,
`/favicon.ico`, `/invite/*`. `/admin` additionally requires staff. Post-login → `/coverage`;
root redirects by auth state (retires `landing.html`). **Invite flow: not yet built** (see end).
Supersedes the placeholder `/login` (`POST /login` returns a "not available yet" note) and
builds on `access_requests` (migration 0050), which becomes the top of the funnel.

## Principles / what shapes it

- **Invite-only, not open signup.** Funnel is `marketing → Request access → operator approves →
  invitation → user`. There is no public self-serve registration. So the model needs an
  **invitation** step, not an email-verify-on-signup flow.
- **Firms are the customer; users are people.** An `organization` is the tenant boundary. Screens
  are global today, but per-firm watchlists ("the names you hold") are coming, so users belong to a
  firm now to avoid a painful retrofit later.
- **Operator logs in through the same door.** Staff-vs-customer is a boolean (`is_staff`), not a
  second auth system. Staff additionally see `/admin`.
- **Sessions are server-side and revocable.** The cookie is an opaque claim-check; all state lives
  in the DB, so disable-user / log-out-everywhere / kill-a-leaked-session are instant.

## Decisions locked

- **Login method:** email + password (argon2id). Self-contained — an operator can seed a user by
  hand and login works day one. Magic-link / SSO deferred.
- **Tenant boundary:** `organizations` modeled now (thin), one org per user in v1.
- **Sessions:** server-side `sessions` table + opaque HttpOnly cookie. No JWT.

### Micro-decisions (defaults chosen — change if desired)

- **Email uniqueness:** case-insensitive via a functional unique index `lower(email)` on a plain
  `text` column — avoids the `citext` extension (consistent with dropping pg_trgm earlier).
- **Who invites:** in v1 **only staff** create invitations (operator-led onboarding). `org_role`
  (`owner|member`) is carried but mostly informational until firms self-invite colleagues; the
  first user of an org is `owner`.
- **Session lifetime:** **hybrid** — sliding idle window (14d) under an absolute ceiling (90d),
  using the existing columns (no extra field). On each use set
  `expires_at = min(now + 14d, created_at + 90d)`; a session is valid while `now < expires_at`.
  So a daily user stays logged in up to 90 days then re-auths; an idle session dies after 14 days.
  `last_seen_at` is bumped on use for visibility. Tune either window.
- **Password hashing:** argon2id via `argon2-cffi` (new dependency). bcrypt/passlib is the
  fallback if argon2 install is a problem.
- **Password policy (NIST 800-63B style):** the user *chooses* their password at invite
  acceptance (not generated); only the invite *token* is generated. Enforced server-side at
  accept + reset: **min 12 / max 128 chars**, all characters allowed (spaces/unicode/symbols),
  **no composition mandates**, **no forced rotation**. Reject a tiny blocklist now (`password`,
  the user's own email, single-repeated-char); add a Have I Been Pwned k-anonymity breach check
  later. Client-side shows a length hint; the server is the enforcer.
- **Token storage:** session + invite tokens are `secrets.token_urlsafe(32)`; the DB stores the
  **sha256 hash**, the raw value lives only in the cookie / invite URL.
- **Cookie flags:** `HttpOnly`, `SameSite=Lax`, `Secure` in prod (off on localhost http),
  `Path=/`. Opaque token → server-side lookup, so no cookie signing lib needed.

## Entities

```
organizations 1───* users 1───* sessions
                     │
access_requests *────* invitations ──1 users (invited_by)
      (funnel)         (org_id, access_request_id)
```

### `organizations`
| column      | type          | notes                                   |
|-------------|---------------|-----------------------------------------|
| id          | serial PK     |                                         |
| slug        | text uniq NN  | url-safe firm handle                    |
| name        | text NN       | firm name                               |
| status      | text NN       | `active` \| `suspended` (default active)|
| created_at  | timestamptz NN| default now()                           |

### `users`
| column        | type           | notes                                             |
|---------------|----------------|---------------------------------------------------|
| id            | serial PK      |                                                   |
| org_id        | int FK NN      | → organizations(id)                               |
| email         | text NN        | unique on `lower(email)` (functional index)       |
| name          | text           | set at invite acceptance                          |
| password_hash | text           | NULL until invite accepted                        |
| org_role      | text NN        | `owner` \| `member` (default member)              |
| is_staff      | bool NN        | default false — true → Strata operator, sees /admin|
| status        | text NN        | `active` \| `disabled` (default active)           |
| last_login_at | timestamptz    |                                                   |
| created_at    | timestamptz NN | default now()                                     |

### `sessions`
| column      | type           | notes                                            |
|-------------|----------------|--------------------------------------------------|
| id          | text PK        | sha256 of the raw session token                  |
| user_id     | int FK NN      | → users(id), ON DELETE CASCADE                   |
| created_at  | timestamptz NN | default now()                                    |
| last_seen_at| timestamptz    | bumped on use                                    |
| expires_at  | timestamptz NN | sliding: `min(now + 14d, created_at + 90d)`      |
| user_agent  | text           | best-effort context                              |
| ip          | text           | best-effort context                              |

Index: `sessions(user_id)` for "list/kill a user's sessions".

### `invitations`
| column            | type           | notes                                         |
|-------------------|----------------|-----------------------------------------------|
| id                | serial PK      |                                               |
| org_id            | int FK NN      | → organizations(id) — invite into which firm  |
| email             | text NN        | recipient                                     |
| org_role          | text NN        | `owner` \| `member` (default member)          |
| token_hash        | text uniq NN   | sha256 of the raw invite token                |
| invited_by        | int FK         | → users(id) (the operator), nullable          |
| access_request_id | int FK         | → access_requests(id), nullable (funnel link) |
| created_at        | timestamptz NN | default now()                                 |
| expires_at        | timestamptz NN | e.g. +14d                                     |
| accepted_at       | timestamptz    | set when the user completes signup            |

### `access_requests` (extend existing, migration 0050)
Add: `status text NN default 'new'` (`new` \| `invited` \| `active` \| `rejected`) and
`handled_at timestamptz`. Linkage to the invite is via `invitations.access_request_id`.

## Lifecycle

1. **Request** — visitor submits the marketing form → `access_requests` row, `status='new'`.
2. **Approve** — operator reviews. To admit: create the `organization` (if a new firm), then an
   `invitation` (random token, hash stored). Email the link `/invite/<raw_token>` (or paste it).
   Mark the request `status='invited'`.
3. **Accept** — recipient opens the invite link → sets name + password → `users` row created
   (`status='active'`, `password_hash` set, `org_role` from invite; first user of the org →
   `owner`). Set `invitations.accepted_at`, and the linked request → `status='active'`.
4. **Login** — `POST /login`: look up user by `lower(email)`, verify argon2 hash, check
   `status='active'`. On success create a `sessions` row, set the opaque cookie, bump
   `last_login_at`. Generic error on any failure (no user-enumeration).
5. **Authorize** — a FastAPI dependency reads the cookie → hashes it → loads the session (not
   expired) → its user (active). Gates the product; `is_staff` gates `/admin`. Bump `last_seen_at`.
6. **Logout** — delete the `sessions` row, clear the cookie.
7. **Revoke** — delete session rows for a user (log-out-everywhere) and/or set
   `users.status='disabled'` (blocks new logins; existing sessions die on next check if we also
   verify user status in the dependency — which we do).

## Deferred (noted, not in v1)

- Password reset / magic-link: a small `user_tokens(user_id, purpose, token_hash, expires_at,
  used_at)` table when transactional email is wired up.
- SSO / SAML (enterprise), API keys, multi-org membership (join table), 2FA, login rate-limiting
  and the marketing-form honeypot (spam hardening).
- Transactional email provider (for invites/resets) — until then, invite links are hand-delivered.

## New dependency

`argon2-cffi` (password hashing) → add to `requirements.txt`. Session/invite tokens use stdlib
`secrets` + `hashlib`; no JWT/signing library needed.

## Migration plan

- `0051_auth_core.sql` — `organizations`, `users`, `sessions`, `invitations`, functional unique
  index on `lower(users.email)`, and the `access_requests` `status` / `handled_at` additions.
- Models appended to `strata_core/models.py` (append-only, per repo convention).
- Regenerate `schema.local.sql` snapshot after applying.
- Forward-compatible: additive tables + additive columns on `access_requests`, safe to deploy
  code before/after independently.
