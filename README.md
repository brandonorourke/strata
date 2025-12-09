# Strata

### Quick start

```bash
cd strata
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# create a local env file and database (values should match your Postgres setup)
cp .env.example .env  # adjust values inside if needed (PUBLIC_BASE expects a host, no scheme)
createdb kyn_local || true
psql "$DATABASE_URL" -f db/schema.local.sql  # optional: load base schema snapshot

# Edit main.py:
#   - PUBLIC_BASE = "https://<your-tunnel>.trycloudflare.com"
#   - UID_DOMAIN  = "dev.kyn" (or "kyn.live" later in prod)
uvicorn main:app --reload --port 8000 --log-level info --access-log

# Optional: capture schema snapshot for reference
pg_dump "$DATABASE_URL" --schema-only --no-owner > db/schema.local.sql
```

Expose publicly (so iOS can open links):

```bash
# in another terminal
cloudflared tunnel --url http://localhost:8000
# note the printed https URL; set it as PUBLIC_BASE in main.py, restart uvicorn
```

Smoke test:

```bash
PUBLIC="https://<your-tunnel>.trycloudflare.com"
curl -s -X POST "$PUBLIC/invites" \
  -H 'content-type: application/json' \
  -d '{"organizer_name":"Brandon","title":"Thu 3:30–4 ET","duration_min":30,"option_iso":"2025-10-24T15:30:00-04:00","attendee":{"name":"Maya","phone":"+15551234567","email":null}}'
```

Open the returned `"link"` in a browser → click **Accept** → add the `.ics`.

### Database schema

- The canonical schema lives in `db/schema.local.sql`. Load it into a fresh database with `psql "$DATABASE_URL" -f db/schema.local.sql`.
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

### `POST /invites`
Create an invite (first time option only is used for MVP).

```json
{
  "organizer_name": "Brandon",
  "title": "Thu 3:30–4 ET",
  "duration_min": 30,
  "option_iso": "2025-10-24T15:30:00-04:00",
  "attendee": { "name": "Maya", "phone": "+15551234567", "email": null }
}

```

**200 OK**
```json
{
  "invite_id": "inv_XXXX",
  "link": "https://<PUBLIC_BASE>/t/<token>.<sig>",
  "ics_url": "https://<PUBLIC_BASE>/i/inv_XXXX.ics"
}
```

### `GET /t/{token.sig}`
HTML landing with **Accept** / **Decline**.

### `POST /attendees/{attendee_id}/respond`
Form POST (`application/x-www-form-urlencoded`):

- `action=accept` → returns HTML with `.ics` and Google “Add to Calendar” links  
- `action=decline` → returns a simple “Declined” page

### `GET /i/{invite_id}.ics`
`text/calendar` with:
- `UID: <invite_id>@<UID_DOMAIN>`
- `SEQUENCE: n` (increments on accept)
- `STATUS: TENTATIVE|CONFIRMED`

---

## Dev tips / troubleshooting

- **Tunnel changes each run**: update `PUBLIC_BASE` in `api/main.py` **and** `API.base` in iOS, then restart `uvicorn`.
- **Landing returns 404**: token invalid or invite deleted. Create a new invite.
- **“Cannot find type … in scope”**: ensure the file is in **KynMessagesExtension** target and clean build (⇧⌘K).
- **Generic parameter ‘T’ could not be inferred**:
  - Wrap `prefix/dropFirst` in `Array(...)` for `ForEach`.
  - Annotate `CheckedContinuation<Void, Error>` in the `MSConversation.insert` helper.
- **Contacts permission crash**: missing `NSContactsUsageDescription` in **extension** Info.plist.

---

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

---

## What’s intentionally **not** built yet

- User accounts (OTP), JWT/refresh, Keychain sharing
- Google/Outlook Calendar write
- DB persistence (Postgres)
- Universal Links (Associated Domains)
- Multi-recipient / reschedule / cancel / organizer UI

These come after we validate the **message-native** flow “clicks.”

---

## Roadmap (near-term)

1. **Polish landing:** organizer name, time zone labels, “already accepted” variant.
2. **Basic metrics:** in-memory counters + `/metrics` JSON (create → view → accept).
3. **Persistence:** swap to Postgres (invite, attendee, token tables).
4. **Reschedule/Cancel:** bump `SEQUENCE`, set `STATUS:CANCELLED`.
5. **Auth:** SMS OTP → access/refresh (JWT + opaque rotating refresh in shared Keychain).
6. **Universal Links:** `applinks:` + AASA to open links in-app when installed.

---

## Security notes (for when auth lands)

- Store **access+refresh** in **Keychain Sharing** (not App Group).
- Rotate refresh on every `/session/refresh`, with reuse detection.
- Server stores refresh tokens **hashed**, bound to `device_id`.
- JWT (`access_token`) short TTL (15–30m), with `iss`/`aud` claims.

---

## Contributing

- Keep extension views compact (< ~280pt) and snappy—network calls should be on **Insert** only.
- No blocking UI in the extension; use async/await and simple error states.
- Prefer **no JS** on landing; fast HTML wins for SMS/iMessage.

---

## License

MIT (add `LICENSE` file).

---

## Maintainer

- Brandon O’Rourke — `@brandonorourke`
