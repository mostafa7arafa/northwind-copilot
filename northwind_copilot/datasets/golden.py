"""Select golden examples to inject into a dataset's prompt.

A golden example is a (question → SQL) pair a user confirmed with a thumbs-up.
Selection is deliberately simple for v1 — keyword overlap with the incoming
question, recency as the tie-breaker, no embeddings — because the corpus per
dataset is small (tens, not thousands) and the goal is style/formula transfer,
not retrieval precision.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.tenancy.models import GoldenExample

# How many examples one prompt carries. More would crowd out the schema.
TOP_K = 3
# Only consider reasonably recent examples so selection stays O(small).
_POOL = 50

_WORD_RE = re.compile(r"[\w؀-ۿ]+")  # latin + arabic word chars
_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "for",
    "by",
    "and",
    "or",
    "to",
    "what",
    "which",
    "how",
    "many",
    "much",
    "show",
    "me",
    "is",
    "are",
    "was",
    "were",
    "per",
    "with",
    "top",
    "all",
}


def _tokens(text: str) -> set[str]:
    """Lowercased content words of a question."""
    return {
        w
        for w in (m.group(0).lower() for m in _WORD_RE.finditer(text or ""))
        if len(w) > 2 and w not in _STOPWORDS
    }


async def select_examples(
    session: AsyncSession, dataset_id: str, question: str, k: int = TOP_K
) -> list[tuple[str, str]]:
    """Return up to ``k`` (question, sql) pairs relevant to this question.

    Examples sharing keywords with the question rank first (overlap count,
    then recency); if fewer than ``k`` match, the most recent remaining
    examples pad the list — seeing *any* confirmed SQL for this dataset
    teaches its formulas and idioms.
    """
    rows = list(
        (
            await session.execute(
                select(GoldenExample)
                .where(GoldenExample.dataset_id == dataset_id)
                .order_by(GoldenExample.created_at.desc())
                .limit(_POOL)
            )
        ).scalars()
    )
    if not rows:
        return []
    asked = _tokens(question)
    scored = sorted(
        enumerate(rows),
        key=lambda pair: (-len(asked & _tokens(pair[1].question)), pair[0]),
    )
    return [(ex.question, ex.sql) for _, ex in scored[:k]]
