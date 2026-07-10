# Ops runbook — hosted deployment

Solo-operator ops for the hosted product: error tracking, uptime, backups,
restore drill, and staging. Everything here assumes the docker-compose stack in
this directory running on a single VPS.

## Error tracking (Sentry)

- **Backend**: set `SENTRY_DSN` in `deploy/.env`. The FastAPI app initialises
  Sentry at import ([core/observability.py](../northwind_copilot/core/observability.py));
  every event passes a scrubber that redacts `sk-…` keys and bearer tokens.
  The `error_id` users see in chat errors is attached as the **`error_id`
  event tag** — search Sentry for the id a user reports.
- **Frontend**: set `NEXT_PUBLIC_SENTRY_DSN` (baked into the bundle at build
  time — rebuild the frontend image after changing it). Use a separate Sentry
  project so browser noise doesn't drown backend errors.
- Both are opt-in: empty DSNs disable Sentry entirely (dev, POC, tests).
- Tag environments via `SENTRY_ENVIRONMENT` (`production` / `staging`).

## Uptime (UptimeRobot)

Create a free HTTPS monitor on `https://<domain>/api/health` (expects
`{"ok": true}`), 5-minute interval, alert to email/Telegram. Add a second
monitor on `https://<domain>/` for the frontend. Staging gets its own monitor
on `staging.<domain>` once it exists.

## Backups

[`backup.sh`](backup.sh) runs nightly from cron: `pg_dump` (custom format) of
the app DB + a copy of `/data/tenants` (per-tenant SQLite files), snapshotted
to a Hetzner Storage Box with **restic** (client-side encrypted; the box never
holds plaintext tenant data). Retention: 7 daily / 4 weekly / 12 monthly.

Setup is documented at the top of the script. The restic repo password is a
production secret — store it with `JWT_SECRET`/`KEY_ENCRYPTION_SECRET` (GitHub
Actions environment secret → server env file, mode 600).

### Restore drill (do this once now, then quarterly)

Target: fresh VPS → serving traffic in under an hour.

1. Provision a VPS, install Docker + restic, clone the repo, copy `deploy/.env`.
2. `restic -r $RESTIC_REPOSITORY restore latest --target /tmp/restore`
3. Start only Postgres: `docker compose up -d postgres`
4. Restore the app DB:
   `docker compose exec -T postgres pg_restore -U copilot -d copilot --clean --if-exists < /tmp/restore/<workdir>/app-<stamp>.dump`
5. Restore tenant files:
   `docker compose cp /tmp/restore/<workdir>/tenants/. backend:/data/tenants`
   (bring `backend` up first, or `docker run` a throwaway container mounting
   the `tenant_data` volume and `cp` into it).
6. `docker compose up -d --build`, point DNS (or /etc/hosts for a drill) at the
   box, log in, open an old conversation, ask a question against an uploaded
   dataset.
7. Record the wall-clock time in this file.

Last drill: _not yet performed_.

## Staging

Staging is a second compose **project** on the same box — same images,
separate volumes and network, its own subdomain:

```bash
mkdir -p ~/staging && cp -r deploy ~/staging/deploy
cd ~/staging/deploy
# edit .env: SITE_ADDRESS=staging.<domain>, FRONTEND_ORIGIN=https://staging.<domain>,
#            SENTRY_ENVIRONMENT=staging, a separate POSTGRES_PASSWORD
docker compose -p northwind-staging up -d --build
```

Caddy in each project binds 80/443, so give staging its own ports
(`8080:80`, `8443:443`) and put the DNS record behind the prod Caddy with a
`staging.<domain>` site block proxying to the staging Caddy — or simplest:
add `staging.<domain>` as a second site in the **prod** Caddyfile pointing at
the staging frontend/backend containers via the shared Docker network. Pick one
and keep it; the point is prod and staging never share a database, volume, or
Sentry environment.

## Secrets & rotation

- `KEY_ENCRYPTION_SECRET` (Fernet, encrypts stored BYOK keys): rotating it
  requires re-encrypting `api_keys` rows (decrypt with old, encrypt with new).
  Until a rotation script exists, a rotation invalidates stored keys — they
  fail closed (turns fall back to the metered path) and users re-enter keys.
- `JWT_SECRET`: rotation = every session invalidated (forced re-login). Cheap;
  do it on any suspicion of leakage.
- Our `OPENROUTER_API_KEY`: rotate at the provider, update `.env`, restart.
