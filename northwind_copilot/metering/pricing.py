"""Static model pricing and the token → credit conversion.

Prices are USD per 1M tokens (input, output), matching the providers' public
rate cards for the curated models in ``web.models_registry``. One credit is
worth ``CREDIT_USD`` ($0.01), so a typical mini-class analyst turn costs about
one credit. Unknown models fall back to a deliberately conservative (high)
price so a free-typed frontier model can never be under-billed.
"""

from __future__ import annotations

from decimal import Decimal

# 1 credit ≈ $0.01 of LLM spend.
CREDIT_USD = Decimal("0.01")

# model id → (USD per 1M input tokens, USD per 1M output tokens).
# Keys are bare model ids; OpenRouter's "vendor/model" ids are normalised by
# stripping the vendor prefix before lookup, so both spellings resolve.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    # OpenAI
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    # Anthropic (via OpenRouter)
    "claude-sonnet-4": (Decimal("3.00"), Decimal("15.00")),
    # Google (via OpenRouter)
    "gemini-2.0-flash-001": (Decimal("0.10"), Decimal("0.40")),
    # Meta (via OpenRouter)
    "llama-3.3-70b-instruct": (Decimal("0.12"), Decimal("0.30")),
}

# Fallback for models not in the table: priced like a frontier model so an
# unlisted (free-typed) model id errs on over- rather than under-charging.
DEFAULT_PRICE: tuple[Decimal, Decimal] = (Decimal("3.00"), Decimal("15.00"))

_MILLION = Decimal(1_000_000)


def price_for(model: str) -> tuple[Decimal, Decimal]:
    """Return (input, output) USD per 1M tokens for a model id.

    Args:
        model: The provider model id, e.g. ``gpt-4.1-mini`` or the OpenRouter
            form ``openai/gpt-4.1-mini``.

    Returns:
        The per-million-token price pair, falling back to ``DEFAULT_PRICE``.
    """
    bare = model.rsplit("/", 1)[-1].strip().lower()
    return PRICES.get(bare, DEFAULT_PRICE)


def credits_for(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Price a turn's token usage in credits.

    Args:
        model: The model that served the turn.
        input_tokens: Total prompt tokens across the turn's model calls.
        output_tokens: Total completion tokens across the turn's model calls.

    Returns:
        The credit cost, quantised to 4 decimal places (matching the ledger's
        ``Numeric(12, 4)`` columns).
    """
    price_in, price_out = price_for(model)
    usd = (
        Decimal(input_tokens) * price_in + Decimal(output_tokens) * price_out
    ) / _MILLION
    return (usd / CREDIT_USD).quantize(Decimal("0.0001"))
