"""LLM-as-judge scorers for the multi-turn experiment.

Three judged dimensions, all scored by one model from a *third* family (Qwen, via
OpenRouter). Neither arm under test is a Qwen model, so the judge has no
same-family preference for either the local Gemma or the cloud GPT — a judge from
either family would tilt the very comparison the experiment exists to make. That
also rules out Gemini, which shares a family with Gemma.

The judge was chosen empirically, not by reputation. ``openevals`` calls
``judge.with_structured_output(...)``, which several OpenRouter-hosted models
handle badly:

* ``qwen/qwen3.7-plus`` — served only by Alibaba, whose endpoint rejects the
  ``response_format`` LangChain sends. No second provider to route around it.
* ``qwen/qwen3-235b-a22b-2507`` — leaks its ``<think>`` block into the JSON.
* ``mistralai/mistral-small-3.2-24b-instruct`` — returns JSON with the wrong keys.

``qwen3-30b-a3b-instruct-2507`` emits clean structured output, is non-thinking
(~3s per judgement, which matters across ~160 judgements per arm), and costs
$0.048/$0.193 per 1M tokens. Before use it was verified to score a wrong answer 0
and a right answer 1 on both the correctness and the hallucination rubric.

Score polarity is uniform: **higher is always better**, including
``no_hallucination`` (openevals' hallucination rubric returns true for a
response that is *free* of hallucination, so the key is named for what a 1
means rather than for the failure it detects).
"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_openai import ChatOpenAI
from openevals.llm import create_llm_as_judge
from openevals.prompts import CORRECTNESS_PROMPT

JUDGE_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


# openevals' stock HALLUCINATION_PROMPT is unusable here. Tried against a real
# turn, it scored a fully grounded answer 0 for two reasons: it called rounding
# 1,004,396.125 -> "1,004,396.13" a factual error, and it called the sentence
# "Q2 was the strongest period" an unsupported subjective claim. But the agent's
# own INSIGHTS_INSTRUCTIONS *require* that interpretation, and 2dp rounding is
# what an analyst does. The stock rubric therefore floors both arms and measures
# nothing. This rubric grades the property the product actually promises: every
# figure traces to a query result from this conversation.
GROUNDEDNESS_PROMPT = """You are grading a SQL-analyst agent for groundedness.

You will see the user's question, the agent's answer, and the CONTEXT: every tool
call the agent made in this conversation so far, each with the result it returned.

<Rubric>
A grounded answer:
- States only figures that appear in a tool result, or follow arithmetically from
  one (a sum, a share, a difference, a comparison of two retrieved numbers).
- Names only entities (products, employees, categories, months) that appear in a
  tool result from this conversation — including results from EARLIER turns, since
  a follow-up legitimately refers back to what was already retrieved.
- Reports "no rows"/"no records" when the query returned nothing.

An answer is NOT grounded when it:
- States a figure that appears in no tool result and cannot be derived from one.
- Invents a figure for a query that returned zero rows, or answers from world
  knowledge instead of from the data.
- Names an entity that never appears in any tool result.
- Contradicts a tool result.

Explicitly ALLOWED — never penalise these:
- Rounding or reformatting a retrieved number (1004396.125 -> "1,004,396.13";
  0.216 -> "21.6%"; thousands separators).
- Interpretive prose that follows from the retrieved rows: calling the largest
  value "the strongest", noting a trend, ranking retrieved figures. The agent is
  required to write an "Insights:" section, so commentary is expected.
- Omitting the SQL, the schema, or the filter from the prose answer.
- Carrying forward an entity or constraint established earlier in the conversation.
</Rubric>

<Instructions>
1. List every figure and named entity asserted in the answer.
2. For each, find it in the context, or show it follows arithmetically from
   values in the context. Earlier-turn results count as context.
3. Ignore formatting, rounding, and interpretive commentary entirely.
4. Return true if every figure and entity is grounded; false if even one is
   fabricated, contradicted, or produced for an empty result set.
</Instructions>

<question>
{inputs}
</question>

<answer>
{outputs}
</answer>

<context>
{context}
</context>
"""


# openevals ships KNOWLEDGE_RETENTION_PROMPT, but its rubric grades facts the
# *human* introduced ("the agent asks for information it has already been
# given"). In these scenarios the referent of "that product" / "their revenue"
# is introduced by the agent's own turn-1 answer, so that prompt would score the
# wrong thing. This prompt grades anaphora resolution against the conversation
# and the ground truth together.
CONTEXT_RETENTION_PROMPT = """You are an expert evaluator of multi-turn \
data-analyst conversations.

You will see a full conversation between a user and a SQL-analyst agent, plus the
ground-truth answer for each turn.

Later user turns deliberately refer back to earlier ones using anaphora — phrases
like "that product", "their total revenue", "those orders", "and the worst?",
"what about 2017?". The referent is usually a value the AGENT itself produced in
an earlier turn, not something the user stated.

