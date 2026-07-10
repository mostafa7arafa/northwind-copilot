# Manual Validation Guide — Multi-Tenant SaaS (Phase 0)

The automated tests (206 backend + frontend typecheck/build) prove the units and
the tenant-isolation logic, but they **do not** prove the product works
end-to-end: they mock the LLM, never run a real agent turn, never exercise the
browser, and use SQLite instead of Postgres. This guide is what *you* need to do
to confirm it actually works.

Legend: ✅ = automated tests cover it · 🔴 = **needs your manual check**

---

## 0. What the automated tests already cover ✅

- Signup/login/logout/session, password hashing, JWT cookie
- Tenant isolation: org A cannot read/edit/delete org B's datasets or
  conversations (returns 404), verified at both the API and context layers
- File ingestion: CSV/XLSX/SQLite → per-tenant SQLite; **hostile SQLite
  rejected**, views/triggers/virtual tables shed
- Dataset-parameterized prompt assembly; POC prompt unchanged
- Conversation persistence, history assembly, turn recording
- Config, migrations apply cleanly (SQLite)

## What is NOT tested and needs you 🔴

Everything involving a **real LLM**, a **real browser**, and **Postgres**.

---

## 1. Bring the stack up (Docker, Postgres — closest to production) 🔴

```bash
cd deploy
cp .env.example .env
# Fill in .env:
#   SITE_ADDRESS=localhost           (or your domain)
#   FRONTEND_ORIGIN=https://localhost
#   POSTGRES_PASSWORD=<any>
#   JWT_SECRET=$(openssl rand -hex 32)
#   KEY_ENCRYPTION_SECRET=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
#   OPENROUTER_API_KEY=<your key>    (needed for real answers)
docker compose -f docker-compose.yml up --build
```

