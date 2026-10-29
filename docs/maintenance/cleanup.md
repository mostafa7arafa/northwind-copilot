# Cleanup audit

## Scope and baseline

Base: `631aa9f` (master after PR #9). Backend Python only; no new tests,
frontend edits, prompt/graph/eval changes, runtime dependency upgrades, or API
changes. Preserve GPT-6 `reasoning_effort="none"` in `build_model`.

Baseline commands (UTF-8 environment):

```bash
PYTHONIOENCODING=utf-8 uv run pytest --cov --cov-report=term-missing
uv run black --check northwind_copilot tests
uv run isort --check-only northwind_copilot tests
uv run flake8 northwind_copilot tests
uv run vulture --min-confidence 0
```

Baseline: **269 passed**, 5 warnings; coverage reports **75%** including branches
(2,767 statements, 593 missed; 656 branches, 91 partial). All three lint checks
pass. Vulture 2.15 reports 94 findings: 7 at 100%, 87 at 60%. There are no
80–99% findings. Coverage identifies investigation targets, not proof of dead
code. Tests exercising a symbol are not proof that production uses it either.

`uv run vulture` uses the explicit Python source directories in `pyproject.toml`
and an 80% threshold. Generated/vendor directories are outside that scope.
`uv run vulture --min-confidence 0` is the separate, deliberately unsuppressed
low-confidence review list. Findings below 80% must not trigger deletion in this
cleanup. Vulture's symbol matching is not a call graph or proof of reachability.

This file lives below `docs/maintenance/` because the runtime knowledge-base
loader reads `docs/*.md`; maintenance notes must not become agent context.

## High-confidence findings: confirmed false positives

All seven are unused **parameters**, not unused functions or modules. Removing
these parameters would break caller compatibility. Retain their names and
signatures; suppress only the exact definition lines with `# noqa: F841`, with
an adjacent explanation. Do not use global name/decorator exclusions.

| Location | Parameter(s) | Evidence |
| --- | --- | --- |
| `core/observability.py::_before_send` | `hint` | Registered as Sentry's two-argument `before_send` callback in `init_sentry`; event scrubbing does not need the hint. |
| `query/middleware.py::make_trim_context.trim_context` | `runtime` | `@before_model` middleware receives state and runtime; trimming only needs state. Existing middleware tests exercise it. |
| `tests/test_eval_run_benchmark.py::_FakeGraph.invoke` | `inp` | Test double accepts the input passed by `eval/run_benchmark.py::run_one`. |
| `tests/test_infra_rag.py::_FakeFAISS.load_local` | `allow_dangerous_deserialization` | `infra/rag.py` passes this exact keyword to FAISS; the fake has no serialization to perform. |
| `tests/test_response_streaming.py::_FakeAgent.astream` | `inp`, `stream_mode` | `response/streaming.py` passes input and `stream_mode="updates"`; fake emits preconfigured updates. |
| `tests/test_response_streaming.py::_collect_stream` | `kw` | Monkeypatched `build_agent_for` accepts production keyword arguments while returning the configured fake. |

## Lower-confidence findings: review only, retain

All 87 findings below are at **60% confidence**. The groups account for the
entire raw report, without whitelisting potentially unused code.

### Alembic discovery: 42 findings

Each of the seven files in `migrations/versions/` reports `revision`,
`down_revision`, `branch_labels`, `depends_on`, `upgrade`, and `downgrade`.
Alembic discovers these through its script loader; retain all six symbols in:

- `4eba94e869de_002_datasets.py`
- `503821bd43e6_006_subscriptions_and_webhook_events.py`
- `8e47b15f5821_007_turn_feedback_and_golden_examples.py`
- `ae2f4b892fce_004_usage_events_and_credit_ledger.py`
- `b6711b926409_001_initial_identity_and_tenancy.py`
- `b82952102652_005_api_keys.py`
- `d13b693b1299_003_conversations_and_turns.py`

### FastAPI discovery: 27 findings

Route decorators register these functions; `web/app.py` includes the routers.
They are not direct Python calls. Retain:

- `auth/router.py`: `signup`, `login`, `logout`.
- `billing/router.py`: `list_plans`, `portal`, `webhook`, `mock_complete`,
  `mock_simulate`.
- `conversations/router.py`: `list_conversations`, `get_conversation`,
  `rename_conversation`, `delete_conversation`, `turn_feedback`.
- `datasets/router.py`: `upload_dataset`, `add_file`, `run_query`,
  `list_datasets`, `get_dataset`, `update_context`, `delete_dataset`.
- `keys/router.py`: `get_keys`, `put_key`, `remove_key`.
- `web/app.py`: `health`, `get_preferences`, `put_preferences`.
- `web/app.py::PreferencesRequest._strip`: Pydantic field validator, invoked during
  request validation rather than directly.

### ORM declarations and persistence: 11 findings

Mapped columns and relationships participate in SQLAlchemy metadata, schema,
assignment, and serialization; absence of a direct attribute read does not make
them removable. Retain:

- `billing/service.py`: assignment to `external_id`.
- `datasets/router.py`: two assignments to `size_bytes`.
- `tenancy/models.py`: `owner_user_id`, `members`, `size_bytes`, `conversation`,
  `external_id`, `processed_at`.
- `tenancy/models.py`: `oauth_accounts` and `provider_account_id` belong to the
  reserved OAuth schema; review alongside `OAuthAccount` below, not in isolation.

### Pytest discovery: 1 finding

- `tests/test_infra_rag.py::_patch_embeddings`: `@pytest.fixture(autouse=True)`;
  pytest invokes it to prevent real embeddings/network calls.

### Potentially unused or reserved: 6 findings, deferred

These are **not confirmed false positives** and remain visible in the
low-confidence report. Any removal needs separate approval, including a check
of documented configuration and schema compatibility:

- `core/config.py::frontend_origin`: no attribute consumer found; environment
  configuration is part of the documented hosted setup.
- `core/config.py::google_client_id` and `google_client_secret`: reserved Google
  OAuth integration configuration, documented as future work.
- `datasets/storage.py::org_usage_bytes`: no caller found; coverage misses its
  body. Potential dead quota helper, retained under the <80% review-only rule.
- `tenancy/models.py::OAuthAccount`: reserved mapped OAuth table, related to
  `User.oauth_accounts` and existing migration metadata; deleting a mapped model
  is not a safe assumption about schema behavior.
- `eval/multiturn/scenarios.py::NO_ROWS`: no executable reference found (only a
  docstring); eval is protected by the compatibility contract in `CLAUDE.md`.

## Deletions, moves, and renames

No high-confidence finding justifies deleting code. Existing flake8 checks find
no unused imports. A source-comment scan found no obsolete commented-out code
blocks to remove. No whole module was proven dead by the combined reference and
coverage audit. Do not delete low-confidence candidates to manufacture a diff.

Keep the existing `core`, `infra`, `query`, `response`, `web`, and `eval`
packages and separate hosted-domain packages. No module moves or identifier
renames are justified in this pass. In particular, do not relocate the static
graph or eval harness, rename `build_model`, or alter its GPT-6 handling.
