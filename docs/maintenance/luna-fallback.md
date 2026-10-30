# GPT-6 Luna fallback evaluation

## Scope and predeclared decision rule

Date: 2026-10-30. Base: `ef95205` (`master`), independent of the quality-gates
and 1997-NULL PRs. The comparison uses the existing 18-question
`benchmark_dataset.jsonl` and its existing graders, without changing any
question, expected answer, static prompt, SQL guard or production model logic.

Before collecting the full run, “not meaningfully slower or more expensive”
was operationalized as no more than a **10% increase in either p50 or p95
latency or mean inference cost/question**. Accuracy must be at least the
baseline's aggregate accuracy, with no worse tool-failure count or invocation
errors and no missing usage measurements. These are conservative operational
thresholds, not claims of statistical significance.

## Method

```bash
uv run python scripts/compare_fallbacks.py
```

- Three repetitions, all 18 questions: **54 questions per candidate**, 108 total.
  These are repetitions of 18 unique questions, not 54 independent examples.
- Serial execution, alternating AB/BA order across questions and repetitions.
  A fresh message state is used every time; no checkpointer or prior answer.
- Both candidates use the static `SYSTEM_PROMPT`, SQL toolkit, document search,
  recursion limit 50 and the static graph's context trim. The SQL checker uses
  the candidate too, so a missing local model cannot confound the comparison.
- Models are constructed by the unchanged `build_model`. Luna uses its existing
  required `reasoning_effort="none"` configuration; GPT-4.1 mini uses its existing
  configuration. No Fast/priority tier, custom caching, insecure TLS, or tracing
  is enabled. LangSmith tracing flags are explicitly false.
- One-time document-index loading is outside both candidates' timing. Tool
  execution, query checking, model requests, network waits and automatic SDK
  retries are inside each question's elapsed time. p50/p95 use linear sample
  interpolation, not averages of per-repeat percentiles.
- Callbacks collect **all nested chat-model usage**, including SQL checker
  calls, not just final agent-message tokens. Missing usage produces an unknown
  cost, never zero. Costs include reported cache reads and writes at their
  distinct rates; the sum is averaged over every attempted question.
- Cost is **chat inference only**, not an invoice total: document-query
  embeddings, setup/index construction, and the unmeasured local-primary
  attempt are excluded. No LLM judge is used; accuracy uses existing deterministic
  graders. Caching is the provider's normal automatic caching, so these are
  observed warm/mixed-cache costs, not guaranteed cold-request costs.
- Failed grades and invocation errors stay in the denominator. Tool failures
  include error-status tool messages, SQL tools' `Error:` text, invalid generated
  tool calls, and callback-captured failures if an invocation aborts. Unknown
  tool-name errors are counted even without a tool-start callback. Node updates
  and callback events are reconciled by tool-call ID; unanswered requested
  calls on an aborted invocation also count as failed attempts.

This is a **candidate-model comparison**, not a benchmark of the complete
local-first escalation path. Ollama is unavailable on this machine, so the
full hybrid route is not measured. It also means the cloud candidate answers
its own SQL-checker requests, unlike the static graph's local-backed checker.
No production escalation logic is changed by the benchmark.

## Pricing sources

Checked against OpenAI's primary documentation on 2026-10-30. USD per 1M tokens,
Standard short-context requests (at most 272K input tokens):

| Model | Ordinary input | Cached input | Cache write (30m) | Output |
| --- | ---: | ---: | ---: | ---: |
| GPT-4.1 mini | $0.40 | $0.10 | $0.40 (ordinary input rate) | $1.60 |
| GPT-6 Luna | $0.10 | $0.01 | $0.125 | $0.50 |

GPT-4.1 mini has no separate cache-write surcharge. For Luna, cache-write
pricing is a replacement input rate, **not** an additive surcharge. The harness
subtracts cached/read and written input from ordinary input before pricing.
Long-context requests are rejected by this rate-card calculation rather than
silently priced at the short-context rate.

Sources:
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- [GPT-6 Luna model and Chat Completions tool requirements](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [GPT-4.1 mini model pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Prompt caching and non-additive cache-write billing](https://developers.openai.com/api/docs/guides/prompt-caching)

## Results and decision

| Metric | GPT-4.1 mini | GPT-6 Luna |
| --- | ---: | ---: |
| Accuracy | 87.0% (47/54) | 100% (54/54) |
| p50 latency / question | 5.78 s | 11.02 s |
| p95 latency / question | 11.08 s | 13.71 s |
| Mean inference cost / question | $0.001950 | $0.000528 |
| Tool-call failures | 0/208 | 0/232 |
| Invocation / model errors | 0 / 0 | 0 / 0 |
| Missing usage records | 0 | 0 |
| Chat-model calls (including checker) | 271 | 320 |

Per-repeat accuracy: mini **16/18, 15/18, 16/18**; Luna **18/18 in all three**.
Mini repeatedly missed the summer top-category and winter AOV questions; it
also missed the best-month answer once. These are grader failures, not tool
or transport failures. Luna had higher observed accuracy and **72.9% lower
inference cost**, but **90.6% higher p50** and **23.7% higher p95 latency**.
Both latency increases exceed the predeclared 10% tolerance.

**Decision: retain `FALLBACK_MODEL=gpt-4.1-mini`.** Luna does not satisfy the
requested conjunction of at-least-equal accuracy **and** no meaningful slowdown
or cost increase. Its accuracy/cost advantages do not authorize accepting an
approximately doubled typical wait. No production default, fallback builder,
GPT-6 reasoning configuration or SQL guard is changed. Choosing an explicit
accuracy-for-latency tradeoff would be a separate user decision.

Compact per-question answers, grader details, latency, usage totals, costs,
per-repeat and overall aggregates are in
[`luna-fallback-results.json`](luna-fallback-results.json). Every attempted
question is retained, including the seven mini grader failures. All individual
chat requests were within the short-context rate-card bound.

The full run used harness `a19eea1`. Review then hardened aborted-question
accounting in `9392e2d`. **All 108 measured invocations returned successfully**,
so the corrected abort path cannot alter their tool-failure counts; no results
were removed, rerun or selected to improve the comparison. The hardened version
also passed a separate paired one-question live smoke test (excluded from the
54-question-per-model decision table).

SQLite thread-affinity exceptions were logged on connection cleanup during
the run, as in the earlier baseline environment. No measured invocation or
tool call failed; the protected adapter is unchanged. These small repeated
samples and network-dependent timings are operational evidence, not a claim
that Luna is universally slower or always perfectly accurate.

## Validation

Offline accounting tests cover cache-read/write arithmetic, short-context
bounds, nested checker usage, missing usage, model errors, invalid tool calls,
unknown-tool errors, aborted invocations, exception redaction, percentile
interpolation and retention of failed questions in summaries. A real offline
LangGraph test verifies an unknown-tool error survives a later node failure;
additional cases cover missing node updates and callback/result deduplication.
The original harness reproduced that review finding as 0 attempts / 0 failures
instead of 1/1; the hardened accounting passes the regression.
