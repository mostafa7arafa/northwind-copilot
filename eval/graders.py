"""Fuzzy graders for benchmark answers.

The agent returns free-text, so we grade by checking that the expected
values *appear* in the answer rather than demanding an exact string match.
Each grader returns (passed: bool, detail: str).
"""

from __future__ import annotations

import re

# Matches numbers like 1,234.56  -1234  21018.7  558.75
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers_in(text: str) -> list[float]:
    out: list[float] = []
    for m in _NUMBER_RE.findall(text):
        cleaned = m.replace(",", "")
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


def number_appears(answer: str, target: float, rel_tol: float = 0.01,
                   abs_tol: float = 0.5) -> bool:
    """True if some number in `answer` matches `target` within tolerance.

    Relative tolerance (default 1%) absorbs rounding differences; the small
    absolute floor handles near-zero targets and integer counts.
    """
    tol = max(abs_tol, abs(target) * rel_tol)
    return any(abs(n - target) <= tol for n in _numbers_in(answer))


def text_appears(answer: str, needle: str) -> bool:
    return needle.lower() in answer.lower()


def grade_numeric(answer: str, expected) -> tuple[bool, str]:
    ok = number_appears(answer, float(expected))
    return ok, f"expected ~{expected}; found numbers {_numbers_in(answer)[:8]}"


def grade_contains_all(answer: str, expected: list[str]) -> tuple[bool, str]:
    missing = [s for s in expected if not text_appears(answer, s)]
    return (not missing), (f"missing: {missing}" if missing else "all present")


def grade_fields(answer: str, expected: dict) -> tuple[bool, str]:
    misses = []
    for key, val in expected.items():
        if isinstance(val, (int, float)):
            if not number_appears(answer, float(val)):
                misses.append(f"{key}={val}")
        else:
            if not text_appears(answer, str(val)):
                misses.append(f"{key}={val!r}")
    return (not misses), (f"missing: {misses}" if misses else "all fields present")


def grade_rows(answer: str, expected: list[dict]) -> tuple[bool, str]:
    misses = []
    for i, row in enumerate(expected):
        ok, detail = grade_fields(answer, row)
        if not ok:
            misses.append(f"row{i}:{detail}")
    return (not misses), ("; ".join(misses) if misses else "all rows present")


GRADERS = {
    "numeric": grade_numeric,
    "contains_all": grade_contains_all,
    "fields": grade_fields,
    "rows": grade_rows,
}


def grade(grader: str, answer: str, expected) -> tuple[bool, str]:
    fn = GRADERS.get(grader)
    if fn is None:
        return False, f"unknown grader {grader!r}"
    return fn(answer, expected)
