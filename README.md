# Northwind Copilot

[![CI](https://github.com/mostafa7arafa/northwind-copilot/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/mostafa7arafa/northwind-copilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/release/python-3120/)

A personal, local-first workspace for chatting with your data. Upload CSV,
XLSX, or SQLite files, or explore the built-in Northwind sample. Inspect and
edit SQL, save conversations, and export tables and charts. Use Ollama locally
or choose OpenAI/OpenRouter—no login, organizations, billing, or subscriptions.

The separate static Northwind agent uses Ollama (`gemma4-12b`) with optional
OpenAI fallback (`gpt-6-luna`) on errors or empty responses. The web app lets
you choose its engine directly. The previous SaaS implementation is preserved
as an archived, unmaintained
[`saas/paused`](https://github.com/mostafa7arafa/northwind-copilot/tree/saas/paused)
snapshot; this product is intentionally single-user.

It ships three ways to use it:

- a **LangGraph agent** (`langgraph dev`),
- a **FastAPI + Next.js web app** — the "Northwind Trading Desk" (see
  [WEBAPP.md](WEBAPP.md)),
- a **benchmark harness** that grades the agent against a labelled dataset.

[![Northwind Copilot demo: a question becomes SQL, result rows and a revenue chart](docs/assets/demo.gif)](docs/assets/northwind-demo.mp4)

[Watch the full 28-second silent demo](docs/assets/northwind-demo.mp4)

*Real app footage using Northwind sample data and a cloud model. Waiting time trimmed.*

## Results at a glance

23 scenarios / 69 turns per arm. Higher is better for the judged metrics.
Local `gemma4-12b` against cloud `gpt-4.1-mini`.

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

The machine, the judge, what the gaps do and don't support, and how to
reproduce the run are in
[Evaluation](#evaluation-can-a-local-model-actually-do-this-job).

---

## Architecture

`langgraph.json` compiles `northwind_copilot/query/graph.py:graph`
(`create_agent`). Besides `__start__` and `__end__`, the compiled graph has
three nodes: `trim_context.before_model`, `model`, and `tools`. Local-to-cloud
escalation is not its own node.
`EscalateToFallbackMiddleware.wrap_model_call` runs inside `model`: it calls
Ollama first, and calls OpenAI only when that call raises or returns an empty
completion (no text and no tool call). With no `OPENAI_API_KEY`,
`build_fallback_model` returns `None` and there is nothing to escalate to.

```mermaid
flowchart TD
    startNode([__start__]) --> trim["trim_context.before_model"]
    trim --> primary["model: ChatOllama PRIMARY_MODEL"]
    primary --> gate{"usable response?"}
    gate -->|yes| route{tool calls?}
    gate -->|no| hasKey{"OPENAI_API_KEY set?"}
    hasKey -->|yes| fallback["model: ChatOpenAI FALLBACK_MODEL"]
    hasKey -->|no| stopNode["stop: re-raise, or return the empty completion"]
    fallback --> fbGate{"usable response?"}
    fbGate -->|yes| route
    fbGate -->|no| stopNode
    route -->|yes| tools["tools"]
    route -->|no| endNode([__end__])
    tools --> trim
```

The diamonds are that middleware decision, drawn so the escalation path is
visible. They are not extra LangGraph nodes. On the stop path the middleware
re-raises only when every model raised and none returned a message; an empty
completion is returned instead, and the loop ends because that message has no
tool call. `tools` is a single node. On this static graph it exposes
`sql_db_list_tables`, `sql_db_schema`, `sql_db_query`, `sql_db_query_checker`,
and `search_docs` (FAISS over `docs/*.md`).

For the web request path and local storage boundaries, see the
[architecture guide](docs/maintenance/architecture.md).

Application and evaluation Python code lives in the single package `northwind_copilot/`, split into
concern-focused layers. Dependencies point **inward**: `web` → `response` →
`query` → `infra` → `core`; nothing in `core` imports anything above it.
`core` is config, KPI definitions, and prompts. `infra` is the database, the
Ollama and OpenAI factories, and the doc index. `query` is the graph, the
per-request engine builder (`ollama`, `openai`, or `openrouter`), and the
middleware. `response` turns a finished turn into a table, a chart, and SSE
events. `web` is the FastAPI service. `eval` is the benchmark harness. The
Next.js Trading Desk lives in `frontend/`; the knowledge base is `docs/`; the
database is `data/northwind.sqlite` (orders span 2012–2023, not classic
1996–98).

### Package layout

The runtime graph above is not a folder map. The diagram below shows the
principal package dependencies, not every import. Datasets and conversations
use a local persistence layer; there is no account or tenant context.

```mermaid
flowchart TD
    subgraph analyst["northwind_copilot/ — analyst layers and evaluation"]
        web["web/ — FastAPI, model registry, preferences, security"]
        response["response/ — SSE, SQL results, charts"]
        query["query/ — graph, agent factory, middleware"]
        infra["infra/ — database, model factories, document index"]
        core["core/ — config, definitions, prompts, observability"]
        evaluation["eval/ — benchmark harness, graders, multiturn"]
        web --> response --> query --> infra --> core
        evaluation --> query
    end
    subgraph workspace["northwind_copilot/ — personal workspace"]
        datasets["datasets/ — upload, schema, golden examples"]
        conversations["conversations/ — saved history and feedback"]
        persistence["persistence/ — local SQLite metadata"]
        datasets --> persistence
        conversations --> persistence
    end
    web --> datasets & conversations & persistence
    frontend["frontend/ — Next.js"] -->|HTTP / SSE| web
    langgraph["langgraph.json"] --> query
```

`northwind_copilot/eval/` contains Python code; root `eval/results/` stores
benchmark artifacts. `tests/` holds the offline suite, `scripts/` holds
support tooling, and `dev.sh` starts the personal workspace. SaaS migrations
and production deployment files belong to the archived, unmaintained
[`saas/paused`](https://github.com/mostafa7arafa/northwind-copilot/tree/saas/paused)
snapshot, not this branch. `docs/*.md` is runtime knowledge-base content;
maintenance notes belong in subdirectories such as `docs/maintenance/`.

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

## Quickstart

Requires **Python 3.12+**, [uv](https://docs.astral.sh/uv/), **Node.js 20+**,
npm, curl, and Bash (Linux/macOS or WSL).

```bash
./dev.sh --setup                      # install locked dependencies once
# Optional: cp .env.example .env, then configure your model keys
./dev.sh                             # http://127.0.0.1:3000
```

Ctrl+C stops both servers. No Docker, database service, account setup, or
separate LangGraph server is needed. Ollama is only required when you choose a
local engine; start it separately and pull a model first.

Uploads and saved conversations live in `data/datasets/` and
`data/workspace.sqlite`. Old SaaS data is not automatically imported or
modified. This app is **loopback-only**, not a public service; do not expose it
through a public tunnel or reverse proxy.

### Cloud-only (no GPU)

The static graph always constructs an Ollama primary
(`build_primary_model`). You do not need a GPU if a cloud key is set: a failed
or empty local call escalates inside `model`. The Trading Desk can skip Ollama
entirely by choosing the OpenAI engine, which never builds the local model.

From [`.env.example`](.env.example):

| Variable | Needed without Ollama |
| --- | --- |
| `OPENAI_API_KEY` | Required. Builds the OpenAI fallback and the RAG embeddings. |
| `FALLBACK_MODEL` | Cloud model the static graph escalates to. Default `gpt-6-luna`. |
| `EMBEDDING_MODEL` | OpenAI embeddings for `search_docs`. Default `text-embedding-3-small`. Uses the same `OPENAI_API_KEY`. |
| `OPENROUTER_API_KEY` | Optional alternative cloud provider for the web app. |

`PRIMARY_MODEL` and `OLLAMA_BASE_URL` are unused once you select the OpenAI
engine in the web app. Configure server keys in `.env` or enter a key in
Settings (browser-entered keys stay in memory). Protected API routes accept
only loopback clients/hosts and allowed local browser origins.

```bash
uv run langgraph dev                  # Ollama is tried first; errors escalate
# or the web app, then pick OpenAI in the header (see Usage)
```

### Windows notes

- `uv` needs `--native-tls` to reach PyPI:
  `uv sync --group dev --group web --native-tls`.
- Set `PYTHONIOENCODING=utf-8` before commands that print query results. Some
  product and customer names carry accented characters that crash the Windows
  console.

### Run tests

```bash
uv sync --frozen --group dev --group web && uv run pytest
```

The suite runs fully offline — no LLM or network calls.

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
./dev.sh                             # backend + frontend, with readiness checks
```

### Run the benchmark

```bash
uv run python -m northwind_copilot.eval.run_benchmark
uv run python -m northwind_copilot.eval.run_benchmark --id sql_employee_count_usa
uv run python -m northwind_copilot.eval.run_benchmark --limit 3 --no-save
```

Results (accuracy, which model answered, latency) are written to
`eval/results/latest.json`. On Windows, set `PYTHONIOENCODING=utf-8` first
([Windows notes](#windows-notes)).

To compare cloud fallback candidates independently of the local primary, run
`uv run python scripts/compare_fallbacks.py` (three paired repetitions, local
results only). See the [GPT-6 Luna fallback comparison](docs/maintenance/luna-fallback.md).

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

See the [NULL-fix recheck methodology and limitations](docs/maintenance/eval-1997-null.md).

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
| `FALLBACK_MODEL` | `gpt-6-luna` | Cloud escalation model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embeddings for RAG |
| `NORTHWIND_DATABASE_URI` | `sqlite:///data/northwind.sqlite` | Sample analyst database |
| `WORKSPACE_DATABASE_URL` | `sqlite+aiosqlite:///data/workspace.sqlite` | Personal workspace metadata |
| `DATASET_DATA_DIR` | `data/datasets` | Uploaded dataset files |
| `DOCS_DIR` | `docs` | Markdown knowledge base |
| `FAISS_PATH` | `.faiss_index` | On-disk vector index |
| `REINDEX` | `false` | Rebuild the FAISS index on next load |
| `OPENAI_API_KEY` | — | Enables the fallback **and** RAG embeddings |
| `OLLAMA_NUM_CTX` | `8192` | Local context window — see the warning below |
| `OLLAMA_REASONING` | `false` | Chain-of-thought on local thinking models |
| `OLLAMA_NUM_PREDICT` | `1024` | Cap on tokens generated per model call |
| `OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model resident |
| `OPENROUTER_API_KEY` | — | Web cloud engine and multi-turn eval judge |

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

# Coverage (includes branches and missing paths)
uv run pytest --cov --cov-report=term-missing

# Dead-code gate (80%+ confidence; exact false positives documented inline)
uv run vulture

# Lower-confidence review list only — do not automatically delete findings
uv run vulture --min-confidence 0

# Lint gate (run before shipping)
uv run ruff check . --fix && uv run black . && uv run mypy
```

The tests use fakes for external services so the suite never touches Ollama,
OpenAI, or the network. The [historical cleanup audit](docs/maintenance/cleanup.md)
records the pre-simplification baseline. Current manual checks are in the
[validation guide](docs/maintenance/VALIDATION.md). `run_sql` and `build_database`
run against the real `northwind.sqlite` **read-only**.

The multi-turn eval's *instrument* is tested too
([`tests/test_multiturn_eval.py`](tests/test_multiturn_eval.py)): every reference
query must execute, return rows (unless it is the empty-result probe), and resolve
to an unambiguous top-1 answer. A silently wrong reference does not fail an
experiment — it produces a confident, wrong comparison, which is worse.

---

## License

[MIT](LICENSE). Copyright 2026 Mostafa Arafa. The software is provided as-is
and may be used for educational and evaluation purposes.
