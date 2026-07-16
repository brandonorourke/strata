#!/usr/bin/env python
"""Create an organization + user with a chosen password.

Bootstraps the first staff user (there's no invite for the first login), and doubles as
manual onboarding until the invite UI exists. Idempotent on the org (reused by slug).

Usage (local):
    python ops/create_user.py --email you@firm.com --name "You" \
        --org "Proofgraph" --org-slug proofgraph --staff

Prod (DATABASE_URL is inline + command-scoped; never echoed):
    DATABASE_URL="$PROD_DATABASE_URL" python ops/create_user.py --email ... --org-slug ...

Password: pass --password, or omit to be prompted (getpass, not echoed). Policy is enforced
via strata_core.auth.validate_password.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select, func

from strata_core.db import AsyncSessionLocal
from strata_core.models import Organization, User
from strata_core.auth import hash_password, validate_password


async def _run(args: argparse.Namespace, password: str) -> int:
    async with AsyncSessionLocal() as session:
        # reuse the org if the slug already exists, else create it
        org = (await session.execute(
            select(Organization).where(Organization.slug == args.org_slug)
        )).scalar_one_or_none()
        if org is None:
            org = Organization(slug=args.org_slug, name=args.org)
            session.add(org)
            await session.flush()  # assign org.id
            print(f"created organization '{org.name}' (slug={org.slug}, id={org.id})")
        else:
            print(f"reusing organization '{org.name}' (slug={org.slug}, id={org.id})")

        # reject a duplicate user (case-insensitive), matching the DB's lower(email) index
        email = args.email.strip()
        existing = (await session.execute(
            select(User.id).where(func.lower(User.email) == email.lower())
        )).scalar_one_or_none()
        if existing is not None:
            print(f"error: a user with email {email} already exists (id={existing})", file=sys.stderr)
            return 1

        user = User(
            org_id=org.id,
            email=email,
            name=args.name,
            password_hash=hash_password(password),
            org_role="owner",          # first user of a firm owns it
            is_staff=args.staff,
            status="active",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"created user {user.email} (id={user.id}, staff={user.is_staff}, "
              f"org_role={user.org_role})")
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Create an organization + user.")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--org", required=True, help="firm display name")
    p.add_argument("--org-slug", required=True, help="url-safe firm handle")
    p.add_argument("--staff", action="store_true", help="mark as Strata operator (sees /admin)")
    p.add_argument("--password", default=None, help="omit to be prompted securely")
    args = p.parse_args()

    password = args.password or getpass.getpass("Password: ")
    err = validate_password(password, email=args.email)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    return asyncio.run(_run(args, password))


if __name__ == "__main__":
    raise SystemExit(main())
