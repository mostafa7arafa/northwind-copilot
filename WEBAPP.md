# Northwind Trading Desk — web app

A premium, AI-native analytics workspace over the Northwind copilot agent. Ask
the ledger in plain language; the agent generates SQL, runs it, and the UI
unfolds the answer as a live pipeline — **Understand → SQL → Execute → Results →
Chart → Insights** — beside a result table and Apache ECharts visualization.

It has two engine states you switch between in the header dashboard:

- **Local** — any model installed in your Ollama (auto-detected, e.g. `gemma4-12b`).
- **Cloud** — **OpenAI** or **OpenRouter**, chosen per request. Cloud models get
  an extended system prompt that asks them to draw their own ECharts spec; local
  models are charted automatically by the server from the result table.

Under **Settings** you can save free-text **analyst preferences** (appended to
the system prompt on every question) and your **provider API keys** (kept in the
browser only).

## Architecture

```
frontend/  Next.js 15 · React 19 · Tailwind v4 · Framer Motion · TanStack Table
           · Monaco (SQL) · Apache ECharts · Zustand
server/    FastAPI wrapping the existing LangGraph agent (northwind_copilot):
           GET  /api/models        local + cloud model registry
           POST /api/chat          SSE stream of pipeline events
           GET/POST /api/preferences
```

The frontend proxies `/api/*` to the backend (see `frontend/next.config.mjs`),
so streaming isn't buffered and the browser sees one origin.

## Run it

**1. Backend** (from the repo root, using the existing uv venv):

```bash
uv sync --group web --native-tls          # first time only
# tracing off avoids noisy LangSmith calls if you don't use it
LANGCHAIN_TRACING_V2=false PYTHONIOENCODING=utf-8 \
  .venv/Scripts/python.exe -m uvicorn server.app:app --port 8000
```

**2. Frontend** (in another terminal):

```bash
cd frontend
npm install                                 # first time only
npm run dev                                  # http://localhost:3000
```

Open http://localhost:3000, pick an engine in the header, and ask a question.

## Notes

- **Local engine** needs Ollama running (`ollama serve`) with at least one model
  pulled. The picker lists whatever is installed.
- **Cloud engines** need a key (Settings → Provider keys), or set `OPENAI_API_KEY`
  in `.env` for OpenAI.
- The RAG `search_docs` tool uses OpenAI embeddings, so questions about KPIs /
  categories / policies need `OPENAI_API_KEY` set even on the local engine.
- All generated SQL is executed **read-only** (`SELECT`/`WITH` only) for the
  result table.
