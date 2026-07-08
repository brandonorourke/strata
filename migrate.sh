#!/usr/bin/env bash
#
# Apply one numbered migration to local or prod. No state tracking — you name the
# migration, it shows you the SQL, then runs it (prod asks for confirmation first).
#
#   ./migrate.sh local 0040          # apply migrations/0040_*.sql to local
#   ./migrate.sh prod  0040          # apply to prod (PROD_DATABASE_URL) — confirms first
#   ./migrate.sh prod  0040 --show   # print the SQL only, run nothing (verify before)
#
# DATABASE_URL (local) and PROD_DATABASE_URL (prod) come from .env — never committed.
# Runs with ON_ERROR_STOP so a broken migration aborts instead of half-applying.

set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-}"; NUM="${2:-}"; MODE="${3:-run}"
if [[ -z "$TARGET" || -z "$NUM" ]]; then
  echo "usage: ./migrate.sh <local|prod> <number> [--show]"; exit 1
fi

# load .env (KEY=VALUE)
if [[ -f .env ]]; then set -a; . ./.env; set +a; fi

case "$TARGET" in
  local) URL="${DATABASE_URL:-}"; [[ -n "$URL" ]] || { echo "DATABASE_URL not set"; exit 1; } ;;
  prod)  URL="${PROD_DATABASE_URL:-}"; [[ -n "$URL" ]] || { echo "PROD_DATABASE_URL not set (add it to .env)"; exit 1; } ;;
  *) echo "target must be 'local' or 'prod'"; exit 1 ;;
esac
# psql wants postgresql:// not the SQLAlchemy postgresql+asyncpg:// form
URL="${URL/postgresql+asyncpg:/postgresql:}"

FILE=$(ls migrations/${NUM}_*.sql 2>/dev/null | head -1 || true)
[[ -n "$FILE" ]] || { echo "no migration matching migrations/${NUM}_*.sql"; exit 1; }

echo "── $FILE  →  $TARGET ──────────────────────────────"
cat "$FILE"
echo "───────────────────────────────────────────────────"
[[ "$MODE" == "--show" ]] && exit 0

if [[ "$TARGET" == "prod" ]]; then
  read -r -p "Apply the above to PROD? type 'yes': " ok
  [[ "$ok" == "yes" ]] || { echo "aborted"; exit 1; }
fi

psql "$URL" -v ON_ERROR_STOP=1 -f "$FILE"
echo "✓ applied $(basename "$FILE") to $TARGET"
