"""Run mypy with an exact, fail-closed baseline for protected source files.

Unlike module-wide ignores, this checks every diagnostic and rejects stale
baseline entries. From the repository root, run:
``uv run python scripts/check_types.py``.
"""

import json

from mypy import api

# Keep the protected SQL adapter and eval instrument unchanged. Match file,
# line, column, code AND message so unrelated errors cannot hide here.
_BASELINE = {
    # Mypy cannot narrow url.database through the is_sqlite_file boolean.
    (
        "northwind_copilot/infra/database.py",
        74,
        58,
        "arg-type",
        'Argument 1 to "_readonly_sqlite_creator" has incompatible type '
        '"str | None"; expected "str"',
    ),
    # Pydantic accepts this existing field name at runtime, but the generated
    # constructor signature exposes only the max_completion_tokens alias.
    (
        "northwind_copilot/eval/multiturn/judges.py",
        188,
        11,
        "call-arg",
        'Unexpected keyword argument "max_tokens" for "ChatOpenAI"',
    ),
    # Pydantic coerces the existing string key to SecretStr at runtime.
    (
        "northwind_copilot/eval/multiturn/judges.py",
        191,
        16,
        "arg-type",
        'Argument "api_key" to "ChatOpenAI" has incompatible type "str"; '
        'expected "SecretStr | Callable[[], str] | '
        'Callable[[], Awaitable[str]] | None"',
    ),
}


def main() -> int:
    """Fail on unexpected diagnostics, tool errors, or stale exceptions."""
    stdout, stderr, status = api.run(["--output", "json"])
    remaining = set(_BASELINE)
    unexpected = []
    for line in stdout.splitlines():
        try:
            diagnostic = json.loads(line)
            key = tuple(
                diagnostic[field]
                for field in ("file", "line", "column", "code", "message")
            )
        except (ValueError, KeyError, TypeError):
            unexpected.append(line)
            continue
        if diagnostic.get("severity") == "error" and key in remaining:
            remaining.remove(key)
        else:
            unexpected.append(line)
    for line in unexpected:
        print(line)
    if stderr:
        print(stderr, end="")
    for entry in sorted(remaining):
        print(f"Stale mypy baseline: {entry}")
    if unexpected or remaining or stderr or status not in (0, 1):
        return 1
    print(
        f"Mypy passed; {len(_BASELINE)} exact protected-source diagnostics baselined."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
