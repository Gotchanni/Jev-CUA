"""Public model-price conversions; measured usage is supplied by run traces."""

from __future__ import annotations

from typing import Any

JEV_MODEL = "jev-1.13.0"
JEV_INPUT_USD_PER_MILLION = 0.042
CODEX_MODEL = "gpt-6-sol"
# Standard-speed Codex credits, not USD or a claim about actual account billing.
CODEX_CREDITS_PER_MILLION = (50.0, 5.0, 250.0)
# Published token-based Enterprise reference rate. Other plans/agreements may differ.
CODEX_ENTERPRISE_USD_PER_MILLION = (2.0, 0.2, 10.0)


def token_count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def jev_model_usd(input_tokens: int) -> float:
    return input_tokens * JEV_INPUT_USD_PER_MILLION / 1_000_000


def codex_standard_credits(input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
    if cached_input_tokens > input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens")
    uncached, cached, output = CODEX_CREDITS_PER_MILLION
    return (
        (input_tokens - cached_input_tokens) * uncached
        + cached_input_tokens * cached
        + output_tokens * output
    ) / 1_000_000


def codex_reference_usd(input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
    if cached_input_tokens > input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens")
    uncached, cached, output = CODEX_ENTERPRISE_USD_PER_MILLION
    return (
        (input_tokens - cached_input_tokens) * uncached
        + cached_input_tokens * cached
        + output_tokens * output
    ) / 1_000_000
