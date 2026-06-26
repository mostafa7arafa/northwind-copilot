# Northwind Copilot

A natural-language-to-SQL agent over the classic **Northwind** retail database.
It runs **local-first** on a small open model and escalates to a frontier model
only when the local one can't finish a step — so most questions never leave your
machine, and the hard ones still get answered.

Built with **LangGraph** + **LangChain v1**, with a RAG layer over internal
business docs and a benchmark harness that measures accuracy, per-model
attribution, and latency.

---

## Why it's interesting

- **Local-first, escalate-on-failure.** Primary model is a local
  `gemma4-12b` via [Ollama](https://ollama.com/); fallback is OpenAI
  `gpt-4.1-mini`. Crucially, escalation triggers on **empty/degenerate
  responses**, not just exceptions — a small local model often *silently*
  returns nothing on the hardest reasoning step, and the stock
  `ModelFallbackMiddleware` never catches that.
- **Hybrid SQL + RAG.** The agent answers questions that require *both*
  querying the database *and* reading internal policy/KPI docs (e.g. "top
  customer by gross margin in 2017" needs the margin definition **and** a
  3-table aggregation).
- **Measured, not vibes.** Every change is validated against a 10-question
  benchmark with verified ground truth.

## Architecture

```
                    ┌──────────────────────────────────────────┐
   user question →  │  LangGraph agent (create_agent)          │
                    │                                          │
                    │  middleware:                             │
                    │   • EscalateToFallbackMiddleware ────────┼──► gemma4-12b (local, Ollama)
                    │     (escalate on error OR empty reply)   │        │ if empty/error
                    │   • trim_context (8k-token window)       │        ▼
                    │                                          │     gpt-4.1-mini (OpenAI)
                    │  tools:                                  │
                    │   • SQLDatabaseToolkit (list/schema/     ├──► data/northwind.sqlite
                    │     query/checker)                       │
                    │   • search_docs (FAISS RAG) ─────────────┼──► docs/*.md
                    └──────────────────────────────────────────┘
```

Key files:

| Path | What |
|---|---|
| [`agent/agent.py`](agent/agent.py) | Agent, system prompt, `EscalateToFallbackMiddleware`, context trimming |
| [`agent/tools/docs_tool.py`](agent/tools/docs_tool.py) | `search_docs` RAG tool |
| [`agent/rag/retrieval.py`](agent/rag/retrieval.py) | FAISS index build/load over `docs/` |
| [`docs/`](docs/) | Business knowledge: KPI defs, marketing calendar, product policy, catalog |
| [`eval/`](eval/) | Benchmark runner + fuzzy graders |
| [`benchmark_dataset.jsonl`](benchmark_dataset.jsonl) | 10 questions with verified ground truth |

## Results

Latest benchmark (10 questions: 3 RAG, 3 SQL, 4 hybrid):

| Metric | Value |
|---|---|
| Accuracy | **10 / 10** |
| Ran fully on local gemma | 9–10 / 10 |
| Escalated to GPT-4.1 | 0–1 / 10 |

The agent keeps almost all work local and only reaches for the frontier model
on the most complex multi-step query.

## Setup

**Prerequisites:** Python 3.12, [uv](https://docs.astral.sh/uv/),
[Ollama](https://ollama.com/), and an OpenAI API key (used for the fallback
model and for RAG embeddings).

```bash
# 1. Install dependencies
uv sync

# 2. Pull the local model (≈7.4 GB)
ollama pull gemma4-12b      # or point agent/agent.py at any local model you have

# 3. Configure secrets
cp .env.example .env        # then fill in OPENAI_API_KEY (+ optional LangSmith)
```

`.env` keys:

```
OPENAI_API_KEY=<your-key>
LANGSMITH_API_KEY=<your-key>      # optional, for tracing
LANGCHAIN_TRACING_V2=true         # optional
LANGCHAIN_PROJECT=northwind-copilot
REINDEX=true                      # rebuild the FAISS index on next run
```

## Run

**Interactive (LangGraph dev server):**

```bash
uv run langgraph dev
```

**Benchmark:**

```bash
PYTHONIOENCODING=utf-8 uv run python -m eval.run_benchmark
# options: --id <id>  (run one question)   --limit N   --no-save
```

Results are written to `eval/results/latest.json` (plus a timestamped copy).
`PYTHONIOENCODING=utf-8` is required on Windows because some product/customer
names contain accented characters (e.g. *Côte de Blaye*).

## How it works

1. The agent searches the docs (RAG) for any KPI / campaign / policy definitions
   the question references.
2. It inspects the DB schema (`sql_db_list_tables` → `sql_db_schema`), writes and
   validates SQL, then executes it.
3. The local model handles this end-to-end for most questions. If it errors or
   returns an empty completion, `EscalateToFallbackMiddleware` retries that step
   on GPT-4.1 and the loop continues.

## License

Personal learning project. Northwind sample data is public-domain.
