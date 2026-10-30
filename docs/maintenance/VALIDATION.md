# Manual validation — personal workspace

Automated tests use fake LLMs and do not establish real-model/browser quality.
Run these checks before calling a personal-workspace release ready. No accounts,
Postgres, billing provider, or Docker stack is required.

## Start and stop

1. Run `./dev.sh --setup`, then `./dev.sh` from a different working directory
   using its absolute path; it should still find the project.
2. Open http://127.0.0.1:3000. There must be no login redirect, credit meter,
   pricing, subscription, or account controls.
3. Ctrl+C must stop both servers and leave ports 3000 and 8000 free.
4. An occupied port, missing dependency, or failed server must produce a useful
   error and stop the other child process. Do not kill unrelated applications.

## Product checks (requires a configured real model)

- Ask a Northwind question without selecting a dataset; verify the answer,
  displayed SQL, result table, chart, and exports against the actual data.
- Run the same flow with an uploaded CSV, XLSX, and SQLite file. Append a second
  file and query across its tables where a meaningful join exists.
- Edit/re-run SQL; attempts to write data must fail. A zero-row result must not
  produce invented numbers or a misleading chart.
- Set dataset business context and analyst preferences; verify they influence
  the next question without altering the static benchmark prompt.
- Start, rename, reload, and delete conversations. Restart the servers and
  verify saved history/datasets remain available.
- Give feedback, reload, and verify the vote persists; a positive dataset-backed
  answer should be available as a golden example.
- Try Local/Ollama and a configured cloud engine; server keys must not be exposed
  in API responses or logs, and browser-entered keys must not enter localStorage.
- Disconnect during a turn; completed/partial artifacts should remain coherent
  and the next turn should still work.

## Safety and data

- Non-loopback Host/Origin requests must be rejected by the protected API.
- No SaaS auth/usage/billing/key-storage endpoints should be present.
- Oversized uploads and hostile SQLite input must be rejected safely.
- Legacy `data/app.sqlite`, `data/tenants/`, external databases, browser storage,
  and Docker volumes must not be modified or automatically imported.
- Back up `data/workspace.sqlite` and `data/datasets/` together with the app
  stopped, then verify restoring those copies in a separate test directory.

## Automated checks

```bash
PYTHONIOENCODING=utf-8 uv run pytest
uv run black --check northwind_copilot tests
uv run isort --check-only northwind_copilot tests
uv run flake8 northwind_copilot tests
uv run vulture
bash -n dev.sh
(cd frontend && npm test && npx tsc --noEmit && npm run build)
```

Results from older SaaS validation instructions are not evidence that these
personal-workspace checks passed. Record real-model/manual outcomes separately;
do not substitute passing unit tests for an end-to-end trial.

## Implementation check results

At implementation commit `99dd7e0`:

- Backend: **246 tests passed**, including a real Uvicorn/socket regression that
  checks forwarded headers cannot replace the launcher's loopback peer.
- Frontend: **14 tests passed**; TypeScript and production build passed.
- Black/isort/flake8, Vulture80+, lock consistency, launcher syntax/help, and
  whitespace checks passed. Remaining dependency versions were not upgraded.
- An isolated real `./dev.sh` smoke check verified UI/API proxy startup,
  no login/signup/auth/usage/billing routes, foreign-Origin rejection, CSV
  upload, read-only SQL returning the expected sum, write rejection, deletion,
  and Ctrl+C shutting down both servers. No real LLM was called.
- Regression tests cover interrupted-turn reconciliation, delayed saves,
  startup/list races, stable IDs, and restoring feedback without browser cache.
- Independent standards and specification reviews found the initial recovery
  issues; the second/final review confirmed the fixes with no unresolved issues.
- GPT-6 model construction, the static graph, POC prompts/definitions, and the
  evaluation instrument remain unchanged from the archived, unmaintained
  [`saas/paused`](https://github.com/mostafa7arafa/northwind-copilot/tree/saas/paused)
  snapshot.

Real-model answer quality, visual browser interaction, and a backup/restore drill
remain manual checks, not completed claims in this implementation receipt.
