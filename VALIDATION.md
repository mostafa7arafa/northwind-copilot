# Manual Validation Guide — Multi-Tenant SaaS (Phase 0)

The automated tests (167 backend + frontend typecheck/build) prove the units and
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

## Known gaps (deliberately not built yet — don't test for these)

- **Billing / plans / credits** — no metering or payment yet (Phase 1–2). Everyone is effectively unlimited; there's a hard 25 MB upload cap in code.
- **BYOK key storage** — the per-user encrypted key store is Phase 1. Today the server's `OPENROUTER_API_KEY` serves all hosted turns.
- **Google OAuth** — endpoints not wired yet; email+password only.
- **Backups, Sentry, rate-limit-by-user, LangSmith/Langfuse** — Phase 1 ops.
- **Dataset schema LLM enrichment** — only the mechanical schema summary is generated so far (the `describe` hook exists, unused).

## If something breaks

- Backend errors return an `error_id`; find the full traceback in the backend
  container logs by that id.
- Migrations: `docker compose exec backend alembic current` / `history`.
- Reset everything: `docker compose down -v` (⚠ deletes the Postgres volume and
  all uploaded datasets).
