# Northwind Trading Desk

A personal SQL-analyst workspace: upload CSV/XLSX/SQLite or use the Northwind
sample, ask questions, inspect/edit SQL, and export results and charts.
There are no accounts, organizations, plans, credits, or payment flows.

## Start

Requires Python 3.12+, uv, Node.js 20+, npm, and curl. The launcher targets
Bash on Linux/macOS (or a Linux environment such as WSL).

```bash
./dev.sh --setup      # Install locked dependencies; first run or after lock changes
# Optional: cp .env.example .env, then edit your model/API-key settings
./dev.sh
```

Open **http://127.0.0.1:3000**. Ctrl+C stops both servers. Startup fails clearly
if dependencies are missing, ports 3000/8000 are occupied, or a server cannot
become ready. It never overwrites `.env`, generates secrets, or starts Ollama.

- **Local:** start Ollama separately and pull a model; the picker lists installed
  models. No GPU/local model is needed when using a cloud engine.
- **Cloud:** choose OpenAI/OpenRouter and configure the appropriate server key in
  `.env`, or enter a key in Settings. Browser-entered keys stay in memory, not
  localStorage; re-enter them after refreshing.
- **Document search:** `search_docs` uses OpenAI embeddings, even with local chat.
  Without an OpenAI key, do not rely on this optional tool.

## Data

- `data/northwind.sqlite`: built-in sample, queried read-only.
- `data/workspace.sqlite`: saved datasets, conversations, turns, and feedback.
- `data/datasets/`: uploaded data converted into per-dataset SQLite files.
- `.user_preferences.json`: local analyst preferences.
- Browser storage: UI/session state; not a substitute for backing up workspace data.

Back up the workspace database and uploaded files together while the app is
stopped. Old SaaS databases, tenant files, encrypted provider keys, and Docker
volumes are not automatically migrated or deleted. The old implementation is
preserved as an archived, unmaintained
[`saas/paused`](https://github.com/mostafa7arafa/northwind-copilot/tree/saas/paused)
snapshot.

### Schema policy

There are **no migrations**. SQLAlchemy `create_all` initializes missing tables;
it does not update existing tables after a model change. Startup rejects an
incompatible workspace schema rather than silently modifying it.

After changing a model, stop the app and back up the workspace and uploaded
files. Either delete `data/workspace.sqlite` to start fresh (this loses saved
conversations, feedback, and the dataset catalog), or update the schema by hand,
for example by adding the required columns with SQLite SQL. Remove any leftover
`workspace.sqlite-wal`/`workspace.sqlite-shm` files only when resetting the stopped
workspace. Uploaded files are not automatically reimported after a reset.

## Request flow

```text
Composer → store.ts → api.ts → POST /api/chat
  → resolve dataset and saved history
  → build agent → stream model/tool updates
  → execute result SQL read-only → emit tables/charts/insights
  → save turn → browser renders SSE events
```

The Next.js server proxies `/api/*` to FastAPI on port 8000. The web app builds
its own agent through `query/agent_factory.py`; it does not need a separate
`langgraph dev` process. That command remains a separate agent-development entry
point.

## Local-only security

The launcher binds both servers to loopback and disables Uvicorn proxy-header
handling. Keep `--no-proxy-headers` if starting Uvicorn manually. The API checks
loopback peers, Host, and allowed Origin values. Do not expose it through public tunnels,
reverse proxies, or LAN bindings: there is intentionally no user authentication.
Generated SQL remains read-only, timeout-limited, and row-capped; uploads retain
the 25 MB safety cap.

Manual checks: [validation guide](docs/maintenance/VALIDATION.md).
