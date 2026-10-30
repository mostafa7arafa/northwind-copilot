# Single-user simplification specification

## Approved direction

The owner decided to keep Northwind Copilot a simple personal project. Preserve
current SaaS work on another local branch, make local `master` the single-user
product, update README/docs, and simplify startup. Do not push.

Preservation ref: archived, unmaintained
[`saas/paused`](https://github.com/mostafa7arafa/northwind-copilot/tree/saas/paused)
snapshot at `15bcded912b3b85ab00e4d56f33681529bfff53e`.
Implementation branch: `refactor/single-user`, based on that preserved snapshot.
Only fast-forward local `master` after relevant checks and independent review.

## Keep

- Local/Ollama, OpenAI, and OpenRouter model selection.
- Northwind sample fallback and CSV/XLSX/SQLite uploads, including multi-file data.
- Dataset context, saved conversations/turns, feedback/golden examples.
- SQL inspection/edit/re-run, tables, charts, exports, analyst preferences.
- Read-only SQL, timeout/row caps, upload validation and 25 MB resource cap.
- Required GPT-6 `reasoning_effort="none"` behavior in `build_model`.
- Static Northwind graph, POC prompt/definitions, and eval instrument unchanged.

## Remove from the active product

Login/signup, JWT/account/OAuth plumbing, organizations/memberships, tenancy,
subscriptions/checkout, payment mocks, credits/trials, commercial entitlement
checks, per-account encrypted provider keys, and hosted-mode forks. No dummy
account or fake organization as a shortcut.

SaaS migrations, production deployment stack, and image-publication CI belong
on the preservation branch. Keep ordinary backend/frontend/security checks.

## Local architecture

Use a small `persistence/` package (async SQLAlchemy/aiosqlite) for datasets,
conversations, turns, feedback, and golden examples. No user/org columns.
Initialize fresh SQLite schema locally; do not automatically migrate SaaS data.

- `WORKSPACE_DATABASE_URL`: `sqlite+aiosqlite:///data/workspace.sqlite`.
- `DATASET_DATA_DIR`: `data/datasets`.
- Preserve `NORTHWIND_DATABASE_URI` for the read-only analyst sample.
- Ignore obsolete SaaS env settings; reject explicitly pointed-at legacy
  schemas/paths rather than modifying them.
- Do not delete/modify Docker volumes, old app DBs/tenant files, or browser
  storage. Existing browser entries must fail/recover gracefully if their server
  conversation does not exist in the new workspace.
- Keys may come from backend environment or transient browser memory, not
  localStorage or a per-account database.

The personal API is loopback-only: guard peer, Host, and allowed local Origin;
do not trust forwarded headers to grant access. Keep health usable for startup
checks. No public/LAN deployment support is implied by removal of login.

## Startup and docs

`./dev.sh --setup` explicitly installs locked dependencies and exits.
`./dev.sh` starts loopback FastAPI and Next.js, checks occupied ports/readiness,
prints the URL, and terminates only its own children on interrupt/failure.
Do not overwrite `.env`, generate/rotate keys, start Ollama, enable insecure
TLS, or make model calls automatically.

Move manual validation under `docs/maintenance/` so `docs/*.md` knowledge-base
indexing excludes it. Update README package diagram, environment sample,
WEBAPP guide, and maintenance architecture/validation notes. Old SaaS docs
must not masquerade as the current product instructions.

## Acceptance

- All retained automated tests pass; add/adapt tests for changed product
  behavior. Removed SaaS tests naturally change the old 269-test total.
- Black/isort/flake8, Vulture80+, frontend typecheck/build, launcher syntax,
  lock consistency, and whitespace checks pass. No ruff/mypy or unrelated
  runtime dependency upgrades.
- Exercise local startup/shutdown and API persistence without real model
  calls, using an isolated workspace. Real LLM/browser quality remains a
  separately documented manual check; do not claim it was proven by unit tests.
- Independent standards and spec review, at most two review/fix rounds.
- Local `master` updated only after these gates; preserved SaaS ref unchanged;
  nothing pushed.
