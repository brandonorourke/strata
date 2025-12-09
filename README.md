# Strata

### Quick start

We use Python 3.12

```bash
cd strata
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# create a local env file and database (values should match your Postgres setup)
cp .env.example .env  # adjust values inside if needed (PUBLIC_BASE expects a host, no scheme)
createdb strata_local || true
psql "$DATABASE_URL" -f db/schema.local.sql  # optional: load base schema snapshot

# Edit main.py:
#   - PUBLIC_BASE = "https://<your-tunnel>.trycloudflare.com"
#   - UID_DOMAIN  = "dev.kyn" (or "kyn.live" later in prod)
uvicorn main:app --reload --port 8000 --log-level info --access-log

# Optional: capture schema snapshot for reference
pg_dump "$DATABASE_URL" --schema-only --no-owner > db/schema.local.sql
```

### Database schema

- The canonical schema lives in `strata_core/schema.local.sql`. Load it into a fresh database with `psql "$DATABASE_URL" -f strata_core/schema.local.sql`.
- Ad-hoc SQL migrations (if needed) live under `db/migrations/` and should be applied manually in order.
- After changing the schema, rerun `pg_dump --schema-only --no-owner > db/schema.local.sql` so the snapshot stays current.

### Production environment

- Use `api/.env.example.prod` as a template for Railway variables. It includes the internal `DATABASE_URL`, `INVITE_DOMAIN`, `PUBLIC_BASE`, and `PORT=8000` so the health check works.
- Replace the placeholders (`[PWDGOESHERE]`, `[SIGNING_SECRET GOES HERE]`) with your actual values before adding them to Railway.

### Logging

- `uvicorn` prints HTTP access logs; running with `--log-level info --access-log` makes latency/status visible during dev.
- The FastAPI service also emits lightweight application logs (`invite_created`, `invite_response`, and request timing) so failures are easy to trace in both local runs and Railway.

---



## Repo layout

```
kyn/
  ios/                 # Xcode project (SwiftUI)
    KynApp/
      Kyn.xcodeproj
      Kyn/             # container app (stubbed for now)
      KynMessagesExtension/  # messages extension (the MVP UI)
        MessagesViewController.swift
        ComposeView.swift
        ContactPicker.swift
        Models.swift
        API.swift
  api/                 # FastAPI service (MVP)
    main.py
    requirements.txt
```

---

## Architecture (MVP)

1. **User flow**
   - In iMessage, the extension shows 2–3 suggested times + a **required** contact picker.
   - On **Insert**, it calls `POST /invites` and inserts the returned link into the chat.
   - Recipient taps link → **landing page** (no login) → **Accept** → downloads `.ics`.

2. **Backend**
  - `POST /invites`: writes invite data to Postgres; returns `link`.
   - `GET /t/{token.sig}`: landing page with Accept/Decline forms.
   - `POST /attendees/{id}/respond`: sets accepted/declined.
   - `GET /i/{invite_id}.ics`: generates `.ics` with **stable UID** and **SEQUENCE**.

3. **Identifiers**
   - **PUBLIC_BASE**: the clickable host (tunnel in dev, domain in prod).
   - **UID_DOMAIN**: forms the right side of `UID` in `.ics` (`<invite_id>@<UID_DOMAIN>`).  
     Keep **stable per environment** to avoid calendar duplicates.

---

## API (current)



## Git branching strategy

```
# Merge from develop
git checkout main
git pull --ff-only
git merge --no-ff develop -m "vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --tags   # This deploys to Railway so do any db migrations first (always backwards compatible)

# Sync develop forward with exactly what's on main
git checkout develop
git pull --ff-only
git merge --ff-only main     # <- fast-forward or fail
git push origin develop
```