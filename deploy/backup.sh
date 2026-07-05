#!/usr/bin/env bash
# Nightly backup: Postgres dump + restic snapshot of tenant SQLite files to a
# Hetzner Storage Box (encrypted at rest by restic; the box never sees
# plaintext tenant data).
#
# Install on the VPS (as the deploy user):
#   sudo apt-get install -y restic
#   restic -r sftp:uXXXXXX@uXXXXXX.your-storagebox.de:backups/northwind init
#   crontab -e →  15 3 * * * /opt/northwind/deploy/backup.sh >> /var/log/nw-backup.log 2>&1
#
# Required environment (put in /etc/northwind-backup.env, mode 600, and
# `set -a; . /etc/northwind-backup.env; set +a` below picks it up):
#   RESTIC_REPOSITORY   sftp:uXXXXXX@uXXXXXX.your-storagebox.de:backups/northwind
#   RESTIC_PASSWORD     repo encryption password (manage like JWT_SECRET)
#   COMPOSE_PROJECT_DIR path to the checkout's deploy/ dir (compose + .env)
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/northwind-backup.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

cd "$COMPOSE_PROJECT_DIR"

# 1. App DB: pg_dump inside the running postgres container (custom format —
#    restorable with pg_restore, table-selective, compressed).
docker compose exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-copilot}" -Fc "${POSTGRES_DB:-copilot}" \
  > "$WORKDIR/app-$STAMP.dump"

# 2. Tenant data: copy the SQLite files out of the named volume. Files are
#    written once at ingest and opened read-only afterwards, so a live copy is
#    consistent.
docker compose cp backend:/data/tenants "$WORKDIR/tenants"

# 3. One restic snapshot holding both. restic deduplicates unchanged tenant
#    files across nights, so storage grows with churn, not with data size.
restic backup "$WORKDIR" --tag nightly

# 4. Retention: keep a week of dailies, a month of weeklies, a year of
#    monthlies; prune unreferenced data.
restic forget --tag nightly --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "backup $STAMP ok"
