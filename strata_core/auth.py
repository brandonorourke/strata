"""Auth primitives (pure, framework-agnostic). See docs/auth.md.

Covers the parts shared by the API routes and the bootstrap seed script:
  - password hashing/verification (argon2id)
  - password policy (NIST 800-63B style)
  - opaque token generation + hashing (session ids, invite tokens)
  - session-expiry math (sliding 14d idle under a 90d absolute cap)

Cookie handling and the request→session dependency live in the API layer, not here.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

# ---------------------------------------------------------------- passwords ----

_ph = PasswordHasher()  # argon2id defaults are sound for interactive login

PASSWORD_MIN = 12
PASSWORD_MAX = 128


def hash_password(password: str) -> str:
    """Return an argon2id hash for storage in users.password_hash."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verify. False on any mismatch/malformed hash (never raises)."""
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the stored hash used weaker params than current defaults (rehash on next login)."""
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def validate_password(password: str, *, email: str | None = None) -> str | None:
    """NIST 800-63B-style policy. Returns an error message, or None if acceptable.

    Length-based, no composition mandates, no rotation. Rejects a tiny obvious-blocklist;
    a Have I Been Pwned breach check can be layered on later.
    """
    if len(password) < PASSWORD_MIN:
        return f"Password must be at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"Password must be at most {PASSWORD_MAX} characters."
    lowered = password.strip().lower()
    if lowered in {"password", "passphrase", "letmein", "changeme"}:
        return "That password is too common. Choose something less guessable."
    if email and lowered == email.strip().lower():
        return "Password can't be your email address."
    if len(set(password)) == 1:
        return "Password can't be a single repeated character."
    return None


# ------------------------------------------------------------------ tokens -----

def new_token() -> tuple[str, str]:
    """Generate an opaque token. Returns (raw, sha256_hex).

    Give `raw` to the client (cookie / invite URL); store the hash. A leaked DB then
    can't be used to mint sessions or accept invites.
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    """sha256 hex of a raw token — the value stored in sessions.id / invitations.token_hash."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- sessions -----

SESSION_IDLE = timedelta(days=14)   # sliding: extends on each use
SESSION_MAX  = timedelta(days=90)   # absolute: never slides past this
STAFF_IDLE   = timedelta(days=1)    # tighter defaults for operator sessions
STAFF_MAX    = timedelta(days=7)


def session_expiry(created_at: datetime, now: datetime, *, is_staff: bool = False) -> datetime:
    """Compute expires_at: min(now + idle, created_at + max).

    Call on login (created_at == now → now + idle) and on every authenticated request to
    slide the idle window forward without crossing the absolute cap.
    """
    idle = STAFF_IDLE if is_staff else SESSION_IDLE
    cap = STAFF_MAX if is_staff else SESSION_MAX
    return min(now + idle, created_at + cap)
