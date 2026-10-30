# Personal-workspace architecture

## Entry points

- `./dev.sh`: starts FastAPI and Next.js; neither requires LangGraph's dev server.
- `langgraph.json` → `query/graph.py:graph`: separate static Northwind agent.
- `python -m northwind_copilot.eval.run_benchmark`: offline-configured benchmark
  runner (real benchmark execution still needs a running/configured model).

## Web request path

1. `frontend/components/Composer.tsx` submits the question.
2. `frontend/lib/store.ts` manages conversation/UI state; `lib/api.ts` handles
   REST calls and parses the SSE stream.
3. `web/app.py` checks local access, resolves the selected dataset (or Northwind
   sample), loads saved conversation history, and starts the stream.
4. `response/streaming.py` consumes agent updates and emits pipeline artifacts.
5. `query/agent_factory.py` creates the selected model, prompt, tools, and agent.
   GPT-6 `reasoning_effort="none"` remains required tool-calling behavior.
6. `infra/` supplies database/model/document-index adapters. `core/` supplies
   settings, KPI definitions, prompts, and optional error reporting.
7. `response/charting.py` executes result SQL through the read-only safety path
   and infers charts where needed.
8. `conversations/` records the turn and returns its ID for persisted feedback.

The static graph and evaluation instrument retain their original prompt/default
Northwind semantics. The web app's dynamic uploaded-dataset path remains distinct.

## Persistence

`persistence/` owns the async SQLite connection/session lifecycle and workspace
models. Datasets, conversations, turns, feedback, and golden examples have no
user or organization ownership fields. Routes use these models directly through
request-scoped sessions, not an authenticated/fake tenant context.

- `data/workspace.sqlite`: workspace metadata and saved chat artifacts.
- `data/datasets/<dataset-id>.sqlite`: read-only analyst data produced by upload.
- `data/northwind.sqlite`: bundled read-only sample, not workspace metadata.

Fresh schema initialization is local. Old SaaS databases and tenant paths must
not be automatically opened, migrated, or merged into this schema. Keep copies
of metadata and dataset files together when backing up or restoring.

## Boundaries

The app is designed for one trusted OS user. API loopback peer/Host/Origin
checks reduce exposure to remote clients and unrelated websites; they are not
multi-user authentication. Do not deploy publicly or assume tenant isolation.
Cloud keys may come from server environment or transient browser input; there
is no encrypted per-account key store. SQL safety, request limits, upload caps,
stream timeouts, and safe artifact persistence remain useful without billing.

Only `docs/*.md` is runtime knowledge-base content. Development/validation
notes live under `docs/maintenance/` and are not ingested by that glob.

## Preserved SaaS work

The archived, unmaintained
[`saas/paused`](https://github.com/mostafa7arafa/northwind-copilot/tree/saas/paused)
snapshot contains the complete pre-simplification implementation, including its
cleanup commits, tests, migrations, and deployment documentation. Revisit its
design before reusing it for a hosted service; it is not the active product
specification.