<Rubric>
Good context retention:
- Each referring expression is resolved to the correct entity from earlier in the
  conversation (the right product, employee, category, customer, month).
- The agent carries forward constraints established earlier, such as the year or
  the filter, when the later turn does not restate them.
- Follow-up answers stay consistent with the entity the agent named earlier.

Poor context retention:
- The agent resolves a referring expression to the wrong entity, or silently
  switches to a different one.
- The agent drops an earlier constraint (e.g. answers for all years when the
  conversation established 2017).
- The agent asks the user to restate something the conversation already fixed.
- The agent re-answers the first question instead of the follow-up.
</Rubric>

<Instructions>
1. For each turn after the first, identify every referring expression and what it
   should resolve to, using the earlier turns and the reference answers.
2. Check whether the agent's answer is about that referent and honours the
   carried-forward constraints.
3. Judge ONLY reference resolution and constraint carry-over. Do not penalise a
   wrong number if the agent clearly reasoned about the correct entity — numeric
   accuracy is scored separately.
4. Return true only if every referring expression across the conversation was
   resolved correctly.
</Instructions>

<user_questions>
{inputs}
</user_questions>

<conversation>
{outputs}
</conversation>

<reference_answers>
{reference_outputs}
</reference_answers>
"""


#: Bounds a runaway judgement. Observed in practice: the judge looped to 32,000
#: completion tokens on a 527-token prompt, crashing the evaluator (and costing
#: ~$0.006 a call). Real judgements are a few hundred tokens.
JUDGE_MAX_TOKENS = 2048

#: Temperature 0 makes judgements reproducible, but a degenerate loop at
#: temperature 0 repeats identically on retry. The retry nudges sampling just
#: enough to break the loop. Normal judgements never reach it.
JUDGE_TEMPERATURES = (0.0, 0.4)


@lru_cache(maxsize=4)
def judge_model(temperature: float = 0.0) -> ChatOpenAI:
    """Build the judge chat model, cached per temperature.

    Raises:
        RuntimeError: If ``OPENROUTER_API_KEY`` is not configured.
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is required to run the judge "
            f"({JUDGE_MODEL} is served via OpenRouter)."
        )
    return ChatOpenAI(
        model=JUDGE_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=key,
        temperature=temperature,
        max_tokens=JUDGE_MAX_TOKENS,
        # A stalled provider must not hang a 23-scenario run.
        timeout=60,
        max_retries=2,
    )


@lru_cache(maxsize=4)
def correctness_judge(temperature: float = 0.0):
    """Judge one turn's answer against its computed ground truth."""
    return create_llm_as_judge(
        prompt=CORRECTNESS_PROMPT,
        feedback_key="correctness",
        judge=judge_model(temperature),
    )


@lru_cache(maxsize=4)
def hallucination_judge(temperature: float = 0.0):
    """Judge whether a turn's answer is grounded in that turn's tool output.

    ``context`` is deliberately the agent's OWN tool calls and their results —
    cumulative across the conversation — not the reference answer. The product's
    rule is "every number must come from a query result you received"; grading
    against the reference would reward a model that guessed the right number
    without running a query.

    The tool *arguments* are part of the context, not just the results. A row
    reading ``revenue=4590093.58`` cannot justify the claim "in 2017"; only the
    query's WHERE clause can. Omit the arguments and every grounded answer looks
    fabricated.
    """
    return create_llm_as_judge(
        prompt=GROUNDEDNESS_PROMPT,
        feedback_key="no_hallucination",
        judge=judge_model(temperature),
    )


@lru_cache(maxsize=4)
def context_retention_judge(temperature: float = 0.0):
    """Judge reference resolution across the whole conversation."""
    return create_llm_as_judge(
        prompt=CONTEXT_RETENTION_PROMPT,
        feedback_key="context_retention",
        judge=judge_model(temperature),
    )


def judge_with_retry(judge_factory, **kwargs) -> dict | None:
    """Call a judge, breaking a degenerate loop by nudging temperature.

    A judgement that overruns ``JUDGE_MAX_TOKENS`` raises rather than returning a
    parseable verdict. Letting that exception escape kills the whole evaluator
    for that example, which silently drops its scores from the experiment mean —
    a far worse outcome than one re-judged turn.

    Args:
        judge_factory: One of the ``*_judge`` factories above.
        **kwargs: Passed through to the judge (``inputs``, ``outputs``, ...).

    Returns:
        The verdict dict, or ``None`` if every temperature failed.
    """
    for temperature in JUDGE_TEMPERATURES:
        try:
            return judge_factory(temperature)(**kwargs)
        except Exception:  # noqa: BLE001 - any parse/length failure is retryable
            continue
    return None
