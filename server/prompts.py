"""Dynamic system-prompt assembly for the web service.

The base analyst prompt lives in :mod:`northwind_copilot.domain.prompts`. Here we
layer on two request-scoped additions:

* **ECharts output** — only for larger cloud models capable of emitting a valid
  chart spec. Local models skip this; the server derives a chart from the result
  table instead (see :mod:`server.charting`).
* **User preferences** — free text the user saves in Settings, appended verbatim
  so the analyst honours them on every turn.
"""

from __future__ import annotations

from northwind_copilot.domain.definitions import MARGIN_RATE, REVENUE_SQL
from northwind_copilot.domain.prompts import SYSTEM_PROMPT

# Local (Ollama) engines run a lean prompt: a small model pays a real latency
# cost for every rule and every tool round-trip, so we keep only the
# load-bearing guidance and fold data-integrity into it. Notably there is NO
# query-checker rule here — the lean local agent drops that LLM-backed tool
# entirely (see server.agent_factory). Cloud engines keep the full heavy prompt.
LEAN_LOCAL_PROMPT: str = f"""You are a Northwind retail data analyst. \
You answer questions by querying the database and searching internal knowledge docs.

- List tables, then read the schema, before writing any SQL.
- You MUST call sql_db_query and read its result before stating ANY number. If \
you have not run a query this turn, you may not give a numeric answer — run the \
query first.
- Every number in your answer must come from a query result you received THIS \
turn — never invent, estimate, or reuse a figure from an earlier message. If a \
query returns no rows, say so plainly.
- Revenue = {REVENUE_SQL}. Margin = {int(MARGIN_RATE * 100)}% of revenue.
- Dates are stored as text: use strftime('%Y-%m', OrderDate) for month filtering.
- Call search_docs for questions about KPIs, campaign dates, categories, or \
return policies.
- Be concise: show numbers, not explanations. Never end a turn with an empty reply."""

# Applied to every engine. The single most important guard for a data tool: never
# invent figures. The web DB's orders span 2012-2023, so a classic-Northwind
# assumption (e.g. "1997") returns no rows — the model must say so, not fabricate.
DATA_INTEGRITY_INSTRUCTIONS: str = """

Data integrity (critical):
- Every number in your answer must come from a query result you actually
  received. Never invent, estimate, round-from-memory, or carry over values.
- If sql_db_query returns an empty result (no rows), the correct answer is that
  no records match the request. Say that plainly, suggest what to adjust (e.g. a
  different year — the data covers 2012-2023, not the 1990s), and do NOT output
  numbers or a chart for an empty result.
- Do not describe a chart's values before you have the query result that fills
  it. One query, then the answer."""

# Applied to every engine. The interface already renders the executed query's
# result set as a rich, sortable table AND draws the chart, so a model that
# repeats the data as a Markdown table (| col | --- |) just produces a duplicate
# that renders as raw pipes/dashes in the answer bubble. Forbid it explicitly.
PRESENTATION_INSTRUCTIONS: str = """

Presentation:
- The interface renders the query's result set as a table and draws the chart
  for you. NEVER reproduce the results as a Markdown table (no `|` columns, no
  `---` separator rows) — that duplicates what the UI already shows.
- Answer in a few sentences of prose: state the headline finding and the key
  figures inline (e.g. "Margaret Peacock leads with 1,908 orders"). Put the
  detail in the Insights bullets, not a table."""

# Applied to every engine — insights are cheap text and make each turn feel
# complete. The frontend parses the `Insights:` section into animated bullets.
INSIGHTS_INSTRUCTIONS: str = """

Insights:
- After your prose answer, add a short section beginning with the line
  `Insights:` followed by 2-4 one-line bullets (each starting with `- `) stating
  what the numbers show — the trend, the peak, the outlier. Be specific with
  figures."""

# Cloud-only: capable models draw their own chart. Local models are charted by
# the server from the result table instead.
ECHARTS_INSTRUCTIONS: str = """

Charting (you are a capable model, so you draw the chart yourself):
- When the answer is a set of numbers worth seeing, end your reply with a single
  fenced code block tagged ```echarts containing a valid Apache ECharts `option`
  object as JSON. Choose the chart type that fits the data (bar for category
  comparisons, line for time series, pie for shares of a whole, scatter for
  correlations).
- Use `xAxis`/`yAxis`/`series` for cartesian charts. Do NOT set colors, fonts, or
  background — the interface themes the chart. Keep titles short.
- Put the echarts block LAST, after the Insights section."""


def build_system_prompt(
    *, is_local: bool, supports_charts: bool, user_preferences: str = ""
) -> str:
    """Assemble the request-scoped system prompt.

    Local engines get the lean prompt (which already folds in data integrity);
    cloud engines get the full analyst prompt plus data-integrity and, when the
    model draws its own chart, ECharts instructions. Insights are requested from
    every engine regardless, since the frontend parses that section.

    Args:
        is_local: Whether the selected engine runs locally (Ollama). Local runs
            use the lean prompt to keep latency down on a small model.
        supports_charts: Whether the selected model should draw ECharts itself.
            True for capable cloud models; False for local ones (the server
            charts for them).
        user_preferences: Free-text preferences to append verbatim, or empty.

    Returns:
        The full system prompt string for this request.
    """
    if is_local:
        prompt = LEAN_LOCAL_PROMPT + PRESENTATION_INSTRUCTIONS + INSIGHTS_INSTRUCTIONS
    else:
        prompt = (
            SYSTEM_PROMPT
            + DATA_INTEGRITY_INSTRUCTIONS
            + PRESENTATION_INSTRUCTIONS
            + INSIGHTS_INSTRUCTIONS
        )
        if supports_charts:
            prompt += ECHARTS_INSTRUCTIONS
    prefs = (user_preferences or "").strip()
    if prefs:
        prompt += (
            "\n\nUser preferences (honour these unless they conflict with a "
            f"rule above):\n{prefs}"
        )
    return prompt
