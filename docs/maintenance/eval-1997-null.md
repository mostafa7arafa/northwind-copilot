# 1997 NULL aggregate correction

## Diagnosis and fix

Baseline: `ef95205` (`master`). The 1997 reference query already had
`HAVING COUNT(*) > 0`, correctly producing **no rows**. That safeguard is
retained, not presented as a newly fixed SQL predicate.

The runtime gap was elsewhere: the analyst instructions described empty result
sets but not SQL's one-row NULL aggregate. Removing the `HAVING` clause from
the same query reproduces `[(None,)]` on the supplied database. `SUM` over no
matching records is not a recorded revenue of zero.

- Local, cloud, and uploaded-dataset analyst prompts now require checking the
  matching row count before interpreting a NULL total. Genuine zero totals
  from matching records remain valid. The static POC `SYSTEM_PROMPT` is unchanged.
- The dataset builder rejects all-NULL reference values, including when a
  broken reference loses its `empty_result` tag. A genuine `0` remains valid.
- The affected eval question and expected answer explicitly distinguish no
  recorded data from zero revenue. The available order-year range is 2012–2023.
- The existing correct reference SQL is retained and the committed JSONL is
  regenerated. A regression checks the entire committed golden copy against
  current reference SQL and wording.

The initial regression command failed on both the NULL-only ground truth and
missing runtime guidance, then passed after the fix:

```bash
uv run pytest -q tests/test_multiturn_eval.py::TestNullAggregateRegression \
  tests/test_config_and_prompts.py::TestSystemPrompt::test_null_aggregate_guidance_for_every_engine_and_dataset
```

## Measurement scope

Date: 2026-10-30. Before: `ef95205`; after implementation: `461e340` plus the
committed-copy regression in `274ada9`. Both use the original `master` lockfile,
not the dependency updates from the independent quality-gates PR.

Database SHA-256:
`de44ede8a51bd9d22a2a10f55fdc83365cf082a7be03379617be41d553d4b98a`.
Single-turn dataset SHA-256:
`c5add5180317ef0f9a7957630ada5f1c31a7a35954180675f43c437a599d83fc`.

The local Ollama daemon is unavailable (`localhost:11434` refuses connections),
so a new local-model score cannot be claimed. Cloud replays use
`gpt-4.1-mini`, all 23 scenarios / 69 turns, and the existing correctness,
groundedness and context-retention evaluators with the existing Qwen judge.
References come from `build_all()` in each evaluated checkout. Completed
scenarios were checkpointed; remaining scenarios ran with up to four concurrent
conversations, matching the existing cloud experiment's concurrency cap.
Before and after runs overlapped: their latency is not a comparison metric.
Neither dataset nor traces were published; both LangSmith tracing env flags
were explicitly false. Raw local outputs remain under ignored `eval/results/`.

The affected question **and** its reference changed intentionally. This is an
instrument/prompt correction, not an isolated causal model-accuracy experiment.
The cloud baseline already handled this probe correctly; the historically
reported local failure cannot be rechecked without Ollama.

## Cloud before/after scores

Both arms have all 69 correctness verdicts after replaying one missing baseline
judge verdict once against its **unchanged saved answer**. That verdict was 0;
no model answer was rerun or selected. Initial missing verdicts: before 1,
after 0; final missing verdicts: 0/0. All 69 groundedness verdicts and all 23
context-retention verdicts are present in both arms.

| Metric | Before | After |
| --- | ---: | ---: |
| Correctness | 89.9% (62/69) | 89.9% (62/69) |
| Groundedness (`no_hallucination`) | 100% (69/69) | 98.6% (68/69) |
| Context retention | 91.3% (21/23) | 91.3% (21/23) |
| 1997 probe T1 correctness | 1/1 | 1/1 |
| 1997 conversation correctness | 3/3 | 3/3 |
| Turn errors | 0/69 | 0/69 |

Before answer: “There are no records of orders with revenue in the year 1997
in the database. You may want to check for a different year within the data
range available (2012-2023).”

After answer: “There is no data for orders placed in 1997. The available
order-year range in the database is from 2012 to 2023.”

There is **no measured correctness gain**. The single groundedness failure
after the change is in `yoy_2016_2017`, not the 1997 probe. This small,
non-repeated, partly reworded experiment does not establish an overall quality
change. The historical Windows local/cloud table is preserved; the README
adds a separately labelled cloud recheck rather than mixing new cloud figures
with an unrepeated historical local arm.

Compact per-scenario scores and probe answers are committed in
[`eval-1997-null-results.json`](eval-1997-null-results.json). Reproduction uses
`build_all()`, `build_arm("cloud")`, and `run_conversation()` with each record's
three questions. Pass those saved outputs and that checkout's references to
`correctness_evaluator`, `hallucination_evaluator`, and
`context_retention_evaluator`. Aggregate each evaluator's scores across all
23 scenarios; do not drop missing verdicts. These are the same evaluator
functions as the existing LangSmith runner, but results are saved locally and
tracing stays disabled. The original LangSmith reproduction command is also
in the README; it publishes traces and is not what this recheck used.

## Standard single-turn benchmark

Re-run command:

```bash
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
  uv run python -m northwind_copilot.eval.run_benchmark
```

Result: **8/18 (44.4%)**, 5.25 s average, 10/18 answers recorded a GPT fallback.
Eight questions failed with `ConnectError: connection refused` when the static
graph's SQL checker tried the unavailable local model; two others completed but
failed their graders. This run is an environment-limited hybrid diagnostic, not
a replacement for the historical local benchmark or the cloud-only multi-turn
comparison. SQLite thread-affinity errors were also logged during connection
cleanup; the protected adapter is not changed by this task.
