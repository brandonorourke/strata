"""Web-layer auth: session cookie, session lifecycle, and the current-user loader.

Pure crypto/policy lives in strata_core.auth; this module is the FastAPI/HTTP glue —
setting the opaque cookie, creating/destroying server-side sessions, and resolving a
request to a CurrentUser (sliding the idle window as it goes).

Gating is done in a single middleware in main.py (path-prefix based), which stashes the
resolved user on request.state.user for routes/templates to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from fastapi import Request, Response
from sqlalchemy import select, delete

from strata_core.db import AsyncSessionLocal
from strata_core.models import User, Session as SessionModel
from strata_core import auth

COOKIE_NAME = "strata_session"

# Don't write to the DB on every single request just to slide the window — only bump
# last_seen_at / expires_at when the last bump is older than this.
_SLIDE_THROTTLE = timedelta(minutes=10)


@dataclass
class CurrentUser:
    id: int
    email: str
    name: str | None
    is_staff: bool
    org_id: int
    org_role: str


# ------------------------------------------------------------------ cookie -----

def _is_secure(request: Request) -> bool:
    # behind Railway's proxy the real scheme is in x-forwarded-proto; localhost is http
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def set_session_cookie(response: Response, raw: str, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        raw,
        max_age=int(auth.SESSION_MAX.total_seconds()),  # browser hint; server expiry is authoritative
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# --------------------------------------------------------------- lifecycle -----

async def new_session_row(db, user: User, request: Request) -> str:
    """Create a session row for `user` in the caller's db (caller commits). Returns the
    raw token to hand to the cookie."""
    raw, token_hash = auth.new_token()
    now = datetime.now(timezone.utc)
    db.add(SessionModel(
        id=token_hash,
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=auth.session_expiry(now, now, is_staff=user.is_staff),
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    ))
    return raw


async def destroy_session(raw: str) -> None:
    """Delete the session row for a raw cookie token (logout)."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(SessionModel).where(SessionModel.id == auth.hash_token(raw)))
        await db.commit()


async def load_current_user(request: Request) -> CurrentUser | None:
    """Resolve the request's cookie to a CurrentUser, or None. Slides the idle window
    (throttled) and drops expired/invalid sessions."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None

    now = datetime.now(timezone.utc)
    sid = auth.hash_token(raw)
    async with AsyncSessionLocal() as db:
        sess = await db.get(SessionModel, sid)
        if sess is None or sess.expires_at <= now:
            return None
        user = await db.get(User, sess.user_id)
        if user is None or user.status != "active":
            return None

        # slide the idle window forward under the absolute cap, throttled
        if sess.last_seen_at is None or (now - sess.last_seen_at) > _SLIDE_THROTTLE:
            sess.last_seen_at = now
            sess.expires_at = auth.session_expiry(sess.created_at, now, is_staff=user.is_staff)
            await db.commit()

        return CurrentUser(
            id=user.id,
            email=user.email,
            name=user.name,
            is_staff=user.is_staff,
            org_id=user.org_id,
            org_role=user.org_role,
        )