> **TLS-intercepting network (corporate proxy / antivirus)?** If the build
> fails with certificate errors (`UnknownIssuer`), or chat turns fail with
> `CERTIFICATE_VERIFY_FAILED` / "analyst service unreachable", set
> `INSECURE_TLS=1` in `deploy/.env`. This relaxes cert verification for the
> Docker build **and** for the backend's outbound LLM calls at runtime. It is a
> dev-only escape hatch — leave it empty on a real server (a proper fix is to
> mount your network's root CA into the containers instead).

**Check:**
- [ ] All four containers start (postgres, backend, frontend, caddy)
- [ ] Backend logs show `alembic upgrade head` running (creates 8 tables in Postgres — this is the Postgres migration path the tests never exercise)
- [ ] `https://localhost/api/health` returns `{"ok": true}` (accept the self-signed cert for localhost)

> If you don't want Docker yet, run locally instead: set `HOSTED_MODE=true` and
> `NEXT_PUBLIC_HOSTED_MODE=true`, `uvicorn northwind_copilot.web.app:app` +
> `cd frontend && npm run dev`. This uses SQLite, so it does **not** validate the
> Postgres path — do the Docker run before trusting production.

## 2. Auth flow in the browser 🔴

- [ ] Visit the site → you're redirected to `/login` (middleware gate)
- [ ] Create an account at `/signup` → lands in the app
- [ ] Refresh the page → still logged in (cookie persists)
- [ ] Open dev tools → Application → Cookies: `nw_session` is **HttpOnly** and (over https) **Secure**
- [ ] Log out → redirected back to `/login`

## 3. Dataset upload + real chat (the core loop) 🔴

- [ ] In the sidebar (hosted build shows a **Datasets** panel), upload a real CSV of your own
- [ ] Status goes `processing` → `ready` with a row count
- [ ] Select the dataset, ask a real question in plain language
- [ ] **The agent returns a correct answer with SQL + a table (and a chart)** — this is the #1 thing tests can't verify. Sanity-check the SQL and numbers against your data yourself.
- [ ] Ask a follow-up ("break that down by …") → it uses prior context correctly
- [ ] Try Excel (multi-sheet) and a `.sqlite` file too
- [ ] Upload a deliberately broken file (e.g. rename a `.txt` to `.csv`, or a non-DB `.sqlite`) → you get a clean error, not a crash

**Answer quality on *your* schema is the top product risk.** The prompt no
longer has the hand-tuned Northwind rules; it relies on the generated schema
summary + the business-context box. If answers are weak, edit the dataset's
**business context** (definitions/formulas) and re-ask.

## 4. Conversation persistence 🔴

- [ ] After a few turns, reload the page → the conversation is still there (served from the DB, not localStorage)
- [ ] Kill the browser tab mid-answer, reopen → the turn was still saved (persistence runs even on disconnect)

## 5. Tenant isolation with two real accounts 🔴

- [ ] Sign up as user B in a second browser/incognito
- [ ] Confirm B sees **none** of A's datasets or conversations
- [ ] (Optional, if you know A's dataset id) `curl` B's session against `GET /api/datasets/<A's id>` → expect **404**

## 6. Security spot-checks 🔴

- [ ] Response headers include HSTS, `X-Frame-Options: DENY`, and a CSP (from Caddy)
- [ ] An API call without the cookie → 401
- [ ] Confirm no secrets in the frontend bundle: `grep -r JWT_SECRET frontend/.next` finds nothing

---

## 7. Phase 1: metering, entitlements, BYOK 🔴

Automated tests cover the ledger math, tier gates, key encryption, and the
settle-on-disconnect path (mocked agent). What needs a real browser + LLM:

- [ ] Header shows the **UsageMeter**: a fresh trial account shows `30/30 queries`,
      and the count drops after each answer (live from the SSE `usage` event)
- [ ] Kill the browser tab mid-answer → the `usage_events` row (and, on a paid
      plan, the `credit_ledger` debit) still lands — check the DB
- [ ] Upgrade an org manually (`UPDATE orgs SET plan='starter'`, grant credits
      via `metering.credits.grant_credits`) → meter switches to credits and
      counts down by ~1 credit per mini-class turn
- [ ] Out of allowance → chat returns a clean **402** message, not a crash
- [ ] Trial accounts get **403** when storing a BYOK key; on Starter+, Settings
      stores a key (shows `•••• last4`), chat then reports `byok: true` usage
      with 0 credits, and Clear removes it
- [ ] Second dataset upload on trial → clean 403 quota message
- [ ] Set `SENTRY_DSN` and force an error → event arrives with the `error_id`
      tag matching the id shown in chat; no `sk-…` values anywhere in the event

## 8. Billing lifecycle (mock provider) 🔴

`BILLING_PROVIDER=mock` (the default) mimics the full transaction flow — real
checkout URL, signed webhooks, idempotent processing, credit grants — with no
money. Automated tests cover the lifecycle; check the UX in a browser:

- [ ] Settings → **Plan & billing** lists Starter/Pro/Team with prices; your
      current plan shows trial queries left
- [ ] Click **Upgrade** on Pro → browser bounces through the mock checkout and
      lands back on `/?billing=success`; the header meter now shows
      `pro · 1200 credits`
- [ ] Refresh the checkout completion URL from history → balance does **not**
      double (idempotent webhook replay)
- [ ] Simulate a renewal:
      `curl -k -X POST https://localhost/api/billing/mock/simulate -H "Content-Type: application/json" -b "nw_session=<cookie>" -d '{"kind":"renewed"}'`
      → leftover credits expire, fresh 1,200 granted (ledger shows
      `rollover_expiry` + `grant`)
- [ ] Simulate `{"kind":"payment_failed"}` → meter turns amber; Settings shows
      the grace-period banner; chat still works
- [ ] Simulate `{"kind":"cancelled"}` → plan drops to expired trial: chat
      returns 402, but conversations/datasets stay readable
- [ ] Buy again after cancelling → back to active with a fresh grant

When real payments arrive: implement `billing/paddle.py` against the
`BillingProvider` protocol, set `BILLING_PROVIDER=paddle`, and point Paddle's
webhook at `POST /api/billing/webhook` — routes, lifecycle, ledger, and the
frontend don't change.

## 9. Product differentiators 🔴

All four ship in-code and are covered by unit/API tests; check the UX and the
*answer quality* effects with a real LLM:

- [ ] **Multi-file datasets**: upload `sales.csv`, then click the small
      file-plus icon on the dataset row and add `targets.csv` → row/table
      counts grow, and a question like "compare sales against targets by
      region" produces a JOIN across both files
- [ ] **SQL edit & re-run**: on any answer's SQL card, click the pencil →
      edit the query → Run. The edited result renders inline (marked as not
      saved); a non-SELECT edit gets a clean error
- [ ] **Arabic answers**: ask a question in Arabic against an uploaded
      dataset → prose/insights come back in Arabic, SQL stays untouched
      (identifiers untranslated). POC/Northwind behaviour unchanged
- [ ] **Feedback loop**: thumbs-up a correct answer → "Saved" note appears;
      ask a *similar* question in a new conversation → the SQL follows the
      confirmed approach (the prompt now carries the golden example).
      Thumbs-down retracts it

## Known gaps (deliberately not built yet — don't test for these)

- **Real payments** — the mock provider stands in for Paddle; no money moves.
  Paddle (Phase 2) is one new module behind the same protocol + env flip.
- **Automatic renewals** — nothing schedules `renewed` events yet (a real
  provider fires them; the mock has the `/simulate` drill). No dunning emails.
- **Org invites / seats** — the Team tier's seat count is defined but not
  enforced (no invite endpoint yet).
- **Google OAuth** — endpoints not wired yet; email+password only.
- **Rate-limit-by-user** — the limiter is still keyed by client IP.
- **Ops installs** — `deploy/backup.sh` + restore drill, UptimeRobot, staging
  compose project: manual steps in [deploy/OPS.md](deploy/OPS.md).
- **Dataset schema LLM enrichment** — only the mechanical schema summary is generated so far (the `describe` hook exists, unused).

## If something breaks

- Backend errors return an `error_id`; find the full traceback in the backend
  container logs by that id.
- Migrations: `docker compose exec backend alembic current` / `history`.
- Reset everything: `docker compose down -v` (⚠ deletes the Postgres volume and
  all uploaded datasets).
