#!/usr/bin/env bash
#
# ops/load_usaspending_batch2_to_prod.sh   (one-off, 2026-07-14)
#
# Replace prod's usaspending_awards + idiq_recipients (its stale original-10 subset) with
# local's full curated set. The mapping_status confirms/excludes and ownership verdicts ride
# along in the data. `companies` is seeded by migration 0048, so it's not part of the load.
#
# Prereq (run FIRST — not done here):  ./migrate.sh prod 48 && ./migrate.sh prod 49

set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
PROD=$(echo "$PROD_DATABASE_URL" | sed 's#postgresql+asyncpg#postgresql#')

read -r -p "Replace usaspending_awards + idiq_recipients on PROD from local strata? type 'yes': " ok
[ "$ok" = "yes" ] || { echo "aborted"; exit 1; }

# 1) clear prod's stale subset
psql "$PROD" -v ON_ERROR_STOP=1 -c "TRUNCATE usaspending_awards, idiq_recipients;"

# 2) load local's data (pg_dump also emits the sequence setval)
pg_dump strata --no-owner --no-acl --data-only \
    -t usaspending_awards -t idiq_recipients | psql "$PROD" -v ON_ERROR_STOP=1

# 3) belt-and-suspenders: re-sync the awards serial in case the dump didn't
psql "$PROD" -c "SELECT setval('usaspending_awards_id_seq', (SELECT max(id) FROM usaspending_awards));"

echo "done:"
psql "$PROD" -tAc "SELECT 'usaspending_awards='||count(*) FROM usaspending_awards; SELECT 'idiq_recipients='||count(*) FROM idiq_recipients;"
