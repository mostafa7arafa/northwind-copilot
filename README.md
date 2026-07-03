# Northwind Copilot

A **local-first natural-language-to-SQL agent** over the Northwind retail
database. Ask a question in plain English; the agent lists tables, reads the
schema, consults an internal knowledge base, writes SQL, runs it, and answers
with the numbers — never inventing figures.

It runs primarily on a **local Ollama model** and only escalates to a cloud
model (OpenAI) when the local one fails or returns nothing usable. It ships
three ways to use it:

- a **LangGraph agent** (`langgraph dev`),
- a **FastAPI + Next.js web app** — the "Northwind Trading Desk" (see
  [WEBAPP.md](WEBAPP.md)),
- a **benchmark harness** that grades the agent against a labelled dataset.

---

## Architecture

Everything Python lives in the single package `northwind_copilot/`, split into
concern-focused layers. Dependencies point **inward**: `web` → `response` →
`query` → `infra` → `core`; nothing in `core` imports anything above it.

```
northwind_copilot/
├── core/            Business language — no I/O, pure config & text
│   ├── config.py        env-driven `settings` singleton (frozen dataclass)
│   ├── definitions.py   REVENUE_SQL, MARGIN_RATE — the KPI source of truth
│   └── prompts.py       SYSTEM_PROMPT (static) + build_system_prompt (dynamic)
├── infra/           Adapters to external systems
│   ├── database.py      SQLDatabase over data/northwind.sqlite
│   ├── llm.py           primary (Ollama) + optional fallback (OpenAI) factories
│   ├── rag.py           FAISS index builder over docs/*.md
│   └── docs_tool.py     the `search_docs` agent tool
├── query/           Question → running SQL agent
│   ├── graph.py         composition root; exports `graph` (langgraph.json target)
│   ├── agent_factory.py per-request engine builder (ollama|openai|openrouter)
│   └── middleware.py    escalate-on-degenerate + context trimming
├── response/        Agent output → user-facing answer
│   ├── charting.py      re-run SQL read-only (run_sql) + infer_chart
│   └── streaming.py     translate the agent stream into pipeline SSE events
├── web/             FastAPI service the frontend talks to
│   ├── app.py           /api/health, /api/models, /api/chat, /api/preferences
│   ├── models_registry.py  live Ollama + curated cloud model lists
│   └── preferences.py   free-text analyst preferences persistence
└── eval/            Benchmark harness
    ├── graders.py       fuzzy numeric / contains_all / fields / rows graders
    └── run_benchmark.py runs benchmark_dataset.jsonl, records model & latency

frontend/            Next.js 15 "Trading Desk" UI (see WEBAPP.md)
docs/                Knowledge base: KPI defs, marketing calendar, policies, catalog
data/northwind.sqlite  The database (Orders span 2012–2023, not classic 1996–98)
```

### Key design decisions

- **Local-first, escalate-on-empty.** The local model sometimes returns an empty
  completion on the hardest reasoning steps; the agent loop would read that as
  "done" and stop silently. `EscalateToFallbackMiddleware` escalates on an
  exception **or** a degenerate (empty) response — something the stock
  `ModelFallbackMiddleware` misses.
- **The cloud fallback is optional.** With no `OPENAI_API_KEY`, the graph still
  builds and runs entirely on the local model — the escalation simply has no
  target. (`ChatOpenAI` raises at construction without a key, so the factory
  returns `None` instead.)
- **Lean-local / heavy-cloud split (web path).** A slow local model pays real
  latency for every rule and tool round-trip, so the local prompt is short and
  drops the LLM-backed SQL query-checker; cloud carries the full prompt and
  charting instructions. The static benchmark graph is unchanged.
- **Never invent numbers.** Prompts forbid fabricating figures; an empty result
  is reported as "no rows", and the web layer suppresses any chart for it.

---

## Setup

Requires **Python 3.12+**, [uv](https://docs.astral.sh/uv/), and (for local
inference) [Ollama](https://ollama.com/) running with at least one model pulled.

```bash
uv sync --group dev --native-tls      # runtime + test/lint tooling
cp .env.example .env                  # then edit — see "Configuration" below
```

> On this Windows setup, `uv` needs `--native-tls` to reach PyPI.

---

## Usage

### Run the agent (LangGraph dev server)

```bash
uv run langgraph dev
```

`langgraph.json` points at `northwind_copilot/query/graph.py:graph`.

### Run the web app

The full-stack "Trading Desk" (FastAPI backend + Next.js frontend) has its own
guide: **[WEBAPP.md](WEBAPP.md)**. In short:

```bash
# backend (repo root)
LANGCHAIN_TRACING_V2=false PYTHONIOENCODING=utf-8 \
  uv run uvicorn northwind_copilot.web.app:app --port 8000
# frontend (in ./frontend)
npm install && npm run dev            # http://localhost:3000
```

### Run the benchmark

```bash
PYTHONIOENCODING=utf-8 uv run python -m northwind_copilot.eval.run_benchmark
uv run python -m northwind_copilot.eval.run_benchmark --id sql_employee_count_usa
uv run python -m northwind_copilot.eval.run_benchmark --limit 3 --no-save
```

Results (accuracy, which model answered, latency) are written to
`eval/results/latest.json`. Always set `PYTHONIOENCODING=utf-8` — some product
and customer names carry accented characters that crash the Windows console.

---

## Configuration

All settings resolve from environment variables (loaded from `.env`) with sane
defaults in [`core/config.py`](northwind_copilot/core/config.py):

| Variable | Default | Purpose |
| --- | --- | --- |
| `PRIMARY_MODEL` | `gemma4-12b` | Local-first Ollama model |
| `FALLBACK_MODEL` | `gpt-4.1-mini` | Cloud escalation model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embeddings for RAG |
| `NORTHWIND_DATABASE_URI` | `sqlite:///data/northwind.sqlite` | The database |
| `DOCS_DIR` | `docs` | Markdown knowledge base |
| `FAISS_PATH` | `.faiss_index` | On-disk vector index |
| `REINDEX` | `false` | Rebuild the FAISS index on next load |
| `OPENAI_API_KEY` | — | Enables the fallback **and** RAG embeddings |

> **Do not** use `DATABASE_URI` — LangGraph reserves that name for its own
> persistence layer and overwrites it with `:memory:` under `langgraph dev`.
> The RAG `search_docs` tool uses OpenAI embeddings, so questions about
> KPIs/categories/policies need `OPENAI_API_KEY` set even on the local engine.

---

## Development

```bash
# Test suite (offline — no LLM or network calls)
uv run pytest

# Coverage (branch coverage; 72%+ per module, ~94% overall)
uv run pytest --cov --cov-report=term-missing

# Lint gate (run before shipping)
uv run isort . && uv run black . && uv run flake8 northwind_copilot tests
```

Every module is unit-tested with fakes so the suite never touches Ollama,
OpenAI, or the network. `run_sql` and `build_database` run against the real
`northwind.sqlite` **read-only**.

---

## License

Provided as-is for educational and evaluation purposes.
