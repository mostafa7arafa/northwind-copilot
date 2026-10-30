# GPT-6 Luna fallback comparison

## Method

- Measured on 2026-10-30 from master `ef95205`, independently of the other PRs:
  three repetitions of the existing 18-question dataset (**54/model**), with
  unchanged questions, deterministic graders, static prompt, SQL tools and trim.
- Serial AB/BA order and fresh message state. Each candidate answers directly
  and handles its own SQL-checker calls, avoiding the unavailable local Ollama.
  Models use unchanged `build_model`, including Luna's required reasoning `none`.
- Latency includes tools, nested checker requests and SDK retries; index loading
  is outside timing. Costs include all nested chat-model usage and reported
  cache reads/writes at Standard short-context rates. All usage is present;
  failed grades remain in the denominator. No tracing or publication.
- Reproduce with `uv run python scripts/compare_fallbacks.py`; raw local results
  go to ignored `eval/results/luna-fallback.json`. The committed
  [compact summary](luna-fallback-results.json) records aggregates and every
  question's pass/fail in repetition order 1, 2, 3.

## Results

| Metric | GPT-4.1 mini | GPT-6 Luna |
| --- | ---: | ---: |
| Accuracy | 87.0% (47/54) | 100% (54/54) |
| p50 latency / question | 5.78 s | 11.02 s |
| p95 latency / question | 11.08 s | 13.71 s |
| Mean chat-inference cost / question | $0.001950 | $0.000528 |
| Tool-call failures | 0/208 | 0/232 |
| Invocation / model errors | 0 / 0 | 0 / 0 |

Luna was **100% vs 87% accurate and 73% cheaper**, with about **1.9× p50
latency (+5.2 s)** and **1.24× p95**. The fallback runs only when the local
model fails, so the owner chooses this accuracy/cost/latency tradeoff.
`FALLBACK_MODEL` is unchanged in this PR.

## Pricing sources

OpenAI Standard short-context pricing checked on 2026-10-30; the script contains
its rate card, including cache reads/writes:
[pricing](https://developers.openai.com/api/docs/pricing),
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## Limitations

- This measures cloud candidates, **not full local-first escalation**. The
  unavailable local primary and its failed-attempt latency are not measured;
  the candidate-backed checker differs from the static graph's local checker.
- Costs exclude embeddings, setup and local-primary attempts; these are observed
  mixed-cache chat estimates, not invoices or guaranteed cold-request prices.
- Repeated samples cover only 18 unique questions; network timing varies.
  These results do not establish universal accuracy or latency.
- SQLite thread-affinity exceptions appeared during connection cleanup, without
  measured invocation/tool failures. Exact error/location is in the PR for a
  separate issue; the adapter is untouched.
- The full run used `a19eea1`; subsequent abort-metering hardening `9392e2d`
  cannot affect its 108 successfully returned invocations. A later paired smoke
  test is excluded from the table. The harness and its 18 offline tests remain.
