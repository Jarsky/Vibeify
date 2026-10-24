#!/usr/bin/env bash
# Copy the self-hosted Docker Compose database into a hosted PostgreSQL (e.g. Render), then compare row counts.
#
#   TARGET_DATABASE_URL='postgresql://user:pass@host/db' scripts/migrate-to-render.sh
#
# Use the database's *External* connection string. The target app must use the same SECRET_KEY as this install.
# Stops the local app container first so nothing is written after the dump (the local database keeps running,
# and `docker compose start vibeify` undoes it). Existing tables in the target are replaced.
set -euo pipefail

: "${TARGET_DATABASE_URL:?set TARGET_DATABASE_URL to the external connection string of the target database}"
APP=${APP_CONTAINER:-vibeify}
DB=${DB_CONTAINER:-vibeify-db}
OUT=${BACKUP_DIR:-/opt/backups}/vibeify-migrate-$(date +%Y%m%d-%H%M).dump
TABLES="users generations usage_log audit_log support_tickets billing_events plans llm_models settings"

count() {   # count <psql args...>: one line per table, "table rows"
  for t in $TABLES; do printf '%s %s\n' "$t" "$("$@" -tAc "select count(*) from $t")"; done
}
local_psql() { docker exec "$DB" sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB" "$@"' -- "$@"; }
target_psql() { docker run --rm postgres:17-alpine psql "$TARGET_DATABASE_URL" "$@"; }

echo "Stopping $APP so no new data is written locally…"
docker stop "$APP" >/dev/null

echo "Dumping to $OUT…"
docker exec "$DB" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl "$POSTGRES_DB"' > "$OUT"
ls -l "$OUT"

echo "Restoring into the target (replacing its tables)…"
docker run --rm -i postgres:17-alpine pg_restore --clean --if-exists --no-owner --no-acl --single-transaction \
  -d "$TARGET_DATABASE_URL" < "$OUT"

echo "Row counts (local | target):"
paste <(count local_psql) <(count target_psql) | awk '{ flag = ($2 == $4) ? "ok" : "DIFFERENT"; printf "  %-16s %8s | %-8s %s\n", $1, $2, $4, flag }'
echo "Done. Restart the target app so it picks up the restored data, then check the site."
