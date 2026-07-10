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

## Evaluation: can a local model actually do this job?

The project ships two ways — run it locally on Ollama, or deploy it against
cloud models. That bet only holds if the local model is genuinely competent, so
we measured it instead of assuming.

### The experiment

**23 scripted three-turn conversations** (69 turns) over the Northwind database,
run identically against both engines. Later turns refer back to earlier ones
("break *that one* down by quarter", "and the worst?", "which of *them* sold
most?"), because reference resolution is the thing a single-turn benchmark
cannot see: 44 of the 69 turns carry an anaphor.

Ground truth is **computed, never hand-written** — every turn carries a reference
SQL query, executed against the live database at dataset-build time. The builder
refuses to publish if a reference query returns no rows (except the one probe
that is *supposed* to), and a test rejects any reference whose `ORDER BY … LIMIT 1`
is tied, since a tie makes two answers correct while marking one of them wrong.

Scored by an LLM judge (`openevals`) on three dimensions, plus latency and tokens
recorded directly:

| Metric | What it asks |
| --- | --- |
| `correctness` | Does the answer match the computed ground truth? |
| `no_hallucination` | Does every figure trace back to a query result this conversation actually retrieved? |
| `context_retention` | Does each "that product" / "their revenue" resolve to the right entity? |

The judge is **`qwen/qwen3-30b-a3b-instruct-2507`** via OpenRouter — a third
family, chosen so it shares no lineage with either arm. (A GPT judge would favour
the GPT arm; Gemini was disqualified for sharing a family with Gemma.)

### The machine

| | |
| --- | --- |
| CPU | AMD Ryzen 9 5900HX (8C/16T, 3.30 GHz) |
| RAM | 32 GB |
| GPU | NVIDIA RTX 3080 Laptop, **16 GB VRAM**, driver 592.00 |
| OS | Windows 11 |
| Runtime | Ollama 0.31.1 |
| Local model | `gemma4-12b` (11.9B, Q4_K_M, 8.3 GB resident, `num_ctx=8192`, **100% GPU**, thinking off) |
| Cloud model | `gpt-4.1-mini` |

### Results

23 scenarios / 69 turns per arm. Higher is better for the judged metrics.

| | `gemma4-12b` (local) | `gpt-4.1-mini` (cloud) |
| --- | --- | --- |
| **correctness** | **89.9%** | **90.6%** |
| **no_hallucination** | **98.6%** | **98.6%** |
| **context_retention** | **91.3%** | 87.0% |
| correctness — turn 1 | 82.6% | 90.9% |
| correctness — turn 2 | 95.7% | 91.3% |
| correctness — turn 3 | 91.3% | 91.3% |
| latency / turn | 6.98 s | 5.69 s |
| latency / conversation | 20.94 s | 17.07 s |
| input tokens / conversation | 12,594 | 21,886 |
| output tokens / conversation | 553 | 712 |
| model calls / conversation | 8.5 | 9.6 |
| cost / 1,000 conversations | **$0** | ~$9.89 |

**The local model is not meaningfully behind.** The correctness gap is 0.7
percentage points — one turn out of 69, well inside the noise of n=23. Both arms
ground their numbers equally well (98.6%), and the local model *leads* on context
retention. It is 1.3 s/turn slower and uses 43% fewer input tokens, because the
local engine runs the lean prompt.

Where they differ is instructive rather than damning:

- `gpt-4.1-mini` is stronger on **turn 1** (90.9% vs 82.6%) — the cold, unanchored
  question. Once the conversation gives the local model a referent to hold, it
  matches or beats the cloud on turns 2 and 3.
- On the out-of-range-year probe (`missing_year_1997`, where the data starts in
  2012), the cloud model correctly says no records exist. The local model answers
  *"total revenue for 1997 was 0"* — it **did not fabricate** (its groundedness
  scored 1.0, and its own insight line says "no orders were recorded"), but
  reporting `0` implies zero sales rather than no data. A real, if subtle, failure.
- `yoy_2016_2017` defeats **both** arms (33% / 50%). Multi-step year-over-year
  deltas per category are the hard case here, not a local-model weakness.

### Reproduce

```bash
# 1. build ground truth from the DB and publish the dataset
uv run python -m northwind_copilot.eval.multiturn.build_dataset --push

# 2. run each arm (writes a LangSmith experiment + full traces)
uv run python -m northwind_copilot.eval.multiturn.run_experiment --arm local
uv run python -m northwind_copilot.eval.multiturn.run_experiment --arm cloud

# 3. side-by-side table
uv run python -m northwind_copilot.eval.multiturn.compare <local-exp> <cloud-exp>
```

Needs `LANGSMITH_API_KEY`, `OPENAI_API_KEY` (cloud arm), and `OPENROUTER_API_KEY`
(judge). Experiments and per-turn traces land on the LangSmith dataset
`northwind-multiturn-analyst`.

### What the numbers do and don't support

- **n = 23.** A proportion is resolved to roughly ±10 points. Read the gaps, not
  the decimals: "indistinguishable on correctness" is supported; "the local model
  is 0.7% worse" is not.
- **The local arm runs with the cloud fallback disabled.** `build_agent_for`
  normally attaches `EscalateToFallbackMiddleware`, which would let `gpt-4.1-mini`
  silently answer gemma's failed turns — the arm would measure a hybrid.
- **Each arm uses the prompt the product actually gives it** (lean for local, full
  analyst prompt for cloud). This compares the two engines *as shipped*, not the
  same prompt on two models.
- **Latency is not apples-to-apples.** The local number is GPU compute on the
  machine above; the cloud number includes network round-trips from Egypt and
  depends on OpenAI's load.
- Cloud cost uses this repo's own rate card ([`metering/pricing.py`](northwind_copilot/metering/pricing.py)):
  $0.40/$1.60 per 1M input/output tokens.

### Why the local model is configured the way it is

Two findings from profiling this hardware, both encoded as defaults in
[`infra/llm.py`](northwind_copilot/infra/llm.py):

1. **Thinking is off.** Chain-of-thought cost **2.5× latency for identical
   accuracy** on the SQL benchmark (26.4 s → 10.5 s average; 9/11 correct either
   way, failing the same two questions).
2. **`num_ctx` is pinned to 8192.** Ollama defaults to 4096 regardless of what the
   model supports and truncates over-long prompts *from the head* — silently
   discarding the system prompt. Verified: at 4096 the model ignored a system rule
   that it obeyed at 8192.

Generation runs at ~45 tok/s, which is ~80% of this GPU's theoretical memory
bandwidth (448 GB/s spec sheet, 8 GB of weights streamed per token). **The GPU is
already saturated** — local speed is a function of model size, not runtime choice,
so swapping Ollama for another llama.cpp wrapper buys nothing.

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
| `OLLAMA_NUM_CTX` | `8192` | Local context window — see the warning below |
| `OLLAMA_REASONING` | `false` | Chain-of-thought on local thinking models |
| `OLLAMA_NUM_PREDICT` | `1024` | Cap on tokens generated per model call |
| `OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model resident |
| `OPENROUTER_API_KEY` | — | Required only by the multi-turn eval's judge |

> **Do not** use `DATABASE_URI` — LangGraph reserves that name for its own
> persistence layer and overwrites it with `:memory:` under `langgraph dev`.
> The RAG `search_docs` tool uses OpenAI embeddings, so questions about
> KPIs/categories/policies need `OPENAI_API_KEY` set even on the local engine.

> **Never lower `OLLAMA_NUM_CTX` below the trim budget** (`max_context_tokens`,
> 8000). Ollama's own default is 4096 and it truncates an over-long prompt
> *silently, from the head* — where the system prompt lives. The agent then
> loses its instructions mid-conversation with no error. This is a correctness
> setting, not a performance one.

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

The multi-turn eval's *instrument* is tested too
([`tests/test_multiturn_eval.py`](tests/test_multiturn_eval.py)): every reference
query must execute, return rows (unless it is the empty-result probe), and resolve
to an unambiguous top-1 answer. A silently wrong reference does not fail an
experiment — it produces a confident, wrong comparison, which is worse.

---

## License

Provided as-is for educational and evaluation purposes.
